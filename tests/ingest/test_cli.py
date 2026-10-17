import pytest

from ingest.__main__ import _require_env


def test_missing_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        _require_env("DATABASE_URL")
