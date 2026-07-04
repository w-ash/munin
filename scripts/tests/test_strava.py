"""Tests for the strava module (Eir slice 1: fetch, canonical, projection)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from vault_scripts import strava
from vault_scripts._types import CanonicalActivityRow, CanonicalSource, StravaActivity

_YESTERDAY = (datetime.now(UTC).astimezone().date() - timedelta(days=1)).isoformat()
_OLD_DAY = "2019-03-04"


def _raw_activity(act_id: int, date_local: str, sport: str = "Run") -> dict[str, object]:
    return {
        "id": act_id,
        "name": "Morning Run",
        "sport_type": sport,
        "start_date": f"{date_local}T14:12:00Z",
        "start_date_local": f"{date_local}T07:12:00Z",
        "moving_time": 2712,
        "distance": 8210.0,
        "total_elevation_gain": 55.0,
        "average_heartrate": 152.3,
        "max_heartrate": 171.0,
        "extra_field_from_api": "kept in raw layer",
    }


def _row(**overrides: object) -> CanonicalActivityRow:
    base = strava.map_activity(
        StravaActivity.model_validate(_raw_activity(1, _YESTERDAY))
    )
    return base.model_copy(update=dict(overrides))


def test_map_activity():
    row = _row()
    assert row.id == "act_strava_1"
    assert row.date == _YESTERDAY
    assert row.type == "run"
    assert row.duration_s == 2712
    assert row.distance_m == pytest.approx(8210.0)
    assert row.sources == [CanonicalSource(name="strava", source_id="1")]


def test_snake_fallback_for_unknown_sport():
    assert strava._snake("StandUpPaddling") == "stand_up_paddling"
    assert strava._snake("WeightTraining") == "strength"


def test_format_helpers():
    assert strava.format_duration(2712) == "45:12"
    assert strava.format_duration(3753) == "1:02:33"
    assert strava.format_pace(330.3) == "5:30"


def test_activity_line_run_and_strength():
    run = _row()
    assert strava.activity_line(run) == "Ran 8.2 km in 45:12 (5:30/km), avg HR 152"
    lift = _row(type="strength", distance_m=0.0, duration_s=1800, avg_hr=None)
    assert strava.activity_line(lift) == "Strength: 30:00"


def test_upsert_block_inserts_below_divider_and_is_idempotent():
    note = strava.build_daily_note(_YESTERDAY, "2026-07-03")
    block = strava.render_block([_row()])
    once = strava.upsert_block(note, block)
    assert once.count(strava.EIR_START) == 1
    # Prose zones untouched: everything above the divider is identical.
    assert once.split("\n---\n")[0] == note.split("\n---\n")[0]
    assert once.index("## What I want") < once.index(strava.EIR_START)

    twice = strava.upsert_block(once, block)
    assert twice == once

    updated = strava.upsert_block(once, strava.render_block([_row(), _row(type="walk")]))
    assert updated.count(strava.EIR_START) == 1
    assert "Walk:" in updated


def test_apply_daily_props_bare_numbers():
    note = strava.build_daily_note(_YESTERDAY, "2026-07-03")
    out = strava.apply_daily_props(note, [_row()])
    assert "ran_km: 8.2\n" in out
    assert "activity_min: 45\n" in out
    again = strava.apply_daily_props(out, [_row()])
    assert again == out


def test_build_daily_note_shape():
    note = strava.build_daily_note("2026-07-01", "2026-07-03")
    assert note.startswith('---\ncreated: "2026-07-03"\ndate: "2026-07-01"\n')
    assert "# Wednesday, July 1, 2026" in note
    assert "## Links & Connections" in note


@pytest.fixture
def sync_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(strava, "VAULT", tmp_path)
    monkeypatch.setattr(strava, "_access_token", lambda: "fake-token")
    fetched = [_raw_activity(101, _YESTERDAY), _raw_activity(102, _OLD_DAY, "Ride")]
    monkeypatch.setattr(strava, "_fetch_all", lambda _token, _after: fetched)
    return tmp_path


def _run_sync(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["strava", *argv])
    strava.main()
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    return out


def test_sync_dry_run_writes_nothing(sync_env, capsys, monkeypatch):
    out = _run_sync(["sync"], capsys, monkeypatch)
    assert out["result"]["dryRun"] is True
    assert out["result"]["newActivities"] == 2
    assert not (sync_env / "Health").exists()
    assert not (sync_env / "Daily").exists()


def test_sync_write_then_rerun_is_noop(sync_env, capsys, monkeypatch):
    first = _run_sync(["sync", "--write"], capsys, monkeypatch)
    assert first["result"]["rawFilesWritten"] == 2
    assert first["result"]["canonicalAppended"] == {"2019": 1, _YESTERDAY[:4]: 1}
    assert first["result"]["dailyNotesWritten"] == [_YESTERDAY]

    raw = sync_env / "Health" / "data" / "raw" / "strava"
    assert (raw / _YESTERDAY[:4] / f"{_YESTERDAY}_101.json").exists()
    raw_payload = json.loads(
        (raw / _YESTERDAY[:4] / f"{_YESTERDAY}_101.json").read_text()
    )
    assert raw_payload["extra_field_from_api"] == "kept in raw layer"

    daily = sync_env / "Daily" / f"{_YESTERDAY}.md"
    text = daily.read_text(encoding="utf-8")
    assert text.count(strava.EIR_START) == 1
    assert "Ran 8.2 km" in text
    assert "ran_km: 8.2" in text
    # Old activity is ingested but not projected (outside the window).
    assert not (sync_env / "Daily" / f"{_OLD_DAY}.md").exists()

    second = _run_sync(["sync", "--write"], capsys, monkeypatch)
    assert second["result"]["newActivities"] == 0
    assert second["result"]["rawFilesWritten"] == 0
    assert second["result"]["canonicalAppended"] == {}
    assert second["result"]["dailyNotesWritten"] == []
    assert daily.read_text(encoding="utf-8") == text

    rows = (
        (sync_env / "Health" / "data" / "canonical").glob("activities-*.jsonl")
    )
    total = sum(len(p.read_text().splitlines()) for p in rows)
    assert total == 2
