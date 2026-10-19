import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

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
