#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run python tools/check_no_real_data.py
uv run pytest
echo "all checks passed"
