from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import AnalysisPlan, QueryMetadata
from .execution import QueryResult, execute_compiled_query
from .planner import DEFAULT_MODEL_PATH
from .semantic_model import SemanticModel, load_semantic_model
from .sql_compiler import CompiledQuery, DuckDbSqlCompiler


class RestrictedSqlValidationError(ValueError):
    """Raised when restricted SQL does not satisfy the governed pilot shape."""


@dataclass(frozen=True)
class GatewayExecution:
    query_mode: str
    sql: str
    metadata: QueryMetadata
    result: QueryResult


@dataclass(frozen=True)
class ValidatedRestrictedQuery:
    sql: str
    row_limit: int
    involved_entities: tuple[str, ...]
    validation_notes: tuple[str, ...]


@dataclass(frozen=True)
class _RelationRef:
    keyword: str
    entity: str
    alias: str
    start: int
    end: int


class QueryGateway:
    def __init__(self, semantic_model: SemanticModel, default_limit: int = 500):
        self.semantic_model = semantic_model
        self.default_limit = default_limit
        self.compiler = DuckDbSqlCompiler(semantic_model, default_limit=default_limit)
        self.restricted_sql = RestrictedSqlQueryService(semantic_model, default_limit=default_limit)

    @classmethod
    def from_default_model(cls, default_limit: int = 500) -> "QueryGateway":
        return cls(load_semantic_model(DEFAULT_MODEL_PATH), default_limit=default_limit)

    def execute_compiled_plan(self, plan: AnalysisPlan, row_limit: int | None = None) -> GatewayExecution:
        compiled = self.compiler.compile(plan, row_limit=row_limit)
        result = execute_compiled_query(compiled)
        metadata = QueryMetadata(
            query_mode="compiled_plan",
            row_limit=compiled.row_limit,
            involved_entities=compiled.involved_entities,
            validation_notes=("Compiled from governed AnalysisPlan.",),
        )
        return GatewayExecution(query_mode="compiled_plan", sql=compiled.sql, metadata=metadata, result=result)

    def execute_restricted_sql(self, sql: str, row_limit: int | None = None) -> GatewayExecution:
        validated = self.restricted_sql.validate(sql, row_limit=row_limit)
        result = execute_compiled_query(
            CompiledQuery(sql=validated.sql, row_limit=validated.row_limit, involved_entities=validated.involved_entities)
        )
        metadata = QueryMetadata(
            query_mode="restricted_sql",
            row_limit=validated.row_limit,
            involved_entities=validated.involved_entities,
            validation_notes=validated.validation_notes,
        )
        return GatewayExecution(query_mode="restricted_sql", sql=validated.sql, metadata=metadata, result=result)


