import csv
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO


def open_csv(path: Path, encoding: str = "utf-8-sig") -> TextIO:
    return path.open(newline="", encoding=encoding)


def read_csv(f: TextIO) -> tuple[list[str], Iterator[list[str]]]:
    reader = csv.reader(f)
    header = next(reader, None)
    if header is None:
        raise ValueError("file is empty")
    return header, reader
