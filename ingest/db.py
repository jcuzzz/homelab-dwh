from pathlib import Path

import psycopg

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "sql" / "bronze_schema.sql"

Connection = psycopg.Connection[tuple[object, ...]]


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)


def init_schema(conn: Connection) -> None:
    conn.execute(SCHEMA_SQL.read_bytes())
