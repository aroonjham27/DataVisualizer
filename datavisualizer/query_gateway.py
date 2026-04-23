from __future__ import annotations

from dataclasses import dataclass, replace
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
    truncated: bool = False


@dataclass(frozen=True)
class ValidatedRestrictedQuery:
    sql: str
    execution_sql: str
    row_limit: int
    involved_entities: tuple[str, ...]
    validation_notes: tuple[str, ...]


@dataclass(frozen=True)
class _SqlToken:
    value: str
    normalized: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class _RelationRef:
    keyword: str
    entity: str
    alias: str
    on_tokens: tuple[_SqlToken, ...] = ()


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
        limit = row_limit if row_limit is not None else self.default_limit
        display_query = self.compiler.compile(plan, row_limit=limit)
        probe_query = self.compiler.compile(plan, row_limit=limit + 1)
        probe_result = execute_compiled_query(probe_query)
        result, truncated = self._trim_result(probe_result, limit)
        metadata = QueryMetadata(
            query_mode="compiled_plan",
            row_limit=display_query.row_limit,
            involved_entities=display_query.involved_entities,
            validation_notes=("Compiled from governed AnalysisPlan.", "Detected truncation with one-extra-row probing."),
        )
        return GatewayExecution(
            query_mode="compiled_plan",
            sql=display_query.sql,
            metadata=metadata,
            result=result,
            truncated=truncated,
        )

    def execute_restricted_sql(self, sql: str, row_limit: int | None = None) -> GatewayExecution:
        validated = self.restricted_sql.validate(sql, row_limit=row_limit)
        probe_result = execute_compiled_query(
            CompiledQuery(
                sql=validated.execution_sql,
                row_limit=validated.row_limit + 1,
                involved_entities=validated.involved_entities,
            )
        )
        result, truncated = self._trim_result(probe_result, validated.row_limit)
        metadata = QueryMetadata(
            query_mode="restricted_sql",
            row_limit=validated.row_limit,
            involved_entities=validated.involved_entities,
            validation_notes=validated.validation_notes,
        )
        return GatewayExecution(
            query_mode="restricted_sql",
            sql=validated.sql,
            metadata=metadata,
            result=result,
            truncated=truncated,
        )

    def _trim_result(self, result: QueryResult, limit: int) -> tuple[QueryResult, bool]:
        if len(result.rows) <= limit:
            return result, False
        return replace(result, rows=result.rows[:limit]), True


