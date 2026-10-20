import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from ingest.db import Connection

BRONZE = "bronze"
MAX_IDENTIFIER = 63
_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")


class LoadError(Exception):
    """A problem with one file. Messages name lines and columns, never row values."""


def open_csv(path: Path, encoding: str = "utf-8-sig") -> TextIO:
    return path.open(newline="", encoding=encoding)


def read_csv(f: TextIO) -> tuple[list[str], Iterator[list[str]]]:
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
    conn.execute(sql.SQL("create table {} ({})").format(sql.Identifier(BRONZE, table), column_defs))


def copy_rows(conn: Connection, table: str, columns: list[str], rows: Iterator[list[str]]) -> int:
    stmp = sql.SQL("copy {} ({}) from stdin").format(
        sql.Identifier(BRONZE, table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    )
    count = 0
    with conn.cursor() as cur, cur.copy(stmt) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load_file(conn: Connection, path: Path, source: str) -> int:
    if normalise_identifier(source) != source:
        raise LoadError(f"source {source!r} must be lowercase letters, digits and underscores")
    table = table_name(source, path)
    with open_csv(path) as f:
        header, rows = read_csv(f)
        columns = normalise_columns(header)
        return copy_rows(conn, table, columns, rows)
