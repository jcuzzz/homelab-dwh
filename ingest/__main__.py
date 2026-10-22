import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ingest.db import connect, init_schema
from ingest.load import load_path


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create the bronze schema (safe to repeat)")
    load = sub.add_parser("load", help="append a CSV export to its bronze tables")
    load.add_argument("--source", required=True, help="source system prefix, e.g. cases")
    load.add_argument("--encoding", default="utf-8-sig", help="e.g. cp1252 for older exports")
    load.add_argument("target", type=Path, help="the CSV file or a folder of CSV files")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "load" and not args.target.exists():
        sys.exit(f"{args.target} does not exist")
    load_dotenv()
    with connect(_require_env("DATABASE_URL")) as conn:
        if args.command == "init-db":
            init_schema(conn)
            print("bronze schema ready")
            return 0
        archive_dir = Path(_require_env("ARCHIVE_DIR"))
        results = load_path(conn, args.target, args.source, archive_dir, args.encoding)
    if not results:
        print(f"no CSV files found at {args.target}")
        return 1
    for r in results:
        if r.status == "loaded":
            print(f"loaded   {r.file.name} -> bronze.{r.table} ({r.rows} rows, load {r.load_id})")
        elif r.status == "skipped":
            print(f"skipped   {r.file.name}: unchanged since load {r.load_id}")
        else:
            print(f"FAILED   {r.file.name}: {r.error}")
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
