from pathlib import Path

import pytest

from ingest.load import LoadError, normalise_columns, normalise_identifier, table_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Student Key", "student_key"),
        ("  SURNAME ", "surname"),
        ("Year-Level (2026)", "year_level_2026"),
        ("1st Name", "_1st_name"),
    ],
)
def test_normalise_identifier(raw: str, expected: str) -> None:
    assert normalise_identifier(raw) == expected


def test_blank_name_is_rejected() -> None:
    with pytest.raises(LoadError, match="cannot make a name"):
        normalise_identifier(" - ")


def test_long_name_is_rejected() -> None:
    with pytest.raises(LoadError, match="longer than 63"):
        normalise_identifier("x" * 64)


def test_table_name_keeps_double_underscore() -> None:
    assert table_name("cases", Path("/share/Student Contacts.csv")) == "cases__student_contacts"


def test_colliding_headers_are_rejected() -> None:
    with pytest.raises(LoadError, match="'Year Level' and 'year_level'"):
        normalise_columns(["Year Level", "year_level"])