class RestrictedSqlQueryService:
    clause_keywords = {"where", "group", "order", "having", "limit"}
    relation_boundary_keywords = {"join", "where", "group", "order", "having", "limit"}
    blocked_keywords = {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "attach",
        "detach",
        "copy",
        "pragma",
        "call",
        "union",
        "except",
        "intersect",
        "cross",
        "with",
        "like",
        "ilike",
        "regexp",
    }

    def __init__(self, semantic_model: SemanticModel, default_limit: int = 500):
        self.semantic_model = semantic_model
        self.default_limit = default_limit

    def validate(self, sql: str, row_limit: int | None = None) -> ValidatedRestrictedQuery:
        limit = row_limit if row_limit is not None else self.default_limit
        if limit <= 0:
            raise RestrictedSqlValidationError("Row limit must be positive.")
        source_sql = self._normalize_sql_text(sql)
        tokens = self._tokenize(source_sql)
        source_sql = self._strip_trailing_limit(source_sql, tokens)
        tokens = self._tokenize(source_sql)
        self._validate_token_stream(tokens)
        relations = self._parse_relations(tokens)
        self._validate_relation_entities(relations)
        self._validate_join_edges(relations)
        self._validate_where_clause(tokens)
        involved_entities = tuple(dict.fromkeys(relation.entity for relation in relations))
        display_sql = self._wrap_with_governed_ctes(source_sql, involved_entities, limit)
        execution_sql = self._wrap_with_governed_ctes(source_sql, involved_entities, limit + 1)
        return ValidatedRestrictedQuery(
            sql=display_sql,
            execution_sql=execution_sql,
            row_limit=limit,
            involved_entities=involved_entities,
            validation_notes=(
                "Validated restricted SQL structure against the pilot subset.",
                "Validated restricted SQL entities and joins against the semantic model.",
                "Enforced gateway row limit.",
            ),
        )

    def _normalize_sql_text(self, sql: str) -> str:
        source_sql = sql.strip()
        if not source_sql:
            raise RestrictedSqlValidationError("SQL text is required.")
        if ";" in source_sql:
            raise RestrictedSqlValidationError("Restricted SQL must be a single statement without semicolons.")
        lowered = source_sql.lower()
        if "read_csv" in lowered or "read_parquet" in lowered:
            raise RestrictedSqlValidationError("Restricted SQL may not access files directly.")
        if "--" in source_sql or "/*" in source_sql or "*/" in source_sql:
            raise RestrictedSqlValidationError("SQL comments are not supported in restricted SQL.")
        return source_sql

    def _tokenize(self, sql: str) -> tuple[_SqlToken, ...]:
        tokens: list[_SqlToken] = []
        index = 0
        while index < len(sql):
            char = sql[index]
            if char.isspace():
                index += 1
                continue
            if char == "'":
                end = index + 1
                while end < len(sql):
                    if sql[end] == "'" and end + 1 < len(sql) and sql[end + 1] == "'":
                        end += 2
                        continue
                    if sql[end] == "'":
                        break
                    end += 1
                if end >= len(sql) or sql[end] != "'":
                    raise RestrictedSqlValidationError("Unterminated string literal.")
                value = sql[index : end + 1]
                tokens.append(_SqlToken(value=value, normalized=value, kind="string", start=index, end=end + 1))
                index = end + 1
                continue
            if char == '"':
                end = sql.find('"', index + 1)
                if end == -1:
                    raise RestrictedSqlValidationError("Unterminated quoted identifier.")
                value = sql[index + 1 : end]
                self._validate_identifier(value)
                tokens.append(_SqlToken(value=value, normalized=value.lower(), kind="identifier", start=index, end=end + 1))
                index = end + 1
                continue
            if char.isalpha() or char == "_":
                end = index + 1
                while end < len(sql) and (sql[end].isalnum() or sql[end] == "_"):
                    end += 1
                value = sql[index:end]
                tokens.append(_SqlToken(value=value, normalized=value.lower(), kind="identifier", start=index, end=end))
                index = end
                continue
            if char.isdigit():
                end = index + 1
                while end < len(sql) and (sql[end].isdigit() or sql[end] == "."):
                    end += 1
                value = sql[index:end]
                tokens.append(_SqlToken(value=value, normalized=value, kind="number", start=index, end=end))
                index = end
                continue
            two_char = sql[index : index + 2]
            if two_char in {"!=", "<>", "<=", ">="}:
                tokens.append(_SqlToken(value=two_char, normalized=two_char, kind="operator", start=index, end=index + 2))
                index += 2
                continue
            if char in "(),.*=<>":
                kind = "operator" if char in "=<>" else "punctuation"
                tokens.append(_SqlToken(value=char, normalized=char, kind=kind, start=index, end=index + 1))
                index += 1
                continue
            raise RestrictedSqlValidationError(f"Unsupported SQL character: {char}")
        if not tokens:
            raise RestrictedSqlValidationError("SQL text is required.")
        return tuple(tokens)

    def _strip_trailing_limit(self, sql: str, tokens: tuple[_SqlToken, ...]) -> str:
        limit_indexes = [index for index, token in enumerate(tokens) if token.normalized == "limit"]
        if not limit_indexes:
            return sql
        if len(limit_indexes) != 1:
            raise RestrictedSqlValidationError("Only one trailing LIMIT clause is supported.")
        limit_index = limit_indexes[0]
        if limit_index != len(tokens) - 2 or tokens[limit_index + 1].kind != "number":
            raise RestrictedSqlValidationError("LIMIT is only supported as a trailing numeric clause.")
        return sql[: tokens[limit_index].start].strip()

    def _validate_token_stream(self, tokens: tuple[_SqlToken, ...]) -> None:
        if tokens[0].normalized != "select":
            raise RestrictedSqlValidationError("Restricted SQL currently supports SELECT statements only.")
        depth = 0
        for token in tokens:
            if token.kind == "identifier":
                self._validate_identifier(token.value)
            if token.normalized in self.blocked_keywords:
                raise RestrictedSqlValidationError(f"Unsupported or unsafe SQL token: {token.value}")
            if token.normalized == "or":
                raise RestrictedSqlValidationError("OR predicates are not supported in restricted SQL.")
            if token.value == "(":
                depth += 1
            elif token.value == ")":
                depth -= 1
                if depth < 0:
                    raise RestrictedSqlValidationError("Unbalanced parentheses in restricted SQL.")
        if depth != 0:
            raise RestrictedSqlValidationError("Unbalanced parentheses in restricted SQL.")

    def _parse_relations(self, tokens: tuple[_SqlToken, ...]) -> tuple[_RelationRef, ...]:
        from_index = self._top_level_keyword(tokens, "from")
        if from_index is None:
            raise RestrictedSqlValidationError("Restricted SQL must include one semantic FROM entity.")
        relations: list[_RelationRef] = []
        index = from_index
        keyword = "from"
        while index < len(tokens):
            if tokens[index].normalized not in {"from", "join"}:
                break
            keyword = tokens[index].normalized
            index += 1
            entity, alias, index = self._parse_relation(tokens, index)
            if keyword == "from":
                relations.append(_RelationRef(keyword=keyword, entity=entity, alias=alias))
                if index < len(tokens) and tokens[index].value == ",":
                    raise RestrictedSqlValidationError("Comma joins are not supported in restricted SQL.")
                if index < len(tokens) and tokens[index].normalized == "join":
                    continue
                if index < len(tokens) and tokens[index].normalized not in self.clause_keywords:
                    raise RestrictedSqlValidationError("Unexpected token after FROM relation.")
                break
            if index >= len(tokens) or tokens[index].normalized != "on":
                raise RestrictedSqlValidationError(f"JOIN must include an ON clause for entity: {entity}")
            on_start = index + 1
            on_end = self._next_relation_boundary(tokens, on_start)
            on_tokens = tokens[on_start:on_end]
            if not on_tokens:
                raise RestrictedSqlValidationError(f"JOIN must include an ON clause for entity: {entity}")
            relations.append(_RelationRef(keyword=keyword, entity=entity, alias=alias, on_tokens=on_tokens))
            index = on_end
            if index < len(tokens) and tokens[index].value == ",":
                raise RestrictedSqlValidationError("Comma joins are not supported in restricted SQL.")
            if index >= len(tokens) or tokens[index].normalized != "join":
                if index < len(tokens) and tokens[index].normalized not in self.clause_keywords:
                    raise RestrictedSqlValidationError("Unexpected token after JOIN clause.")
                break
        if not relations or relations[0].keyword != "from":
            raise RestrictedSqlValidationError("Restricted SQL must include one semantic FROM entity.")
        return tuple(relations)

    def _parse_relation(self, tokens: tuple[_SqlToken, ...], index: int) -> tuple[str, str, int]:
        if index >= len(tokens):
            raise RestrictedSqlValidationError("Missing relation after FROM or JOIN.")
        if tokens[index].value == "(":
            raise RestrictedSqlValidationError("Subqueries and derived tables are not supported in restricted SQL.")
        entity = tokens[index].value
        self._validate_identifier(entity)
        index += 1
        alias = entity
        if index < len(tokens) and tokens[index].normalized == "as":
            index += 1
            if index >= len(tokens):
                raise RestrictedSqlValidationError("Missing alias after AS.")
            alias = tokens[index].value
            self._validate_identifier(alias)
            index += 1
        elif index < len(tokens) and self._can_be_alias(tokens[index]):
            alias = tokens[index].value
            self._validate_identifier(alias)
            index += 1
        return entity, alias, index

    def _can_be_alias(self, token: _SqlToken) -> bool:
        return token.kind == "identifier" and token.normalized not in self.relation_boundary_keywords and token.normalized != "on"

    def _validate_relation_entities(self, relations: tuple[_RelationRef, ...]) -> None:
        for relation in relations:
            if relation.entity not in self.semantic_model.entities:
                raise RestrictedSqlValidationError(f"Entity is not in the semantic model: {relation.entity}")

    def _validate_join_edges(self, relations: tuple[_RelationRef, ...]) -> None:
        known_aliases = {relations[0].alias: relations[0].entity, relations[0].entity: relations[0].entity}
        for relation in relations[1:]:
            if relation.keyword != "join":
                raise RestrictedSqlValidationError("Only explicit JOIN syntax is supported after FROM.")
            if not self._join_tokens_match_approved_edge(relation, known_aliases):
                raise RestrictedSqlValidationError(f"JOIN is not approved or lacks approved keys for entity: {relation.entity}")
            known_aliases[relation.alias] = relation.entity
            known_aliases[relation.entity] = relation.entity

    def _join_tokens_match_approved_edge(self, relation: _RelationRef, known_aliases: dict[str, str]) -> bool:
        if any(token.normalized not in {"and", ".", "=", "(", ")"} and token.kind not in {"identifier"} for token in relation.on_tokens):
            raise RestrictedSqlValidationError("JOIN predicates only support equality across approved keys joined by AND.")
        equality_pairs = self._extract_equality_pairs(relation.on_tokens)
        if not equality_pairs:
            return False
        known_entities = set(known_aliases.values())
        combined_aliases = {**known_aliases, relation.alias: relation.entity, relation.entity: relation.entity}
        for left_ref, right_ref in equality_pairs:
            left_entity = combined_aliases.get(left_ref[0])
            right_entity = combined_aliases.get(right_ref[0])
            if left_entity is None or right_entity is None:
                return False
            if relation.entity not in {left_entity, right_entity}:
                return False
            if left_entity == right_entity:
                return False
            if {left_entity, right_entity}.isdisjoint(known_entities | {relation.entity}):
                return False
            if not self._approved_join_key(left_entity, left_ref[1], right_entity, right_ref[1]):
                return False
        return True

    def _extract_equality_pairs(self, tokens: tuple[_SqlToken, ...]) -> list[tuple[tuple[str, str], tuple[str, str]]]:
        pairs = []
        parts = self._split_on_and(tokens)
        for part in parts:
            normalized_part = part
            if (
                len(normalized_part) != 7
                or normalized_part[1].value != "."
                or normalized_part[3].value != "="
                or normalized_part[5].value != "."
            ):
                raise RestrictedSqlValidationError("JOIN predicates must use alias.key = alias.key.")
            pairs.append(((normalized_part[0].value, normalized_part[2].value), (normalized_part[4].value, normalized_part[6].value)))
        return pairs

    def _split_on_and(self, tokens: tuple[_SqlToken, ...]) -> list[tuple[_SqlToken, ...]]:
        parts: list[tuple[_SqlToken, ...]] = []
        start = 0
        for index, token in enumerate(tokens):
            if token.normalized == "and":
                parts.append(tokens[start:index])
                start = index + 1
        parts.append(tokens[start:])
        return [part for part in parts if part]

    def _approved_join_key(self, left_entity: str, left_key: str, right_entity: str, right_key: str) -> bool:
        for join in self.semantic_model.allowed_joins:
            if join.status != "approved_for_v0":
                continue
            if {join.left_entity, join.right_entity} != {left_entity, right_entity}:
                continue
            for approved_left, approved_right in join.join_keys:
                if join.left_entity == left_entity and approved_left == left_key and approved_right == right_key:
                    return True
                if join.right_entity == left_entity and approved_right == left_key and approved_left == right_key:
                    return True
        return False

    def _validate_where_clause(self, tokens: tuple[_SqlToken, ...]) -> None:
        where_index = self._top_level_keyword(tokens, "where")
        if where_index is None:
            return
        end = self._next_clause_boundary(tokens, where_index + 1)
        predicates = self._split_on_and(tokens[where_index + 1 : end])
        if not predicates:
            raise RestrictedSqlValidationError("WHERE must include at least one predicate.")
        for predicate in predicates:
            self._validate_where_predicate(predicate)

    def _validate_where_predicate(self, tokens: tuple[_SqlToken, ...]) -> None:
        if not tokens:
            raise RestrictedSqlValidationError("Empty WHERE predicate.")
        normalized = [token.normalized for token in tokens]
        if "or" in normalized:
            raise RestrictedSqlValidationError("OR predicates are not supported in restricted SQL.")
        if "=" in normalized:
            if normalized.count("=") != 1:
                raise RestrictedSqlValidationError("WHERE equality predicates must contain one equals operator.")
            equals_index = normalized.index("=")
            self._validate_field_reference(tokens[:equals_index])
            self._validate_literal(tokens[equals_index + 1 :])
            return
        if "in" in normalized:
            in_index = normalized.index("in")
            self._validate_field_reference(tokens[:in_index])
            self._validate_in_literal_list(tokens[in_index + 1 :])
            return
        raise RestrictedSqlValidationError("WHERE predicates only support = and IN.")

    def _validate_field_reference(self, tokens: tuple[_SqlToken, ...]) -> None:
        if len(tokens) == 1 and tokens[0].kind == "identifier":
            return
        if len(tokens) == 3 and tokens[0].kind == "identifier" and tokens[1].value == "." and tokens[2].kind == "identifier":
            return
        raise RestrictedSqlValidationError("WHERE predicates must use a field reference.")

    def _validate_literal(self, tokens: tuple[_SqlToken, ...]) -> None:
        if len(tokens) != 1 or tokens[0].kind not in {"string", "number", "identifier"}:
            raise RestrictedSqlValidationError("WHERE predicates must compare to a simple literal.")

    def _validate_in_literal_list(self, tokens: tuple[_SqlToken, ...]) -> None:
        if len(tokens) < 3 or tokens[0].value != "(" or tokens[-1].value != ")":
            raise RestrictedSqlValidationError("IN predicates must use a parenthesized literal list.")
        expecting_value = True
        for token in tokens[1:-1]:
            if expecting_value:
                if token.kind not in {"string", "number", "identifier"}:
                    raise RestrictedSqlValidationError("IN predicates only support simple literals.")
                expecting_value = False
            else:
                if token.value != ",":
                    raise RestrictedSqlValidationError("IN predicate literals must be comma-separated.")
                expecting_value = True
        if expecting_value:
            raise RestrictedSqlValidationError("IN predicate literal list cannot end with a comma.")

    def _top_level_keyword(self, tokens: tuple[_SqlToken, ...], keyword: str) -> int | None:
        depth = 0
        for index, token in enumerate(tokens):
            if token.value == "(":
                depth += 1
            elif token.value == ")":
                depth -= 1
            elif depth == 0 and token.normalized == keyword:
                return index
        return None

    def _next_relation_boundary(self, tokens: tuple[_SqlToken, ...], start: int) -> int:
        depth = 0
        for index in range(start, len(tokens)):
            token = tokens[index]
            if token.value == "(":
                depth += 1
            elif token.value == ")":
                depth -= 1
            elif depth == 0 and token.normalized in self.relation_boundary_keywords:
                return index
        return len(tokens)

    def _next_clause_boundary(self, tokens: tuple[_SqlToken, ...], start: int) -> int:
        depth = 0
        for index in range(start, len(tokens)):
            token = tokens[index]
            if token.value == "(":
                depth += 1
            elif token.value == ")":
                depth -= 1
            elif depth == 0 and token.normalized in {"group", "order", "having", "limit"}:
                return index
        return len(tokens)

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

    def _validate_identifier(self, value: str) -> None:
        if not value.replace("_", "").isalnum() or not (value[0].isalpha() or value[0] == "_"):
            raise RestrictedSqlValidationError(f"Unsafe identifier: {value}")

    def _quote_identifier(self, value: str) -> str:
        self._validate_identifier(value)
        return f'"{value}"'

    def _literal(self, value: str | Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"
