import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ingest.db import connect, init_schema
from ingest.load import load_file


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the bronze schema (safe to repeat)")
    load = sub.add_parser("load", help="append a CSV export to its bronze table")
    load.add_argument("--source", required=True, help="source system prefix, e.g. cases")
    load.add_argument("target", type=Path, help="the CSV file to load")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_dotenv()
    with connect(_require_env("DATABASE_URL")) as conn:
        if args.command == "init-db":
            init_schema(conn)
            print("bronze schema ready")
            return
        r = load_file(conn, args.target, args.source)
        print(f"loaded {r.file.name} -> bronze.{r.table} ({r.rows} rows, load {r.load_id})")


if __name__ == "__main__":
    main()
