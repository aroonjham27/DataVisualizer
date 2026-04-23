from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _normalize_terms(values: list[str] | None) -> tuple[str, ...]:
    return tuple(values or ())


@dataclass(frozen=True)
class SemanticField:
    name: str
    label: str
    type: str
    synonyms: tuple[str, ...] = ()
    semantic_status: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SemanticField":
        return cls(
            name=str(payload["name"]),
            label=str(payload["label"]),
            type=str(payload["type"]),
            synonyms=_normalize_terms(payload.get("synonyms")),  # type: ignore[arg-type]
            semantic_status=payload.get("semantic_status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SemanticMeasure:
    name: str
    label: str
    aggregation: str
    field: str | None = None
    filter: str | None = None
    definition: str | None = None
    non_additive: bool = False
    guardrail: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SemanticMeasure":
        return cls(
            name=str(payload["name"]),
            label=str(payload["label"]),
            aggregation=str(payload["aggregation"]),
            field=payload.get("field"),  # type: ignore[arg-type]
            filter=payload.get("filter"),  # type: ignore[arg-type]
            definition=payload.get("definition"),  # type: ignore[arg-type]
            non_additive=bool(payload.get("non_additive", False)),
            guardrail=payload.get("guardrail"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SemanticTimeDimension:
    name: str
    label: str
    grain: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SemanticTimeDimension":
        return cls(
            name=str(payload["name"]),
            label=str(payload["label"]),
            grain=tuple(payload.get("grain", ())),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SemanticEntity:
    name: str
    label: str
    synonyms: tuple[str, ...]
    role: str
    grain: str
    source_file: str
    primary_key: str
    default_label: str
    identifiers: tuple[str, ...]
    dimensions: tuple[SemanticField, ...]
    measures: tuple[SemanticMeasure, ...]
    time_dimensions: tuple[SemanticTimeDimension, ...]
    ambiguity_flags: tuple[str, ...]

    @classmethod
    def from_dict(cls, name: str, payload: dict[str, object]) -> "SemanticEntity":
        return cls(
            name=name,
            label=str(payload["label"]),
            synonyms=_normalize_terms(payload.get("synonyms")),  # type: ignore[arg-type]
            role=str(payload["role"]),
            grain=str(payload["grain"]),
            source_file=str(payload["source_file"]),
            primary_key=str(payload["primary_key"]),
            default_label=str(payload["default_label"]),
            identifiers=tuple(payload.get("identifiers", ())),  # type: ignore[arg-type]
            dimensions=tuple(SemanticField.from_dict(item) for item in payload.get("dimensions", ())),  # type: ignore[arg-type]
            measures=tuple(SemanticMeasure.from_dict(item) for item in payload.get("measures", ())),  # type: ignore[arg-type]
            time_dimensions=tuple(SemanticTimeDimension.from_dict(item) for item in payload.get("time_dimensions", ())),  # type: ignore[arg-type]
            ambiguity_flags=tuple(payload.get("ambiguity_flags", ())),  # type: ignore[arg-type]
        )

    def get_dimension(self, name: str) -> SemanticField:
        for field in self.dimensions:
            if field.name == name:
                return field
        raise KeyError(f"Dimension not found: {self.name}.{name}")

    def get_measure(self, name: str) -> SemanticMeasure:
        for measure in self.measures:
            if measure.name == name:
                return measure
        raise KeyError(f"Measure not found: {self.name}.{name}")

    def get_time_dimension(self, name: str) -> SemanticTimeDimension:
        for field in self.time_dimensions:
            if field.name == name:
                return field
        raise KeyError(f"Time dimension not found: {self.name}.{name}")


@dataclass(frozen=True)
class SemanticJoin:
    left_entity: str
    right_entity: str
    cardinality: str
    join_keys: tuple[tuple[str, str], ...]
    status: str
    notes: str

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SemanticJoin":
        keys = tuple((item["left"], item["right"]) for item in payload.get("join_keys", ()))  # type: ignore[index]
        return cls(
            left_entity=str(payload["left_entity"]),
            right_entity=str(payload["right_entity"]),
            cardinality=str(payload["cardinality"]),
            join_keys=keys,
            status=str(payload["status"]),
            notes=str(payload.get("notes", "")),
        )


@dataclass(frozen=True)
class DrillHierarchy:
    name: str
    label: str
    levels: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "DrillHierarchy":
        return cls(
            name=str(payload["name"]),
            label=str(payload["label"]),
            levels=tuple(payload.get("levels", ())),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SemanticModel:
    name: str
    version: str
    status: str
    purpose: str
    source_dataset: dict[str, object]
    evidence: tuple[str, ...]
    modeling_principles: tuple[str, ...]
    entities: dict[str, SemanticEntity]
    allowed_joins: tuple[SemanticJoin, ...]
    join_guardrails: tuple[str, ...]
    drill_hierarchies: tuple[DrillHierarchy, ...]
    global_ambiguity_flags: tuple[str, ...]
    repo_root: Path = field(compare=False)
    model_path: Path = field(compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, object], model_path: Path) -> "SemanticModel":
        semantic_model = payload["semantic_model"]  # type: ignore[index]
        repo_root = model_path.parents[2]
        entities = {
            name: SemanticEntity.from_dict(name, entity_payload)
            for name, entity_payload in semantic_model["entities"].items()  # type: ignore[index]
        }
        return cls(
            name=str(semantic_model["name"]),
            version=str(semantic_model["version"]),
            status=str(semantic_model["status"]),
            purpose=str(semantic_model["purpose"]),
            source_dataset=dict(semantic_model.get("source_dataset", {})),  # type: ignore[arg-type]
            evidence=tuple(semantic_model.get("evidence", ())),  # type: ignore[arg-type]
            modeling_principles=tuple(semantic_model.get("modeling_principles", ())),  # type: ignore[arg-type]
            entities=entities,
            allowed_joins=tuple(SemanticJoin.from_dict(item) for item in semantic_model.get("allowed_joins", ())),  # type: ignore[arg-type]
            join_guardrails=tuple(semantic_model.get("join_guardrails", ())),  # type: ignore[arg-type]
            drill_hierarchies=tuple(DrillHierarchy.from_dict(item) for item in semantic_model.get("drill_hierarchies", ())),  # type: ignore[arg-type]
            global_ambiguity_flags=tuple(semantic_model.get("global_ambiguity_flags", ())),  # type: ignore[arg-type]
            repo_root=repo_root,
            model_path=model_path,
        )

    def entity(self, name: str) -> SemanticEntity:
        return self.entities[name]

    def source_path_for_entity(self, entity_name: str) -> Path:
        return self.repo_root / self.entity(entity_name).source_file

    def drill_hierarchy(self, name: str) -> DrillHierarchy:
        for hierarchy in self.drill_hierarchies:
            if hierarchy.name == name:
                return hierarchy
        raise KeyError(f"Drill hierarchy not found: {name}")


def load_semantic_model(model_path: str | Path) -> SemanticModel:
    path = Path(model_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SemanticModel.from_dict(payload, path)
