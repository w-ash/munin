"""Tests for the stack module (canonical nutrient intake over the supplement stack)."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

import pytest

from vault_scripts import stack


def _note(
    *,
    source_id: str,
    status: str,
    frequency: str,
    ingredients: str,
    pills_per_day: int = 1,
    pills_per_serving: int = 1,
) -> str:
    return textwrap.dedent(f"""\
        ---
        created: "2026-07-12"
        tags:
          - supplement
        name: "{source_id}"
        brand: "Test"
        status: {status}
        frequency: {frequency}
        pills_per_day: {pills_per_day}
        pills_per_serving: {pills_per_serving}
        time_slot: ""
        ingredients:
        {ingredients}
        source_id: "{source_id}"
        ---

        # {source_id}
        """)


_SUBSTANCES = [
    {"key": "magnesium", "name": "Magnesium (elemental)", "unit": "mg", "ul": 350,
     "ul_basis": "supplemental only", "ul_source": "https://ods", "notes": ""},
    {"key": "zinc", "name": "Zinc", "unit": "mg", "ul": 40,
     "ul_basis": "all sources", "ul_source": "https://ods", "notes": ""},
    {"key": "creatine", "name": "Creatine", "unit": "g", "ul": None,
     "ul_basis": None, "ul_source": None, "notes": "no UL"},
    {"key": "iron", "name": "Iron", "unit": "mg", "ul": 45,
     "ul_basis": "all sources", "ul_source": "https://ods", "notes": ""},
    {"key": "taurine", "name": "Taurine", "unit": "mg", "ul": None,
     "ul_basis": None, "ul_source": None, "notes": "no UL"},
]


def _write_vault(root: Path) -> None:
    entries = root / "Health" / "Supplements" / "entries"
    entries.mkdir(parents=True)
    ref = root / "Health" / "data" / "reference"
    ref.mkdir(parents=True)
    (ref / "substances.jsonl").write_text(
        "\n".join(json.dumps(s) for s in _SUBSTANCES) + "\n", encoding="utf-8"
    )
    # Two magnesiums (different products, same substance key) must sum on the
    # elemental figure: 210/3 + 144/3 = 70 + 48 = 118.
    (entries / "mag-glycinate.md").write_text(_note(
        source_id="mag-glycinate", status="active", frequency="daily",
        pills_per_serving=3,
        ingredients='  - { name: "Magnesium", key: magnesium, per_serving: 210, unit: "mg", dv_percent: 50 }',
    ), encoding="utf-8")
    (entries / "mag-threonate.md").write_text(_note(
        source_id="mag-threonate", status="active", frequency="daily",
        pills_per_serving=3,
        ingredients='  - { name: "Magnesium", key: magnesium, per_serving: 144, unit: "mg", dv_percent: 34 }',
    ), encoding="utf-8")
    (entries / "zinc.md").write_text(_note(
        source_id="zinc", status="active", frequency="daily",
        ingredients='  - { name: "Zinc", key: zinc, per_serving: 25, unit: "mg", dv_percent: 227 }',
    ), encoding="utf-8")
    (entries / "creatine.md").write_text(_note(
        source_id="creatine", status="active", frequency="daily",
        ingredients='  - { name: "Creatine", key: creatine, per_serving: 5, unit: "g", dv_percent: null }',
    ), encoding="utf-8")
    # Excluded from the daily stack: as-needed and considering.
    (entries / "iron.md").write_text(_note(
        source_id="iron", status="active", frequency="as-needed",
        ingredients='  - { name: "Iron", key: iron, per_serving: 25, unit: "mg", dv_percent: 139 }',
    ), encoding="utf-8")
    (entries / "taurine.md").write_text(_note(
        source_id="taurine", status="considering", frequency="daily",
        ingredients='  - { name: "Taurine", key: taurine, per_serving: 1500, unit: "mg", dv_percent: null }',
    ), encoding="utf-8")


@pytest.fixture
def vault_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_vault(tmp_path)
    monkeypatch.setattr(stack, "VAULT", tmp_path)
    return tmp_path


def _run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["stack", *argv])
    stack.main()
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    return out


def _by_key(result: dict[str, object]) -> dict[str, dict[str, object]]:
    subs = result["substances"]
    assert isinstance(subs, list)
    return {s["key"]: s for s in subs}


def test_totals_sum_across_products(vault_env, capsys, monkeypatch):
    out = _run(["totals"], capsys, monkeypatch)
    assert out["ok"] is True
    result = out["result"]
    by = _by_key(result)
    mag = by["magnesium"]
    assert mag["daily_amount"] == pytest.approx(118.0)
    assert sorted(mag["products"]) == ["mag-glycinate", "mag-threonate"]
    assert result["productsCounted"] == 4  # two mags + zinc + creatine
    assert result["warnings"] == []


def test_as_needed_and_considering_excluded(vault_env, capsys, monkeypatch):
    by = _by_key(_run(["totals"], capsys, monkeypatch)["result"])
    assert "iron" not in by  # as-needed
    assert "taurine" not in by  # considering


def test_ul_comparison_fields(vault_env, capsys, monkeypatch):
    by = _by_key(_run(["totals"], capsys, monkeypatch)["result"])
    zinc = by["zinc"]
    assert zinc["ul"] == 40
    assert zinc["daily_amount"] == pytest.approx(25.0)
    assert zinc["pct_of_ul"] == pytest.approx(62.5)
    assert zinc["headroom"] == pytest.approx(15.0)
    assert zinc["over_ul"] is False
    # No UL -> null comparison fields.
    creatine = by["creatine"]
    assert creatine["ul"] is None
    assert creatine["pct_of_ul"] is None
    assert creatine["over_ul"] is None


def test_uls_lists_only_ul_bearing(vault_env, capsys, monkeypatch):
    result = _run(["uls"], capsys, monkeypatch)["result"]
    keys = {s["key"] for s in result["substances"]}
    assert keys == {"magnesium", "zinc"}  # creatine has no UL; iron/taurine excluded
    assert result["overUl"] == []  # nothing over UL in the fixture


def test_over_ul_flagged(vault_env, capsys, monkeypatch):
    # Bump zinc over its UL with a second active daily zinc product.
    entries = vault_env / "Health" / "Supplements" / "entries"
    (entries / "zinc2.md").write_text(_note(
        source_id="zinc2", status="active", frequency="daily",
        ingredients='  - { name: "Zinc", key: zinc, per_serving: 30, unit: "mg", dv_percent: 273 }',
    ), encoding="utf-8")
    result = _run(["uls"], capsys, monkeypatch)["result"]
    assert result["overUl"] == ["zinc"]
    zinc = next(s for s in result["substances"] if s["key"] == "zinc")
    assert zinc["daily_amount"] == pytest.approx(55.0)
    assert zinc["over_ul"] is True


def test_ingredients_dry_run_writes_nothing(vault_env, capsys, monkeypatch):
    out = _run(["ingredients"], capsys, monkeypatch)
    result = out["result"]
    assert result["dryRun"] is True
    assert result["rows"] == 6  # one row per ingredient across all six notes
    derived = vault_env / "Health" / "data" / "derived" / "product-ingredients.jsonl"
    assert not derived.exists()


def test_ingredients_write_round_trip(vault_env, capsys, monkeypatch):
    out = _run(["ingredients", "--write"], capsys, monkeypatch)
    assert out["result"]["rows"] == 6
    derived = vault_env / "Health" / "data" / "derived" / "product-ingredients.jsonl"
    lines = [json.loads(x) for x in derived.read_text().splitlines() if x.strip()]
    assert len(lines) == 6
    mag = next(r for r in lines if r["product"] == "mag-glycinate")
    assert mag["per_pill"] == pytest.approx(70.0)
    assert mag["key"] == "magnesium"
    # Idempotent: a second write reproduces the same row count.
    out2 = _run(["ingredients", "--write"], capsys, monkeypatch)
    assert out2["result"]["rows"] == 6


def test_unknown_key_warns(vault_env, capsys, monkeypatch):
    entries = vault_env / "Health" / "Supplements" / "entries"
    (entries / "mystery.md").write_text(_note(
        source_id="mystery", status="active", frequency="daily",
        ingredients='  - { name: "Mystery", key: not_a_real_key, per_serving: 1, unit: "mg", dv_percent: null }',
    ), encoding="utf-8")
    warnings = _run(["totals"], capsys, monkeypatch)["result"]["warnings"]
    assert any("not_a_real_key" in w for w in warnings)


def test_unit_mismatch_warns(vault_env, capsys, monkeypatch):
    entries = vault_env / "Health" / "Supplements" / "entries"
    (entries / "badunit.md").write_text(_note(
        source_id="badunit", status="active", frequency="daily",
        ingredients='  - { name: "Zinc", key: zinc, per_serving: 100, unit: "mcg", dv_percent: null }',
    ), encoding="utf-8")
    warnings = _run(["totals"], capsys, monkeypatch)["result"]["warnings"]
    assert any("zinc" in w and "mcg" in w for w in warnings)


def test_missing_registry_is_validation_error(vault_env, capsys, monkeypatch):
    (vault_env / "Health" / "data" / "reference" / "substances.jsonl").unlink()
    monkeypatch.setattr("sys.argv", ["stack", "totals"])
    with pytest.raises(SystemExit) as exc:
        stack.main()
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


# --- Regimen event log + effective dating (slice 2) ---


def _note_mirror(source_id: str):
    return stack._note_index()[source_id][1]


def test_fold_effective_dating(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    _run(["set", "x", "--product", "creatine", "--pills", "1",
          "--effective", "2026-08-01", "--slot", "3-dinner", "--write"],
         capsys, monkeypatch)
    before = _run(["show", "--as-of", "2026-07-15"], capsys, monkeypatch)["result"]
    after = _run(["show", "--as-of", "2026-08-05"], capsys, monkeypatch)["result"]
    none = _run(["show", "--as-of", "2026-07-01"], capsys, monkeypatch)["result"]
    assert [r["product"] for r in before["roles"]] == ["zinc"]
    assert [r["product"] for r in after["roles"]] == ["creatine"]
    assert none["roles"] == []


def test_set_syncs_mirror_today(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "2",
          "--effective", "2026-07-12", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    z = _note_mirror("zinc")
    assert z.status == "active"
    assert z.pills_per_day == 2
    assert z.time_slot == "2-breakfast"


def test_future_effective_keeps_considering(vault_env, capsys, monkeypatch):
    # taurine is `considering`; a future-dated set must not activate it today.
    _run(["set", "taurine_role", "--product", "taurine", "--pills", "1",
          "--effective", "2027-01-01", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    assert _note_mirror("taurine").status == "considering"
    future = _run(["show", "--as-of", "2027-02-01"], capsys, monkeypatch)["result"]
    assert any(r["product"] == "taurine" for r in future["roles"])


def test_supersede_stops_old_product(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    _run(["set", "x", "--product", "creatine", "--pills", "1",
          "--effective", "2026-07-13", "--slot", "3-dinner", "--write"],
         capsys, monkeypatch)
    assert _note_mirror("creatine").status == "active"
    assert _note_mirror("zinc").status == "stopped"  # managed, out of the fold


def test_stop_ends_role_and_stops_product(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    _run(["stop", "x", "--effective", "2026-07-13", "--write"], capsys, monkeypatch)
    after = _run(["show", "--as-of", "2026-07-20"], capsys, monkeypatch)["result"]
    assert after["roles"] == []
    assert _note_mirror("zinc").status == "stopped"


def test_stop_unknown_role_is_error(vault_env, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["stack", "stop", "nope", "--effective", "2026-07-12"])
    with pytest.raises(SystemExit) as exc:
        stack.main()
    assert exc.value.code == 2


def test_check_detects_mirror_drift(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--slot", "2-breakfast", "--write"],
         capsys, monkeypatch)
    path = vault_env / "Health" / "Supplements" / "entries" / "zinc.md"
    path.write_text(
        path.read_text().replace("pills_per_day: 1", "pills_per_day: 9"),
        encoding="utf-8",
    )
    result = _run(["check"], capsys, monkeypatch)["result"]
    assert result["ok"] is False
    assert any(d.get("role") == "x" for d in result["drift"])


def test_history_orders_events(vault_env, capsys, monkeypatch):
    _run(["set", "x", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--write"], capsys, monkeypatch)
    _run(["stop", "x", "--effective", "2026-08-01", "--write"], capsys, monkeypatch)
    result = _run(["history", "x"], capsys, monkeypatch)["result"]
    events = result["events"]
    assert [e["event"] for e in events] == ["set", "stop"]


# --- Exceptions + derived daily record (slice 3) ---


def _seed_zinc_role(capsys, monkeypatch, *, slot: str = "2-breakfast", pills: int = 1):
    _run(["set", "x", "--product", "zinc", "--pills", str(pills),
          "--effective", "2026-07-12", "--slot", slot, "--write"], capsys, monkeypatch)


def _day(day: str, capsys, monkeypatch) -> dict[str, object]:
    return _run(["day", day], capsys, monkeypatch)["result"]


def test_day_plan_rows(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    day = _day("2026-07-14", capsys, monkeypatch)
    assert len(day["rows"]) == 1  # zinc has one ingredient in the fixture
    assert all(r["basis"] == "plan" for r in day["rows"])
    zinc = next(t for t in day["totals"] if t["key"] == "zinc")
    assert zinc["amount"] == pytest.approx(25.0)


def test_miss_slot_removes_rows(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    _run(["log", "miss", "--date", "2026-07-14", "--scope", "slot",
          "--slot", "2-breakfast", "--write"], capsys, monkeypatch)
    assert _day("2026-07-14", capsys, monkeypatch)["rows"] == []
    # An unaffected day still has the plan row.
    assert len(_day("2026-07-13", capsys, monkeypatch)["rows"]) == 1


def test_miss_day_empties(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    _run(["log", "miss", "--date", "2026-07-14", "--scope", "day", "--write"],
         capsys, monkeypatch)
    assert _day("2026-07-14", capsys, monkeypatch)["rows"] == []


def test_taken_prn_adds_exception_rows(vault_env, capsys, monkeypatch):
    # An as-needed role contributes nothing from the plan; only a logged `taken`
    # produces rows.
    _run(["set", "ironrole", "--product", "zinc", "--pills", "1",
          "--effective", "2026-07-12", "--frequency", "as-needed", "--write"],
         capsys, monkeypatch)
    assert _day("2026-07-13", capsys, monkeypatch)["rows"] == []
    _run(["log", "taken", "--date", "2026-07-13", "--role", "ironrole",
          "--pills", "1", "--write"], capsys, monkeypatch)
    rows = _day("2026-07-13", capsys, monkeypatch)["rows"]
    assert len(rows) == 1
    assert rows[0]["basis"] == "exception"
    assert rows[0]["event_id"].startswith("exc-")


def test_dose_change_overrides_pills(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    _run(["log", "dose_change", "--date", "2026-07-14", "--role", "x",
          "--pills", "3", "--write"], capsys, monkeypatch)
    zinc = next(t for t in _day("2026-07-14", capsys, monkeypatch)["totals"]
                if t["key"] == "zinc")
    assert zinc["amount"] == pytest.approx(75.0)  # 25 per pill x 3


def test_substitute_swaps_product(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    _run(["log", "substitute", "--date", "2026-07-14", "--role", "x",
          "--product", "creatine", "--write"], capsys, monkeypatch)
    rows = _day("2026-07-14", capsys, monkeypatch)["rows"]
    assert [r["key"] for r in rows] == ["creatine"]


def test_derive_writes_intake_and_idempotent(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    out = _run(["derive", "--write"], capsys, monkeypatch)["result"]
    assert out["range"]["from"] == "2026-07-12"
    intake = vault_env / "Health" / "data" / "derived" / "intake-2026.jsonl"
    first = [x for x in intake.read_text().splitlines() if x.strip()]
    assert len(first) == out["rows"]
    # Idempotent: a second derive reproduces the same row count.
    out2 = _run(["derive", "--write"], capsys, monkeypatch)["result"]
    second = [x for x in intake.read_text().splitlines() if x.strip()]
    assert len(second) == out2["rows"] == len(first)


def test_log_unknown_kind_is_error(vault_env, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["stack", "log", "bogus", "--write"])
    with pytest.raises(SystemExit) as exc:
        stack.main()
    assert exc.value.code == 2


def _expect_log_error(argv, capsys, monkeypatch) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["stack", *argv])
    with pytest.raises(SystemExit) as exc:
        stack.main()
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    assert out["ok"] is False
    return out


def test_log_unknown_product_is_error(vault_env, capsys, monkeypatch):
    _expect_log_error(
        ["log", "taken", "--product", "not-a-real-sku", "--write"], capsys, monkeypatch
    )


def test_log_taken_unresolvable_role_is_error(vault_env, capsys, monkeypatch):
    # No product and a role with no regimen fill -> would derive nothing silently.
    _expect_log_error(
        ["log", "taken", "--role", "ghost", "--pills", "1", "--write"],
        capsys, monkeypatch,
    )


def test_log_miss_slot_requires_slot(vault_env, capsys, monkeypatch):
    _expect_log_error(
        ["log", "miss", "--date", "2026-07-14", "--scope", "slot", "--write"],
        capsys, monkeypatch,
    )


def test_log_substitute_bad_product_is_error(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    # Role x has a fill, but the substitute product is a typo: must not silently
    # drop x's planned intake for the day.
    _expect_log_error(
        ["log", "substitute", "--date", "2026-07-14", "--role", "x",
         "--product", "typo-sku", "--write"],
        capsys, monkeypatch,
    )


def test_log_dose_change_requires_positive_pills(vault_env, capsys, monkeypatch):
    _seed_zinc_role(capsys, monkeypatch)
    _expect_log_error(
        ["log", "dose_change", "--date", "2026-07-14", "--role", "x", "--write"],
        capsys, monkeypatch,
    )
