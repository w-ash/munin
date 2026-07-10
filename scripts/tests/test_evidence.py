"""Tests for the evidence weight-of-evidence scoring + checkpoint CLI."""

import json
from pathlib import Path

import pytest

from vault_scripts import evidence
from vault_scripts._types import Bearing, EvidenceItem, SourceTier, Strength


def item(
    claim_id: str = "c1",
    source_url: str = "https://a.org/1",
    source_tier: SourceTier = "primary",
    bearing: Bearing = "supports",
    strength: Strength = "strong",
    claim: str = "the claim",
    quote: str = "q",
) -> EvidenceItem:
    return EvidenceItem(
        claim_id=claim_id,
        source_url=source_url,
        source_tier=source_tier,
        bearing=bearing,
        strength=strength,
        claim=claim,
        quote=quote,
    )


# --- pure scoring ---


def test_order_independence():
    items = [
        item(source_url="https://a.org/1", source_tier="primary"),
        item(source_url="https://b.org/2", source_tier="secondary", strength="moderate"),
        item(source_url="https://c.org/3", source_tier="weak", bearing="refutes"),
    ]
    fwd = evidence.score_claim(items)
    rev = evidence.score_claim(list(reversed(items)))
    assert fwd["certainty"] == rev["certainty"]
    assert fwd["net_decibans"] == rev["net_decibans"]


def test_tier_ordering():
    p = evidence.score_claim([item(source_tier="primary")])["certainty"]
    s = evidence.score_claim([item(source_tier="secondary")])["certainty"]
    w = evidence.score_claim([item(source_tier="weak")])["certainty"]
    assert p > s >= w  # secondary may hit the ceiling cap; weak stays below it


def test_refutation_drives_refuted_band():
    refutes = [
        item(source_url="https://a.org/1", bearing="refutes"),
        item(source_url="https://b.org/2", bearing="refutes"),
    ]
    v = evidence.score_claim(refutes)
    assert v["band"] == "refuted"
    assert v["certainty"] < 15


def test_ceiling_gate_blocks_top_band_without_primary():
    weak = [
        item(source_url=f"https://s{i}.org/x", source_tier="weak") for i in range(6)
    ]
    v = evidence.score_claim(weak)
    assert v["capped"] is True
    assert v["certainty"] == evidence._DEFAULT_CEILING
    assert v["band"] == "likely"  # capped just below "confident"

    # one primary supporting source lifts the ceiling
    lifted = evidence.score_claim([*weak, item(source_url="https://prime.org/p")])
    assert lifted["capped"] is False
    assert lifted["certainty"] > evidence._DEFAULT_CEILING


def test_same_domain_diminishing_returns():
    same = [item(source_url=f"https://one.org/{i}", source_tier="secondary") for i in range(3)]
    diff = [item(source_url=f"https://d{i}.org/x", source_tier="secondary") for i in range(3)]
    assert evidence.score_claim(same)["net_decibans"] < evidence.score_claim(diff)["net_decibans"]


def test_exact_duplicates_counted_once():
    dup = [item(), item(), item()]  # identical url+bearing+quote
    v = evidence.score_claim(dup)
    assert v["n_sources"] == 1
    assert v["net_decibans"] == evidence.score_claim([item()])["net_decibans"]


def test_band_thresholds():
    assert evidence._band(95) == "established"
    assert evidence._band(80) == "confident"
    assert evidence._band(60) == "likely"
    assert evidence._band(40) == "tentative"
    assert evidence._band(20) == "speculative"
    assert evidence._band(5) == "refuted"


def test_score_items_groups_and_ranks():
    items = [
        item(claim_id="high", source_tier="primary"),
        item(claim_id="low", source_tier="weak", bearing="refutes"),
    ]
    verdicts = evidence.score_items(items)
    assert [v["claim_id"] for v in verdicts] == ["high", "low"]


# --- CLI ---


def _run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["evidence", *argv])
    evidence.main()
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    return out


