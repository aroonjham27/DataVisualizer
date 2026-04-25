from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .contracts import PlannedField
from .semantic_model import SemanticModel


def normalize_semantic_term(text: str) -> str:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


@dataclass(frozen=True)
class FieldResolution:
    field: PlannedField
    requested_term: str
    matched_term: str
    match_source: str
    score: int
    warning: str | None = None


@dataclass(frozen=True)
class _FieldAlias:
    field: PlannedField
    term: str
    source: str
    weight: int


class SemanticFieldResolver:
    def __init__(self, semantic_model: SemanticModel, join_cost: Callable[[str, str], int | None]):
        self.semantic_model = semantic_model
        self.join_cost = join_cost
        self._aliases = self._build_aliases()

    def requested_breakdown_terms(self, normalized_text: str) -> tuple[str, ...]:
        captures: list[str] = []
        patterns = (
            r"\b(?:break(?: it)? down|broken down|breakdown|vary|group|grouped|slice|split)\s+by\s+(.+)",
            r"\bby\s+(.+)",
            r"\badd\s+(?:a\s+)?(?:breakdown\s+by\s+)?(.+)",
            r"\b(?:go|drill)(?: one level)? deeper\s+(?:to|into|by)\s+(.+)",
            r"\bdrill\s+(?:down\s+)?(?:to|into|by)\s+(.+)",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, normalized_text):
                captures.append(match.group(1))
        terms: list[str] = []
        for capture in captures:
            terms.extend(self._split_requested_terms(self._trim_capture(capture)))
        return tuple(dict.fromkeys(term for term in terms if term))

    def resolve_dimensions(
        self,
        normalized_text: str,
        *,
        primary_entity: str,
        current_entities: Iterable[str] = (),
        existing_field_ids: Iterable[str] = (),
    ) -> tuple[FieldResolution, ...]:
        return self.resolve_dimension_terms(
            self.requested_breakdown_terms(normalized_text),
            primary_entity=primary_entity,
            current_entities=current_entities,
            existing_field_ids=existing_field_ids,
        )

    def resolve_dimension_terms(
        self,
        requested_terms: Iterable[str],
        *,
        primary_entity: str,
        current_entities: Iterable[str] = (),
        existing_field_ids: Iterable[str] = (),
    ) -> tuple[FieldResolution, ...]:
        current_entity_set = set(current_entities)
        existing_field_set = set(existing_field_ids)
        resolved: list[FieldResolution] = []
        selected_field_ids: set[str] = set()
        for requested_term in requested_terms:
            candidates = self._rank_candidates(
                requested_term,
                primary_entity=primary_entity,
                current_entities=current_entity_set,
            )
            candidates = [
                candidate
                for candidate in candidates
                if candidate.field.field_id not in existing_field_set and candidate.field.field_id not in selected_field_ids
            ]
            if not candidates:
                continue
            best = candidates[0]
            warning = None
            is_close_score = len(candidates) > 1 and candidates[1].score >= best.score - 40
            is_same_explicit_term = len(candidates) > 1 and candidates[1].matched_term == requested_term and candidates[1].score >= best.score - 55
            if is_close_score or is_same_explicit_term:
                alternate_note = candidates[1].field.field_id
                if candidates[1].field.field_id == "accounts.sales_region":
                    alternate_note = "account-level sales region"
                warning = (
                    f"Resolved '{requested_term}' to {best.field.field_id}; "
                    f"{alternate_note} was also plausible."
                )
            resolved.append(
                FieldResolution(
                    field=best.field,
                    requested_term=requested_term,
                    matched_term=best.matched_term,
                    match_source=best.match_source,
                    score=best.score,
                    warning=warning,
                )
            )
            selected_field_ids.add(best.field.field_id)
        return tuple(resolved)

    def _rank_candidates(
        self,
        requested_term: str,
        *,
        primary_entity: str,
        current_entities: set[str],
    ) -> list[FieldResolution]:
        requested_term = normalize_semantic_term(requested_term)
        ranked_by_field: dict[str, FieldResolution] = {}
        for alias in self._aliases:
            if alias.field.kind != "dimension":
                continue
            match_score = self._match_score(requested_term, alias)
            if match_score is None:
                continue
            join_cost = self.join_cost(primary_entity, alias.field.entity)
            if join_cost is None:
                continue
            score = match_score
            if alias.field.entity == primary_entity:
                score += 30
            if alias.field.entity in current_entities:
                score += 15
            score -= join_cost * 5
            existing = ranked_by_field.get(alias.field.field_id)
            candidate = FieldResolution(
                field=alias.field,
                requested_term=requested_term,
                matched_term=alias.term,
                match_source=alias.source,
                score=score,
            )
            if existing is None or candidate.score > existing.score:
                ranked_by_field[alias.field.field_id] = candidate
        return sorted(
            ranked_by_field.values(),
            key=lambda item: (
                -item.score,
                0 if item.field.entity == primary_entity else 1,
                item.field.field_id,
            ),
        )

    def _match_score(self, requested_term: str, alias: _FieldAlias) -> int | None:
        if requested_term == alias.term:
            return alias.weight
        if len(alias.term.split()) > 1 and self._contains_term(requested_term, alias.term):
            return alias.weight - 20
        if len(requested_term.split()) > 1 and self._contains_term(alias.term, requested_term):
            return alias.weight - 45
        return None

    def _contains_term(self, haystack: str, needle: str) -> bool:
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None

    def _build_aliases(self) -> tuple[_FieldAlias, ...]:
        aliases: list[_FieldAlias] = []
        for entity in self.semantic_model.entities.values():
            entity_terms = self._entity_terms(entity.name, entity.label, entity.synonyms)
            for field in entity.dimensions:
                planned = PlannedField(entity=entity.name, name=field.name, label=field.label, kind="dimension")
                aliases.extend(self._field_aliases(planned, field.name, field.label, field.synonyms, entity_terms))
            for field in entity.time_dimensions:
                planned = PlannedField(entity=entity.name, name=field.name, label=field.label, kind="time_dimension")
                aliases.extend(self._field_aliases(planned, field.name, field.label, (), entity_terms))
                aliases.extend(self._time_grain_aliases(planned, field.name, field.label, field.grain))
            for measure in entity.measures:
                planned = PlannedField(entity=entity.name, name=measure.name, label=measure.label, kind="measure")
                aliases.extend(self._field_aliases(planned, measure.name, measure.label, (), entity_terms))
        drill_field_ids = {level for hierarchy in self.semantic_model.drill_hierarchies for level in hierarchy.levels}
        aliases.extend(alias for alias in self._aliases_for_drill_levels(drill_field_ids))
        deduped: dict[tuple[str, str, str], _FieldAlias] = {}
        for alias in aliases:
            if len(alias.term) < 3:
                continue
            key = (alias.field.field_id, alias.term, alias.source)
            existing = deduped.get(key)
            if existing is None or alias.weight > existing.weight:
                deduped[key] = alias
        return tuple(deduped.values())

    def _field_aliases(
        self,
        field: PlannedField,
        name: str,
        label: str,
        synonyms: tuple[str, ...],
        entity_terms: tuple[str, ...],
    ) -> list[_FieldAlias]:
        aliases = [
            _FieldAlias(field=field, term=normalize_semantic_term(label), source="label", weight=100),
            _FieldAlias(field=field, term=normalize_semantic_term(name), source="name", weight=90),
        ]
        aliases.extend(_FieldAlias(field=field, term=normalize_semantic_term(term), source="synonym", weight=105) for term in synonyms)
        field_core_terms = self._field_core_terms(name, label)
        aliases.extend(_FieldAlias(field=field, term=term, source="derived", weight=70) for term in field_core_terms)
        for entity_term in entity_terms:
            for field_term in field_core_terms:
                if not field_term.startswith(entity_term):
                    aliases.append(_FieldAlias(field=field, term=f"{entity_term} {field_term}", source="entity_qualified", weight=95))
        return aliases

    def _time_grain_aliases(
        self,
        field: PlannedField,
        name: str,
        label: str,
        grains: tuple[str, ...],
    ) -> list[_FieldAlias]:
        bases = set(self._field_core_terms(name, label))
        normalized_label = normalize_semantic_term(label)
        if normalized_label.endswith(" date"):
            bases.add(normalized_label.removesuffix(" date"))
        aliases: list[_FieldAlias] = []
        for base in bases:
            for grain in grains:
                aliases.append(_FieldAlias(field=field, term=f"{base} {grain}", source="time_grain", weight=100))
        return aliases

    def _aliases_for_drill_levels(self, field_ids: set[str]) -> tuple[_FieldAlias, ...]:
        aliases = []
        for field_id in field_ids:
            entity_name, field_name = field_id.split(".", 1)
            entity = self.semantic_model.entity(entity_name)
            try:
                field = entity.get_dimension(field_name)
                planned = PlannedField(entity=entity_name, name=field.name, label=field.label, kind="dimension")
                for term in self._field_core_terms(field.name, field.label):
                    aliases.append(_FieldAlias(field=planned, term=term, source="drill_level", weight=85))
                continue
            except KeyError:
                pass
            try:
                field = entity.get_time_dimension(field_name)
                planned = PlannedField(entity=entity_name, name=field.name, label=field.label, kind="time_dimension")
                for term in self._field_core_terms(field.name, field.label):
                    aliases.append(_FieldAlias(field=planned, term=term, source="drill_level", weight=85))
            except KeyError:
                continue
        return tuple(aliases)

    def _entity_terms(self, name: str, label: str, synonyms: tuple[str, ...]) -> tuple[str, ...]:
        raw_terms = [name, label, *synonyms]
        terms: list[str] = []
        for raw_term in raw_terms:
            normalized = normalize_semantic_term(raw_term)
            if not normalized:
                continue
            terms.append(normalized)
            if normalized.endswith("s"):
                terms.append(normalized[:-1])
        return tuple(dict.fromkeys(terms))

    def _field_core_terms(self, name: str, label: str) -> tuple[str, ...]:
        terms = [normalize_semantic_term(name), normalize_semantic_term(label)]
        for term in list(terms):
            parts = term.split()
            if len(parts) > 1:
                terms.append(" ".join(parts[1:]))
                if parts[0] not in {"is", "has"}:
                    terms.append(parts[-1])
        return tuple(dict.fromkeys(term for term in terms if term))

    def _trim_capture(self, capture: str) -> str:
        capture = re.split(r"\b(?:for|where|when|with)\b", capture, maxsplit=1)[0]
        capture = re.sub(r"\b(?:only|please|instead|now|that|it)\b", " ", capture)
        return normalize_semantic_term(capture)

    def _split_requested_terms(self, capture: str) -> list[str]:
        capture = re.sub(r"\s+(?:and|plus|also)\s+", ",", capture)
        terms: list[str] = []
        for part in capture.split(","):
            normalized = normalize_semantic_term(part)
            if not normalized:
                continue
            expanded = self._expand_compound_term(normalized)
            terms.extend(expanded or [normalized])
        return terms

    def _expand_compound_term(self, term: str) -> list[str]:
        matches: list[tuple[int, int, int, str]] = []
        for alias in self._aliases:
            if alias.field.kind not in {"dimension", "time_dimension"}:
                continue
            for match in re.finditer(rf"\b{re.escape(alias.term)}\b", term):
                matches.append((match.start(), match.end(), len(alias.term.split()), alias.term))
        if len(matches) < 2:
            return []
        selected: list[tuple[int, int, str]] = []
        occupied: list[tuple[int, int]] = []
        for start, end, _words, alias_term in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]), -item[2])):
            if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
                continue
            selected.append((start, end, alias_term))
            occupied.append((start, end))
        selected.sort(key=lambda item: item[0])
        return [alias_term for _start, _end, alias_term in selected]