class RestrictedSqlQueryService:
    _relation_pattern = re.compile(
        r"\b(?P<keyword>from|join)\s+(?P<entity>\"?[A-Za-z_][A-Za-z0-9_]*\"?)"
        r"(?:\s+(?:as\s+)?(?P<alias>(?!on\b|join\b|where\b|group\b|order\b|limit\b|having\b)\"?[A-Za-z_][A-Za-z0-9_]*\"?))?",
        re.IGNORECASE,
    )
    _join_clause_end_pattern = re.compile(r"\b(join|where|group\s+by|order\s+by|limit|having)\b", re.IGNORECASE)
    _trailing_limit_pattern = re.compile(r"\s+limit\s+\d+\s*$", re.IGNORECASE)

    def __init__(self, semantic_model: SemanticModel, default_limit: int = 500):
        self.semantic_model = semantic_model
        self.default_limit = default_limit

    def validate(self, sql: str, row_limit: int | None = None) -> ValidatedRestrictedQuery:
        limit = row_limit if row_limit is not None else self.default_limit
        if limit <= 0:
            raise RestrictedSqlValidationError("Row limit must be positive.")
        source_sql = self._normalize_sql_text(sql)
        self._validate_read_only_surface(source_sql)
        source_sql = self._strip_trailing_limit(source_sql)
        relations = self._extract_relations(source_sql)
        self._validate_relation_entities(relations)
        self._validate_join_edges(source_sql, relations)
        involved_entities = tuple(dict.fromkeys(relation.entity for relation in relations))
        governed_sql = self._wrap_with_governed_ctes(source_sql, involved_entities, limit)
        return ValidatedRestrictedQuery(
            sql=governed_sql,
            row_limit=limit,
            involved_entities=involved_entities,
            validation_notes=(
                "Validated restricted SQL against semantic model entities.",
                "Enforced gateway row limit.",
            ),
        )

    def _normalize_sql_text(self, sql: str) -> str:
        source_sql = sql.strip()
        if not source_sql:
            raise RestrictedSqlValidationError("SQL text is required.")
        if ";" in source_sql:
            raise RestrictedSqlValidationError("Restricted SQL must be a single statement without semicolons.")
        return source_sql

    def _validate_read_only_surface(self, sql: str) -> None:
        normalized = f" {' '.join(sql.lower().split())} "
        if not normalized.strip().startswith("select "):
            raise RestrictedSqlValidationError("Restricted SQL currently supports SELECT statements only.")
        blocked_tokens = (
            " insert ",
            " update ",
            " delete ",
            " drop ",
            " alter ",
            " create ",
            " attach ",
            " detach ",
            " copy ",
            " pragma ",
            " call ",
            " union ",
            " except ",
            " intersect ",
            " like ",
            " ilike ",
            " regexp ",
            " or ",
        )
        for token in blocked_tokens:
            if token in normalized:
                raise RestrictedSqlValidationError(f"Unsupported or unsafe SQL token: {token.strip()}")
        if "read_csv" in normalized or "read_parquet" in normalized:
            raise RestrictedSqlValidationError("Restricted SQL may not access files directly.")
        for identifier in re.findall(r'"([^"]+)"', sql):
            self._validate_identifier(identifier)

    def _strip_trailing_limit(self, sql: str) -> str:
        limit_matches = list(re.finditer(r"\blimit\b", sql, flags=re.IGNORECASE))
        if not limit_matches:
            return sql
        stripped = self._trailing_limit_pattern.sub("", sql).strip()
        if stripped == sql:
            raise RestrictedSqlValidationError("LIMIT is only supported as a trailing clause.")
        return stripped

    def _extract_relations(self, sql: str) -> tuple[_RelationRef, ...]:
        relations = []
        for match in self._relation_pattern.finditer(sql):
            keyword = match.group("keyword").lower()
            entity = self._clean_identifier(match.group("entity"))
            alias = self._clean_identifier(match.group("alias") or entity)
            if alias.lower() in {"on", "where", "group", "order", "limit", "having"}:
                alias = entity
            self._validate_identifier(entity)
            self._validate_identifier(alias)
            relations.append(_RelationRef(keyword=keyword, entity=entity, alias=alias, start=match.start(), end=match.end()))
        keyword_count = len(re.findall(r"\b(from|join)\b", sql, flags=re.IGNORECASE))
        if keyword_count != len(relations):
            raise RestrictedSqlValidationError("Restricted SQL contains unsupported relation syntax.")
        if not relations or relations[0].keyword != "from":
            raise RestrictedSqlValidationError("Restricted SQL must include one semantic FROM entity.")
        return tuple(relations)

    def _validate_relation_entities(self, relations: tuple[_RelationRef, ...]) -> None:
        for relation in relations:
            if relation.entity not in self.semantic_model.entities:
                raise RestrictedSqlValidationError(f"Entity is not in the semantic model: {relation.entity}")

    def _validate_join_edges(self, sql: str, relations: tuple[_RelationRef, ...]) -> None:
        known_aliases = {relations[0].alias: relations[0].entity, relations[0].entity: relations[0].entity}
        for index, relation in enumerate(relations[1:], start=1):
            if relation.keyword != "join":
                raise RestrictedSqlValidationError("Only explicit JOIN syntax is supported after FROM.")
            on_clause = self._join_on_clause(sql, relation, relations[index + 1] if index + 1 < len(relations) else None)
            if not self._join_clause_matches_approved_edge(relation, known_aliases, on_clause):
                raise RestrictedSqlValidationError(f"JOIN is not approved or lacks approved keys for entity: {relation.entity}")
            known_aliases[relation.alias] = relation.entity
            known_aliases[relation.entity] = relation.entity

    def _join_on_clause(self, sql: str, relation: _RelationRef, next_relation: _RelationRef | None) -> str:
        search_end = next_relation.start if next_relation else len(sql)
        segment = sql[relation.end:search_end]
        on_match = re.search(r"\bon\b", segment, flags=re.IGNORECASE)
        if not on_match:
            raise RestrictedSqlValidationError(f"JOIN must include an ON clause for entity: {relation.entity}")
        on_text = segment[on_match.end():]
        clause_end = self._join_clause_end_pattern.search(on_text)
        if clause_end:
            on_text = on_text[: clause_end.start()]
        return on_text

    def _join_clause_matches_approved_edge(
        self,
        relation: _RelationRef,
        known_aliases: dict[str, str],
        on_clause: str,
    ) -> bool:
        normalized_on = re.sub(r"\s+", " ", on_clause.replace('"', "")).lower()
        known_entities = set(known_aliases.values())
        combined_aliases = {**known_aliases, relation.alias: relation.entity, relation.entity: relation.entity}
        for known_entity in known_entities:
            for join in self.semantic_model.allowed_joins:
                if join.status != "approved_for_v0":
                    continue
                entities = {join.left_entity, join.right_entity}
                if entities != {known_entity, relation.entity}:
                    continue
                for left_key, right_key in join.join_keys:
                    left_aliases = self._aliases_for_entity(combined_aliases, join.left_entity)
                    right_aliases = self._aliases_for_entity(combined_aliases, join.right_entity)
                    if self._key_pair_in_clause(left_aliases, left_key, right_aliases, right_key, normalized_on):
                        return True
                    if self._key_pair_in_clause(right_aliases, right_key, left_aliases, left_key, normalized_on):
                        return True
        return False

    def _aliases_for_entity(self, alias_map: dict[str, str], entity: str) -> tuple[str, ...]:
        aliases = [alias for alias, mapped_entity in alias_map.items() if mapped_entity == entity]
        if entity not in aliases:
            aliases.append(entity)
        return tuple(dict.fromkeys(aliases))

    def _key_pair_in_clause(
        self,
        left_aliases: tuple[str, ...],
        left_key: str,
        right_aliases: tuple[str, ...],
        right_key: str,
        on_clause: str,
    ) -> bool:
        for left_alias in left_aliases:
            for right_alias in right_aliases:
                left = f"{left_alias.lower()}.{left_key.lower()}"
                right = f"{right_alias.lower()}.{right_key.lower()}"
                if f"{left} = {right}" in on_clause or f"{left}={right}" in on_clause:
                    return True
        return False

    def _wrap_with_governed_ctes(self, sql: str, involved_entities: tuple[str, ...], limit: int) -> str:
        ctes = []
        for entity_name in involved_entities:
            path = self.semantic_model.source_path_for_entity(entity_name).resolve()
            if not path.exists():
                raise RestrictedSqlValidationError(f"Source file not found for entity {entity_name}: {path}")
            ctes.append(
                f"{self._quote_identifier(entity_name)} AS ("
                f"SELECT * FROM read_csv_auto({self._literal(str(path))}, header=true)"
                f")"
            )
        return "\n".join(
            [
                "WITH",
                ",\n".join(ctes),
                "SELECT *",
                f"FROM (\n{sql}\n) AS {self._quote_identifier('governed_query')}",
                f"LIMIT {limit}",
            ]
        )

    def _clean_identifier(self, value: str) -> str:
        return value.strip().strip('"')

    def _validate_identifier(self, value: str) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise RestrictedSqlValidationError(f"Unsafe identifier: {value}")

    def _quote_identifier(self, value: str) -> str:
        self._validate_identifier(value)
        return f'"{value}"'

    def _literal(self, value: str | Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"
