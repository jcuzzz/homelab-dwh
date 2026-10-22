import csv
import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TextIO

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
    status: Literal["loaded", "skipped", "failed"]
    load_id: int | None = None
    rows: int = 0
    error: str | None = None


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
    width = len(columns)
    count = 0
    with conn.cursor() as cur, cur.copy(stmt) as copy:
        for row in reader:
            if not row:
                continue
            if len(row) != width:
                raise LoadError(
                    f"line {reader.line_num}: expected {width} fields, found {len(row)}"
                )
            copy.write_row([load_id, reader.line_num, *row])
            count += 1
    return count


def _latest_load(conn: Connection, table: str) -> tuple[int, str] | None:
    row = conn.execute(
        "select load_id, file_sha256 from bronze.load_log"
        " where table_name = %s order by load_id desc limit 1",
        (table,),
    ).fetchone()
    return None if row is None else (int(str(row[0])), str(row[1]))


def load_file(conn: Connection, path: Path, source: str, archive_dir: Path) -> LoadResult:
    if normalise_identifier(source) != source:
        raise LoadError(f"source {source!r} must be lowercase letters, digits and underscores")
    table = table_name(source, path)
    modified_before = path.stat().st_mtime
    archived, sha = archive_file(path, archive_dir, source)
    if path.stat().st_mtime != modified_before:
        raise LoadError("file changed while being copiedl run the load again")
    modified_at = datetime.fromtimestamp(modified_before, tz=UTC)
    with open_csv(path) as f:
        header, reader = read_csv(f)
        columns = normalise_columns(header)
        with conn.transaction():
            latest = _latest_load(conn, table)
            if latest is not None and latest[1] == sha:
                return LoadResult(path, table, "skipped", load_id=latest[0])
            ensure_table(conn, table, columns)
            inserted = conn.execute(
                "insert into bronze.load_log (source, table_name, source_file,"
                " source_modified_at, archive_file, file_sha256)"
                " values (%s, %s, %s, %s, %s, %s) returning load_id",
                (source, table, str(path), modified_at, str(archived), sha),
            ).fetchone()
            if inserted is None:
                raise LoadError("load log insert returned no id")
            load_id = int(str(inserted[0]))
            rows = copy_rows(conn, table, columns, reader, load_id)
            conn.execute(
                "update bronze.load_log set row_count = %s where load_id = %s", (rows, load_id)
            )
    return LoadResult(path, table, "loaded", load_id=load_id, rows=rows)


def csv_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.iterdir() if p.is_file() and p.suffix.lower() == ".csv")


def load_path(conn: Connection, target: Path, source: str, archive_dir: Path) -> list[LoadResult]:
    results: list[LoadResult] = []
    for path in csv_files(target):
        try:
            results.append(load_file(conn, path, source, archive_dir))
        except (LoadError, OSError) as exc:
            results.append(LoadResult(path, "", "failed", error=str(exc)))
    return results


def archive_file(src: Path, archive_dir: Path, source: str) -> tuple[Path, str]:
    dest_dir = archive_dir / source
    dest_dir.mkdir(parents=True, exist_ok=True)
    partial = dest_dir / f".{src.name}.partial"
    digest = hashlib.sha256()
    with src.open("rb") as fin, partial.open("wb") as fout:
        while chunk := fin.read(1 << 20):
            digest.update(chunk)
            fout.write(chunk)
    sha = digest.hexdigest()
    final = dest_dir / f"{sha}{src.suffix.lower()}"
    if final.exists():
        partial.unlink()
    else:
        partial.replace(final)
