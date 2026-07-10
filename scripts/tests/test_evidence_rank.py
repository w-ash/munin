"""Tests for the ranking rollup (rubric mode) of the evidence module."""

import json
from pathlib import Path

import pytest

from vault_scripts import evidence
from vault_scripts._types import (
    EvidenceItem,
    Rubric,
    RubricCandidate,
    RubricCriterion,
    SourceTier,
)


def cell_item(
    candidate: str,
    criterion: str,
    *,
    source_url: str = "https://a.org/1",
    source_tier: SourceTier = "primary",
    bearing: str = "supports",
    strength: str = "strong",
) -> EvidenceItem:
    return EvidenceItem.model_validate(
        {
            "claim_id": f"{candidate}--{criterion}",
            "source_url": source_url,
            "source_tier": source_tier,
            "bearing": bearing,
            "strength": strength,
            "quote": "q",
        }
    )


def rubric(
    criteria: list[RubricCriterion] | None = None,
    candidates: list[str] | None = None,
    blocker_threshold: float = 50.0,
) -> Rubric:
    return Rubric(
        criteria=criteria
        or [
            RubricCriterion(id="fit", weight=2.0, tier="must"),
            RubricCriterion(id="price", weight=1.0, tier="should"),
        ],
        candidates=[RubricCandidate(id=c) for c in (candidates or ["a", "b"])],
        blocker_threshold=blocker_threshold,
    )


def test_no_evidence_sits_at_prior():
    verdicts = evidence.rank_candidates([], rubric())
    # scores are round()ed to one decimal, so exact comparison via string form
    assert [str(v["score"]) for v in verdicts] == ["50.0", "50.0"]
    assert all(
        str(s["certainty"]) == "50.0" and s["n_sources"] == 0
        for v in verdicts
        for s in v["criteria"]
    )


def test_weighted_rollup_orders_candidates():
    items = [
        cell_item("a", "fit"),
        cell_item("a", "price", source_url="https://b.org/2"),
        cell_item("b", "fit", bearing="refutes"),
    ]
    verdicts = evidence.rank_candidates(items, rubric())
    assert [v["candidate_id"] for v in verdicts] == ["a", "b"]
    a, b = verdicts
    assert a["score"] > 50.0 > b["score"]
    # weight-normalized: fit (w=2) moves the score twice as far as price (w=1)
    fit_c = next(s["certainty"] for s in a["criteria"] if s["criterion_id"] == "fit")
    price_c = next(s["certainty"] for s in a["criteria"] if s["criterion_id"] == "price")
    expected = (fit_c * 2.0 + price_c * 1.0) / 3.0
    assert a["score"] == round(expected, 1)


def test_blocker_gates_and_sorts_last():
    r = rubric(
        criteria=[
            RubricCriterion(id="deal-breaker", weight=1.0, tier="blocker"),
            RubricCriterion(id="nice", weight=10.0, tier="nice"),
        ]
    )
    items = [
        # candidate a: fails the blocker but aces the heavy nice-to-have
        cell_item("a", "deal-breaker", bearing="refutes"),
        cell_item("a", "nice"),
        # candidate b: mediocre everywhere but clean
        cell_item("b", "deal-breaker", source_tier="secondary", strength="weak"),
    ]
    verdicts = evidence.rank_candidates(items, r)
    by_id = {v["candidate_id"]: v for v in verdicts}
    assert by_id["a"]["blocked"] is True
    assert by_id["a"]["blocked_by"] == ["deal-breaker"]
    blocker_certainty = next(
        s["certainty"] for s in by_id["a"]["criteria"] if s["criterion_id"] == "deal-breaker"
    )
    assert by_id["a"]["score"] <= blocker_certainty  # capped at the failing blocker
    assert by_id["b"]["blocked"] is False
    assert [v["candidate_id"] for v in verdicts] == ["b", "a"]  # clean outranks blocked


def test_least_resolved_and_evidence_gaps():
    r = rubric(
        criteria=[
            RubricCriterion(id="strong-evidence", weight=1.0, tier="must"),
            RubricCriterion(id="thin", weight=1.0, tier="must"),
            RubricCriterion(id="ignored", weight=1.0, tier="nice"),
        ],
        candidates=["a"],
    )
    items = [
        cell_item("a", "strong-evidence"),
        cell_item("a", "strong-evidence", source_url="https://b.org/2"),
        cell_item("a", "thin", source_tier="weak", strength="weak"),
    ]
    (v,) = evidence.rank_candidates(items, r)
    # "thin" barely moves off the prior: least resolved of the load-bearing set
    assert v["least_resolved"] == "thin"
    assert v["evidence_gaps"] == ["thin"]  # nice-tier "ignored" is not load-bearing


def test_zero_weight_rubric_is_error():
    r = rubric(criteria=[RubricCriterion(id="x", weight=0.0)])
    with pytest.raises(evidence.CliError):
        evidence.rank_candidates([], r)


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


def test_rank_cli_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "finder-1.jsonl"
    shard.write_text(
        cell_item("a", "fit").model_dump_json() + "\n",
        encoding="utf-8",
    )
    rubric_file = tmp_path / "rubric.json"
    rubric_file.write_text(rubric(candidates=["a"]).model_dump_json(), encoding="utf-8")
    out = _run(
        ["rank", "--run-dir", str(tmp_path), "--rubric", str(rubric_file), "--markdown"],
        capsys,
        monkeypatch,
    )
    assert out["ok"] is True
    result = out["result"]
    assert isinstance(result, dict)
    candidates = result["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 1
    assert "| Rank | Candidate |" in str(result["markdown"])


def test_rank_cli_falls_back_to_manifest_rubric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "question": "q",
        "rubric": {
            "criteria": [{"id": "fit", "weight": 1.0, "tier": "must"}],
            "candidates": [{"id": "a", "name": "Candidate A"}],
        },
    }
    _ = _run(
        ["manifest", "--run-dir", str(tmp_path), "--json", json.dumps(manifest)],
        capsys,
        monkeypatch,
    )
    (tmp_path / "finder-1.jsonl").write_text(
        cell_item("a", "fit").model_dump_json() + "\n", encoding="utf-8"
    )
    out = _run(["rank", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    candidates = result["candidates"]
    assert isinstance(candidates, list)
    verdict = candidates[0]
    assert isinstance(verdict, dict)
    assert verdict["candidate"] == "Candidate A"


def test_rank_cli_rejects_bad_rubric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "finder-1.jsonl"
    shard.write_text(cell_item("a", "fit").model_dump_json() + "\n", encoding="utf-8")
    rubric_file = tmp_path / "rubric.json"
    rubric_file.write_text('{"criteria": "nope"}', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["evidence", "rank", "--run-dir", str(tmp_path), "--rubric", str(rubric_file)],
    )
    with pytest.raises(SystemExit) as exc:
        evidence.main()
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
