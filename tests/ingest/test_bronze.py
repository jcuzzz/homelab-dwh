from pathlib import Path

import pytest

from ingest.db import Connection
from ingest.load import LoadError, load_file

STUDENTS = "Student Key,Surname,Year Level\nS001,Avery,07\nS002,Brook,\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def scalar(conn: Connection, query: str) -> object:
    row = conn.execute(query.encode()).fetchone()
    assert row is not None
    return row[0]


def test_load_mirrors_csv_as_text(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)

    rows = load_file(conn, src, "cases")

    assert rows == 2
    stored = conn.execute(
        b"select student_key, surname, year_level from bronze.cases__student order by 1"
    ).fetchall()
    assert stored == [("S001", "Avery", "07"), ("S002", "Brook", "")]
    types = conn.execute(
        b"select distinct data_type from information_schema.columns"
        b" where table_schema = 'bronze' and table_name = 'cases__student'"
        b" and column_name not like '\\_%'"
    ).fetchall()
    assert types == [("text",)]


def test_second_load_appends(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)

    load_file(conn, src, "cases")
    load_file(conn, src, "cases")

    assert scalar(conn, "select count(*) from bronze.cases__student") == 4


def test_bad_source_name_is_rejected(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)

    with pytest.raises(LoadError, match="source"):
        load_file(conn, src, "Cases!")
