from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import console
from config import Relation
from errors import UserError
from psycopg import sql

MAX_VALUE_LEN = 10000
MAX_IN_VALUES = 1000

SCHEMA_QUERY = (
    "SELECT table_name::text, column_name::text, data_type::text, "
    "is_nullable::text = 'YES', column_default IS NOT NULL, is_identity::text = 'YES' "
    "FROM information_schema.columns "
    "WHERE table_schema = 'public' AND table_name::text = ANY(%s) "
    "ORDER BY table_name::text, ordinal_position"
)

Pairs = Sequence[tuple[str, Any]]


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    has_default: bool
    identity: bool


class Repository:
    def __init__(
        self,
        conn: Any,
        tables: Iterable[str],
        display_limit: int,
        relations: Iterable[Relation],
    ) -> None:
        self._conn = conn
        self._allowed = tuple(tables)
        self._limit = display_limit
        self._configured_relations = tuple(relations)
        self._relations: tuple[Relation, ...] = ()
        self._schema: dict[str, tuple[Column, ...]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    def load_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA_QUERY, [list(self._allowed)])
            rows = cur.fetchall()
        grouped: dict[str, list[Column]] = {}
        for table, name, data_type, nullable, has_default, identity in rows:
            grouped.setdefault(table, []).append(
                Column(name, data_type, nullable, has_default, identity)
            )
        self.set_schema({table: tuple(cols) for table, cols in grouped.items()})

    def set_schema(self, schema: dict[str, tuple[Column, ...]]) -> None:
        self._schema = {t: schema[t] for t in self._allowed if t in schema}
        valid = []
        for rel in self._configured_relations:
            if rel.parent in self._schema and rel.child in self._schema:
                if any(c.name == rel.fk for c in self._schema[rel.child]):
                    valid.append(rel)
        self._relations = tuple(valid)

    def tables(self) -> list[str]:
        return list(self._schema)

    def relations(self) -> tuple[Relation, ...]:
        return self._relations

    def columns(self, table: str) -> tuple[Column, ...]:
        cols = self._schema.get(table)
        if cols is None:
            raise UserError("Таблица недоступна.")
        return cols

    def describe(self, table: str) -> str:
        return ", ".join(f"{c.name} [{c.data_type}]" for c in self.columns(table))

    def column(self, table: str, name: str, writable: bool = False) -> Column:
        key = name.strip().lower()
        for col in self.columns(table):
            if col.name == key:
                if writable and col.identity:
                    raise UserError(f"Колонку «{col.name}» изменять нельзя.")
                return col
        raise UserError(f"В таблице «{table}» нет колонки «{name.strip()[:50]}».")

    def _pk(self, table: str) -> Column:
        pk = self._pk_optional(table)
        if pk is None:
            raise UserError("В таблице нет идентификатора для адресации записей.")
        return pk

    def _pk_optional(self, table: str) -> Column | None:
        for col in self.columns(table):
            if col.identity:
                return col
        return None

    @staticmethod
    def _prepare(col: Column, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if "\x00" in value:
            raise UserError("Значение содержит недопустимый символ.")
        if len(value) > MAX_VALUE_LEN:
            raise UserError("Значение слишком длинное.")
        if value == "":
            if col.nullable:
                return None
            raise UserError(f"Колонка «{col.name}» не может быть пустой.")
        return value

    def _fetch(
        self, query: sql.Composable, params: list[Any]
    ) -> tuple[list[str], list[tuple]]:
        console.audit(f"SQL: {query.as_string()} | params={params!r}")
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(query, params)
                names = [d.name for d in cur.description]
                rows = cur.fetchall()
        return names, rows

    def _modify(self, query: sql.Composable, params: list[Any]) -> int:
        console.audit(f"SQL: {query.as_string()} | params={params!r}")
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(query, params)
                return cur.rowcount

    def select(self, table: str, filters: Pairs = ()) -> tuple[list[str], list[tuple]]:
        self.columns(table)
        query: sql.Composable = sql.SQL("SELECT * FROM {t}").format(
            t=sql.Identifier(table)
        )
        conditions = []
        params: list[Any] = []
        for name, value in filters:
            col = self.column(table, name)
            if value == "":
                conditions.append(
                    sql.SQL("{c} IS NULL").format(c=sql.Identifier(col.name))
                )
            else:
                conditions.append(
                    sql.SQL("{c} = %s").format(c=sql.Identifier(col.name))
                )
                params.append(self._prepare(col, value))
        if conditions:
            query = query + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        query = query + sql.SQL(" ORDER BY 1 LIMIT %s")
        params.append(self._limit)
        return self._fetch(query, params)

    def _assignments(
        self, table: str, changes: Pairs
    ) -> tuple[sql.Composable, list[Any]]:
        if not changes:
            raise UserError("Не указано ни одной колонки для изменения.")
        parts = []
        params: list[Any] = []
        seen: set[str] = set()
        for name, value in changes:
            col = self.column(table, name, writable=True)
            if col.name in seen:
                raise UserError(f"Колонка «{col.name}» указана дважды.")
            seen.add(col.name)
            parts.append(sql.SQL("{c} = %s").format(c=sql.Identifier(col.name)))
            params.append(self._prepare(col, value))
        return sql.SQL(", ").join(parts), params

    def update_one(self, table: str, record_id: str, changes: Pairs) -> int:
        pk = self._pk(table)
        if not record_id:
            raise UserError("Не указан id записи.")
        assignments, params = self._assignments(table, changes)
        params.append(self._prepare(pk, record_id))
        query = sql.SQL("UPDATE {t} SET {s} WHERE {k} = %s").format(
            t=sql.Identifier(table), s=assignments, k=sql.Identifier(pk.name)
        )
        return self._modify(query, params)

    def update_many(
        self,
        table: str,
        set_column: str,
        new_value: str,
        where_column: str,
        values: Sequence[str],
    ) -> int:
        target = self.column(table, set_column, writable=True)
        cond = self.column(table, where_column)
        if not values:
            raise UserError("Не указано ни одного значения для отбора.")
        if len(values) > MAX_IN_VALUES:
            raise UserError(
                f"Слишком много значений для отбора (максимум {MAX_IN_VALUES})."
            )
        params: list[Any] = [self._prepare(target, new_value)]
        for value in values:
            if value == "":
                raise UserError("Пустые значения в списке отбора недопустимы.")
            params.append(self._prepare(cond, value))
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in values)
        query = sql.SQL("UPDATE {t} SET {c} = %s WHERE {w} IN ({p})").format(
            t=sql.Identifier(table),
            c=sql.Identifier(target.name),
            w=sql.Identifier(cond.name),
            p=placeholders,
        )
        return self._modify(query, params)

    def _insert(self, cur: Any, table: str, pairs: Pairs) -> Any:
        columns = self.columns(table)
        names = []
        params: list[Any] = []
        seen: set[str] = set()
        for name, value in pairs:
            col = self.column(table, name, writable=True)
            if col.name in seen:
                raise UserError(f"Колонка «{col.name}» указана дважды.")
            seen.add(col.name)
            names.append(sql.Identifier(col.name))
            params.append(self._prepare(col, value))
        for col in columns:
            if (
                not col.identity
                and not col.nullable
                and not col.has_default
                and col.name not in seen
            ):
                raise UserError(f"Не указано обязательное поле «{col.name}».")
        if names:
            query: sql.Composable = sql.SQL(
                "INSERT INTO {t} ({c}) VALUES ({p})"
            ).format(
                t=sql.Identifier(table),
                c=sql.SQL(", ").join(names),
                p=sql.SQL(", ").join(sql.Placeholder() for _ in names),
            )
        else:
            query = sql.SQL("INSERT INTO {t} DEFAULT VALUES").format(
                t=sql.Identifier(table)
            )
        pk = self._pk_optional(table)
        if pk is not None:
            query = query + sql.SQL(" RETURNING {k}").format(k=sql.Identifier(pk.name))
        console.audit(f"SQL: {query.as_string()} | params={params!r}")
        cur.execute(query, params)
        return cur.fetchone()[0] if pk is not None else None

    def insert_one(self, table: str, pairs: Pairs) -> Any:
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                return self._insert(cur, table, pairs)

    def insert_many(self, table: str, rows: Sequence[Pairs]) -> list[Any]:
        if not rows:
            raise UserError("Не указано ни одной строки.")
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                return [self._insert(cur, table, pairs) for pairs in rows]

    def insert_linked_many(
        self,
        relation: Relation,
        groups: Sequence[tuple[Pairs, Sequence[Pairs]]],
    ) -> list[tuple[Any, list[Any]]]:
        if relation not in self._relations:
            raise UserError("Такая связь таблиц не настроена.")
        if not groups:
            raise UserError("Не указано ни одной записи.")
        results = []
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                for parent_pairs, children in groups:
                    if not children:
                        raise UserError(
                            "У каждой записи должна быть хотя бы одна связанная строка."
                        )
                    parent_id = self._insert(cur, relation.parent, parent_pairs)
                    child_ids = []
                    for child_pairs in children:
                        pairs = [p for p in child_pairs if p[0] != relation.fk]
                        pairs.append((relation.fk, parent_id))
                        child_ids.append(self._insert(cur, relation.child, pairs))
                    results.append((parent_id, child_ids))
        return results
