import subprocess
import sys
from pathlib import PurePosixPath

BLOCKED_EXTENSIONS = (".csv", ".xlsx", ".xls", ".dump", ".pgdump", ".sql.gz")
BLOCKED_FOLDERS = {"private", "data"}


def _is_violation(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if name.endswith(BLOCKED_EXTENSIONS):
        return True
    if name.startswith(".env") and name != ".env.example":
        return True
    return any(part in BLOCKED_FOLDERS for part in parts[-1])


def find_violations(paths: list[str]) -> list[str]:
    return [path for path in paths if _is_violation(path)]


def main() -> None:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    violations = find_violations(result.stdout.splitlines())
    if violations:
        for path in violations:
            print(f"must not be tracked: {path}")
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
