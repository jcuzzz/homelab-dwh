import os
import sys

from dotenv import load_dotenv

from ingest.db import connect


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    else:
        return value


def main() -> None:
    load_dotenv()
    url = _require_env("DATABASE_URL")
    with connect(url) as conn:
        row = conn.execute("select version()").fetchone()
        if row is None:
            sys.exit("query returned no results from target")
        print(row[0])


if __name__ == "__main__":
    main()
