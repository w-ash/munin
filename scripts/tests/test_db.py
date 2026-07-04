"""Tests for the db module (disposable DuckDB cache over canonical JSONL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vault_scripts import db
from vault_scripts._cli import CliError


def _write_fixture_jsonl(root: Path) -> Path:
    data_dir = root / "Health" / "data" / "canonical"
    data_dir.mkdir(parents=True)
    rows = [
        {
            "id": "act_strava_1",
            "date": "2026-06-30",
            "type": "run",
            "distance_m": 8210.0,
            "duration_s": 2712,
        },
        {
            "id": "act_strava_2",
            "date": "2026-07-01",
            "type": "ride",
            "distance_m": 20000.0,
            "duration_s": 3600,
        },
    ]
    path = data_dir / "activities-2026.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return path


@pytest.fixture
def vault_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_fixture_jsonl(tmp_path)
    cfg = tmp_path / "datasets.json"
    cfg.write_text(
        json.dumps(
            {"datasets": {"activities": "Health/data/canonical/activities-*.jsonl"}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_DATASETS_JSON", str(cfg))
    monkeypatch.setenv("VAULT_DB_PATH", str(tmp_path / "cache" / "test.duckdb"))
    monkeypatch.setattr(db, "VAULT", tmp_path)
    return tmp_path


def _run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["db", *argv])
    db.main()
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    return out


def test_rebuild_dry_run_creates_nothing(vault_env, capsys, monkeypatch):
    out = _run(["rebuild"], capsys, monkeypatch)
    assert out["ok"] is True
    result = out["result"]
    assert result["dryRun"] is True
    assert result["datasets"][0]["files"] == 1
    assert not (vault_env / "cache" / "test.duckdb").exists()


def test_rebuild_query_round_trip_and_idempotent(vault_env, capsys, monkeypatch):
    first = _run(["rebuild", "--write"], capsys, monkeypatch)
    assert first["result"]["datasets"][0]["rows"] == 2

    out = _run(
        ["query", "SELECT count(*) AS n FROM activities"], capsys, monkeypatch
    )
    assert out["result"]["rows"] == [{"n": 2}]
    assert out["result"]["truncated"] is False

    second = _run(["rebuild", "--write"], capsys, monkeypatch)
    assert second["result"]["datasets"][0]["rows"] == 2

    by_type = _run(
        ["query", "SELECT type FROM activities ORDER BY date"], capsys, monkeypatch
    )
    assert [r["type"] for r in by_type["result"]["rows"]] == ["run", "ride"]


def test_query_limit_truncates(vault_env, capsys, monkeypatch):
    _run(["rebuild", "--write"], capsys, monkeypatch)
    out = _run(
        ["query", "SELECT * FROM activities", "--limit", "1"], capsys, monkeypatch
    )
    assert out["result"]["rowCount"] == 1
    assert out["result"]["truncated"] is True


def test_query_without_cache_is_validation_error(vault_env, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["db", "query", "SELECT 1"])
    with pytest.raises(SystemExit) as exc:
        db.main()
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_bad_dataset_name_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "datasets.json"
    cfg.write_text(json.dumps({"datasets": {"bad-name": "x/*.jsonl"}}))
    monkeypatch.setenv("VAULT_DATASETS_JSON", str(cfg))
    with pytest.raises(CliError):
        db._load_datasets()


def test_json_safe_passthrough_and_stringify():
    assert db._json_safe(3) == 3
    assert db._json_safe("x") == "x"
    assert db._json_safe(None) is None
    assert db._json_safe(Path("relative/x")) == "relative/x"
