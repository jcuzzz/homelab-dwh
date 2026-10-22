import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from ingest.db import Connection, init_schema
from ingest.load import LoadError, _safe_db_error, load_file, load_path

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

    result = load_file(conn, src, "cases", tmp_path / "archive")

    assert (result.table, result.rows) == ("cases__student", 2)
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


def test_identical_file_is_skipped(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)
    first = load_file(conn, src, "cases", tmp_path / "archive")

    second = load_file(conn, src, "cases", tmp_path / "archive")

    assert (second.status, second.load_id) == ("skipped", first.load_id)
    assert scalar(conn, "select count(*) from bronze.cases__student") == 2


def test_changed_file_appends_new_load(conn: Connection, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    src = write(tmp_path / "Student.csv", STUDENTS)
    load_file(conn, src, "cases", archive)
    write(src, STUDENTS + "S003,Cove,09\n")

    load_file(conn, src, "cases", archive)

    assert scalar(conn, "select count(*) from bronze.cases__student") == 5
    assert len(list((archive / "cases").glob("*.csv"))) == 2


def test_reverted_file_is_loaded_again(conn: Connection, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    src = write(tmp_path / "Student.csv", STUDENTS)
    load_file(conn, src, "cases", archive)
    write(src, STUDENTS + "S003,Cove,09\n")
    load_file(conn, src, "cases", archive)
    write(src, STUDENTS)

    result = load_file(conn, src, "cases", archive)

    assert result.status == "loaded"
    assert len(list((archive / "cases").glob("*.csv"))) == 2


def test_bad_source_name_is_rejected(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)

    with pytest.raises(LoadError, match="source"):
        load_file(conn, src, "Cases!", tmp_path / "archive")


def test_rows_record_load_id_source_line(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS)

    result = load_file(conn, src, "cases", tmp_path / "archive")

    lineage = conn.execute(
        b"select _load_id, _source_line from bronze.cases__student order by 2"
    ).fetchall()
    assert lineage == [(result.load_id, 2), (result.load_id, 3)]
    assert scalar(conn, "select row_count from bronze.load_log") == 2


def test_export_time_is_file_modified_time(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Students.csv", STUDENTS)
    exported = datetime(2026, 3, 1, 6, 30, tzinfo=UTC)
    os.utime(src, (exported.timestamp(), exported.timestamp()))

    load_file(conn, src, "cases", tmp_path / "archive")

    assert scalar(conn, "select source_modified_at from bronze.load_log") == exported


def test_load_id_is_indexed(conn: Connection, tmp_path: Path) -> None:
    load_file(conn, write(tmp_path / "Student.csv", STUDENTS), "cases", tmp_path / "archive")

    indexdef = scalar(conn, "select indexdef from pg_indexes where tablename = 'cases__student'")

    assert "(_load_id)" in str(indexdef)


def test_setup_sql_can_run_twice(conn: Connection) -> None:
    init_schema(conn)

    assert scalar(conn, "select count(*) from bronze.load_log") == 0


def test_ragged_row_rolls_back_whole_file(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Student.csv", STUDENTS + "S003,Cove\n")

    with pytest.raises(LoadError, match="line 4: expected 3 fields, found 2"):
        load_file(conn, src, "cases", tmp_path / "archive")

    assert scalar(conn, "select count(*) from bronze.load_log") == 0
    assert scalar(conn, "select to_regclass('bronze.cases__student') is null") is True


def test_blank_lines_are_ignored(conn: Connection, tmp_path: Path) -> None:
    src = write(tmp_path / "Students.csv", STUDENTS + "\n")

    assert load_file(conn, src, "cases", tmp_path / "archive").rows == 2


def test_folder_load_continues_past_a_bad_file(conn: Connection, tmp_path: Path) -> None:
    share = tmp_path / "share"
    write(share / "Bad.csv", "A,B\n1\n")
    write(share / "Student.csv", STUDENTS)
    write(share / "notes.txt", "ignored")

    results = load_path(conn, share, "cases", tmp_path / "archive")

    assert [(r.file.name, r.status) for r in results] == [
        ("Bad.csv", "failed"),
        ("Student.csv", "loaded"),
    ]


def test_header_change_fails_without_loading(conn: Connection, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    src = write(tmp_path / "Student.csv", STUDENTS)
    load_file(conn, src, "cases", archive)
    write(src, "Surname,Student Key,Home Group\nS005,Eden,10\n")

    with pytest.raises(LoadError, match=r"added \['home_group'\], removed \['year_level'\]"):
        load_file(conn, src, "cases", archive)

    assert scalar(conn, "select count(*) from bronze.load_log") == 1


def test_recorded_columns_still_load(conn: Connection, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    src = write(tmp_path / "Student.csv", STUDENTS)
    load_file(conn, src, "cases", archive)
    write(src, "Surname,Student Key,Year Level\nDell,S004,10\n")

    load_file(conn, src, "cases", archive)

    surname = scalar(conn, "select surname from bronze.cases__student where student_key = 'S004'")
    assert surname == "Dell"


def test_wrong_encoding_is_reported(conn: Connection, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    src = tmp_path / "Student.csv"
    src.write_bytes("Student Key,Surname\nS007,Grégoire\n".encode("cp1252"))

    with pytest.raises(LoadError, match="cp1252"):
        load_file(conn, src, "cases", archive)

    assert load_file(conn, src, "cases", archive, encoding="cp1252").status == "loaded"


def test_safe_db_error_hides_values_the_server_quotes(conn: Connection) -> None:
    secret = "Zanzibar-Quokka"
    with pytest.raises(psycopg.Error) as caught:
        conn.execute("select %s::integer", (secret,))

    assert secret in str(caught.value)
    assert secret not in _safe_db_error(caught.value)


def test_failed_load_does_not_echo_row_values(conn: Connection, tmp_path: Path) -> None:
    secret = "Zanzibar-Quokka"
    write(tmp_path / "share" / "Students.csv", f"Student Key,Surname\nS008,{secret},x00\n")

    [result] = load_path(conn, tmp_path / "share", "cases", tmp_path / "archive")

    assert result.status == "failed"
    assert result.error is not None
    assert secret not in result.error
