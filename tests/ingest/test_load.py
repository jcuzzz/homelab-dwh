from pathlib import Path

import pytest

from ingest.load import open_csv, read_csv


def test_reads_header_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_text("Student Key,Surname\nS0001,Avery\nS0002,Brook\n", encoding="utf-8")

    with open_csv(path) as f:
        header, rows = read_csv(f)
        all_rows = list(rows)

    assert header == ["Student Key", "Surname"]
    assert all_rows == [["S0001", "Avery"], ["S0002", "Brook"]]


def test_quoted_comma(tmp_path: Path) -> None:
    path = tmp_path / "families.csv"
    path.write_text('Family Key,Address\nF001,"Unit 4, 1 Example Street"\n', encoding="utf-8")

    with open_csv(path) as f:
        _, rows = read_csv(f)
        all_rows = list(rows)

    assert all_rows == [["F001", "Unit 4, 1 Example Street"]]


def test_no_byte_order(tmp_path: Path) -> None:
    path = tmp_path / "students.csv"
    path.write_bytes(b"\xef\xbb\xbfStudent Key,Surname\nS0001,Avery\n")

    with open_csv(path) as f:
        header, _ = read_csv(f)

    assert header[0] == "Student Key"


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with open_csv(path) as f, pytest.raises(ValueError, match="empty"):
        read_csv(f)
