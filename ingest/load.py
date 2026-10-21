import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TextIO

from psycopg import sql

from ingest.db import Connection

BRONZE = "bronze"
META_COLUMNS = ("_load_id", "_source_line")
MAX_IDENTIFIER = 63
_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


class LoadError(Exception):
    """A problem with one file. Messages name lines and columns, never row values."""


class CsvReader(Protocol):
    line_num: int

    def __iter__(self) -> Iterator[list[str]]: ...

    def __next__(self) -> list[str]: ...


@dataclass(frozen=True)
class LoadResult:
    file: Path
    table: str
    load_id: int
    rows: int


def open_csv(path: Path, encoding: str = "utf-8-sig") -> TextIO:
    return path.open(newline="", encoding=encoding)


def read_csv(f: TextIO) -> tuple[list[str], CsvReader]:
    reader = csv.reader(f)
    header = next(reader, None)
    if header is None:
        raise LoadError("file is empty")
    return header, reader


def normalise_identifier(name: str) -> str:
    ident = _NON_IDENTIFIER.sub("_", name.strip().lower()).strip("_")
    if not ident:
        raise LoadError(f"cannot make a name from {name!r}")
    if ident[0].isdigit():
        ident = f"_{ident}"
    if len(ident) > MAX_IDENTIFIER:
        raise LoadError(f"name {ident!r} is longer than {MAX_IDENTIFIER} characters")
    return ident


def table_name(source: str, path: Path) -> str:
    name = f"{source}__{normalise_identifier(path.stem)}"
    if len(name) > MAX_IDENTIFIER:
        raise LoadError(f"table name {name!r} is longer than {MAX_IDENTIFIER} characters")
    return name


def normalise_columns(header: list[str]) -> list[str]:
    columns = [normalise_identifier(h) for h in header]
    seen: dict[str, str] = {}
    for original, column in zip(header, columns, strict=True):
        if column in seen:
            raise LoadError(f"headers {seen[column]!r} and {original!r} both become {column!r}")
        seen[column] = original
    return columns


def _existing_columns(conn: Connection, table: str) -> list[str]:
    rows = conn.execute(
        "select column_name from information_schema.columns"
        " where table_schema = %s and table_name = %s order by ordinal_position",
        (BRONZE, table),
    ).fetchall()
    return [str(r[0]) for r in rows]


def ensure_table(conn: Connection, table: str, columns: list[str]) -> None:
    if _existing_columns(conn, table):
        return
    column_defs = sql.SQL(", ").join(
        sql.SQL("{} text not null").format(sql.Identifier(c)) for c in columns
    )
    target = sql.Identifier(BRONZE, table)
    conn.execute(
        sql.SQL(
            "create table {} ("
            " _load_id bigint not null references bronze.load_log (load_id),"
            " _source_line integer not null, {})"
        ).format(target, column_defs)
    )
    conn.execute(sql.SQL("create index on {} (_load_id)").format(target))


def copy_rows(
    conn: Connection, table: str, columns: list[str], reader: CsvReader, load_id: int
) -> int:
    stmt = sql.SQL("copy {} ({}) from stdin").format(
        sql.Identifier(BRONZE, table),
        sql.SQL(", ").join(sql.Identifier(c) for c in (*META_COLUMNS, *columns)),
    )
    count = 0
    with conn.cursor() as cur, cur.copy(stmt) as copy:
        for row in reader:
            copy.write_row([load_id, reader.line_num, *row])
            count += 1
    return count


def load_file(conn: Connection, path: Path, source: str) -> LoadResult:
    if normalise_identifier(source) != source:
        raise LoadError(f"source {source!r} must be lowercase letters, digits and underscores")
    table = table_name(source, path)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    with open_csv(path) as f:
        header, reader = read_csv(f)
        columns = normalise_columns(header)
        ensure_table(conn, table, columns)
        inserted = conn.execute(
            "insert into bronze.load_log (source, table_name, source_file, source_modified_at)"
            " values (%s, %s, %s, %s) returning load_id",
            (source, table, str(path), modified_at),
        ).fetchone()
        if inserted is None:
            raise LoadError("load log insert returned no id")
        load_id = int(str(inserted[0]))
        rows = copy_rows(conn, table, columns, reader, load_id)
        conn.execute(
            "update bronze.load_log set row_count = %s where load_id = %s", (rows, load_id)
        )
    return LoadResult(path, table, load_id, rows)
