from tools.check_no_real_data import find_violations


def test_catches_real_data() -> None:
    paths = [
        "students.csv",
        "exports/report.xlsx",
        "old.xls",
        "backup.dump",
        "backup.pgdump",
        "backup.sql.gz",
        ".env",
        ".env.local",
        "config/.env",
        "private/notes.txt",
        "data/anything.txt",
    ]
    assert find_violations(paths) == paths


def test_allows_safe_files() -> None:
    paths = [".env.example", "ingest/load.py", "README.md", "tools/check.sh"]
    assert find_violations(paths) == []
