import os
from collections.abc import Iterator

import psycopg
import pytest
from dotenv import load_dotenv

from ingest.db import Connection, init_schema

load_dotenv()


@pytest.fixture
def conn() -> Iterator[Connection]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True) as c:
        if not c.info.dbname.endswith("_test"):
            pytest.fail(f"refusing to rest non-test database {c.info.dbname!r}")
        c.execute("drop schema if exists bronze cascade")
        init_schema(c)
        yield c