def test_append_then_merge_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "agent-1.jsonl"
    record = item().model_dump_json()
    _ = _run(["append", "--shard", str(shard), "--json", record], capsys, monkeypatch)
    _ = _run(["append", "--shard", str(shard), "--json", record], capsys, monkeypatch)
    assert len(shard.read_text(encoding="utf-8").splitlines()) == 2

    out = _run(["merge", "--shard", str(shard)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["items_raw"] == 2
    assert result["items_deduped"] == 1


def test_score_cli_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "s.jsonl"
    shard.write_text(
        item(source_url="https://a.org/1").model_dump_json()
        + "\n"
        + item(source_url="https://b.org/2", source_tier="secondary").model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    out = _run(["score", "--shard", str(shard), "--markdown"], capsys, monkeypatch)
    assert out["ok"] is True
    result = out["result"]
    assert isinstance(result, dict)
    assert result["n_items"] == 2
    claims = result["claims"]
    assert isinstance(claims, list)
    assert claims
    assert "Certainty" in str(result["markdown"])


def test_append_invalid_item_is_validation_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "s.jsonl"
    monkeypatch.setattr("sys.argv", ["evidence", "append", "--shard", str(shard), "--json", '{"claim_id":"c"}'])
    with pytest.raises(SystemExit) as exc:
        evidence.main()
    assert exc.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_score_missing_input_is_validation_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("sys.argv", ["evidence", "score"])
    with pytest.raises(SystemExit) as exc:
        evidence.main()
    assert exc.value.code == 2


def test_rubric_cli(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    out = _run(["rubric"], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert "tier_decibans_strong" in result


# --- dropped-line reporting + reserved files ---


def test_merge_reports_dropped_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "finder-1.jsonl"
    shard.write_text(
        item().model_dump_json() + "\n" + '{"claim_id": "half-a-line"\n',
        encoding="utf-8",
    )
    out = _run(["merge", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["items_raw"] == 1
    assert result["dropped_lines"] == 1


def test_run_dir_reads_skip_reserved_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "finder-1.jsonl").write_text(item().model_dump_json() + "\n", encoding="utf-8")
    # citation records in the same dir must not be misread (and miscounted) as evidence
    (tmp_path / "citations.jsonl").write_text('{"source_url": "https://a.org/1"}\n', encoding="utf-8")
    (tmp_path / "merged.jsonl").write_text(item().model_dump_json() + "\n", encoding="utf-8")
    out = _run(["merge", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["shards"] == 1
    assert result["items_raw"] == 1
    assert result["dropped_lines"] == 0


# --- manifest + check ---


def _manifest_json(with_rubric: bool = False) -> str:
    manifest: dict[str, object] = {
        "question": "which is best?",
        "facets": ["f1"],
        "claims": [{"id": "c1", "text": "the claim"}],
    }
    if with_rubric:
        manifest["rubric"] = {
            "criteria": [{"id": "fit", "weight": 1.0, "tier": "must"}],
            "candidates": [{"id": "a"}, {"id": "b"}],
        }
    return json.dumps(manifest)


def test_manifest_write_then_clean_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    out = _run(
        ["manifest", "--run-dir", str(tmp_path), "--json", _manifest_json(with_rubric=True)],
        capsys,
        monkeypatch,
    )
    result = out["result"]
    assert isinstance(result, dict)
    assert result["grid_cells"] == 2
    assert (tmp_path / "manifest.json").is_file()

    (tmp_path / "finder-1.jsonl").write_text(
        item(claim_id="c1").model_dump_json()
        + "\n"
        + item(claim_id="a--fit", source_url="https://b.org/2").model_dump_json()
        + "\n"
        + item(claim_id="freshly-coined", source_url="https://c.org/3").model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    out = _run(["check", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["problems"] == []
    assert result["coined"] == ["freshly-coined"]  # allowed, reported
    assert result["no_evidence"] == ["b--fit"]


def test_check_flags_grid_drift_and_invalid_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _ = _run(
        ["manifest", "--run-dir", str(tmp_path), "--json", _manifest_json(with_rubric=True)],
        capsys,
        monkeypatch,
    )
    (tmp_path / "finder-1.jsonl").write_text(
        item(claim_id="a--fitt").model_dump_json() + "\n" + "not json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["evidence", "check", "--run-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        evidence.main()
    assert exc.value.code == 3
    out = json.loads(capsys.readouterr().out)
    result = out["result"]
    assert isinstance(result, dict)
    problems = result["problems"]
    assert isinstance(problems, list)
    assert any("grid drift: a--fitt" in p for p in problems)
    assert any("invalid line" in p for p in problems)


def test_check_flags_near_miss_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _ = _run(
        ["manifest", "--run-dir", str(tmp_path), "--json", _manifest_json(with_rubric=True)],
        capsys,
        monkeypatch,
    )
    # single-hyphen typo of the registered grid cell a--fit (observed live)
    (tmp_path / "finder-1.jsonl").write_text(
        item(claim_id="a-fit").model_dump_json() + "\n", encoding="utf-8"
    )
    monkeypatch.setattr("sys.argv", ["evidence", "check", "--run-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        evidence.main()
    assert exc.value.code == 3
    out = json.loads(capsys.readouterr().out)
    result = out["result"]
    assert isinstance(result, dict)
    problems = result["problems"]
    assert isinstance(problems, list)
    assert any("probable drift: a-fit resembles registered a--fit" in p for p in problems)
    assert result["coined"] == []  # reclassified as drift, not a new claim


def test_check_verify_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _ = _run(
        ["manifest", "--run-dir", str(tmp_path), "--json", _manifest_json()],
        capsys,
        monkeypatch,
    )
    (tmp_path / "finder-1.jsonl").write_text(
        item(claim_id="c1").model_dump_json() + "\n", encoding="utf-8"
    )
    (tmp_path / "verify-1.jsonl").write_text(
        item(claim_id="c1", bearing="refutes", source_url="https://v.org/1").model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    out = _run(["check", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["verify_covered"] == 1
