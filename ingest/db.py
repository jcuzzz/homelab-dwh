import psycopg


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)
