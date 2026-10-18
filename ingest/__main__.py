import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ingest.db import connect
from ingest.load import open_csv, read_csv


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    else:
        return value


def _summarise_csv(path: Path) -> None:
    with open_csv(path) as f:
        header, rows = read_csv(f)
        count = sum(1 for _ in rows)
    print(f"{len(header)} columns: {header}")
    print(f"{count} rows")


def main() -> None:
    if len(sys.argv) > 1:
        _summarise_csv(Path(sys.argv[1]))
        return
    load_dotenv()
    url = _require_env("DATABASE_URL")
    with connect(url) as conn:
        row = conn.execute("select version()").fetchone()
        if row is None:
            sys.exit("query returned no results from target")
        print(row[0])


if __name__ == "__main__":
    main()
