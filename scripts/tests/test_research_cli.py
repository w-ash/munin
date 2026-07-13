"""Smoke tests: each subcommand emits exactly one JSON envelope on stdout."""

import csv
import json
from pathlib import Path
import sys
from unittest import mock

import pytest

from vault_scripts.research import cli, mirror, score, sheets, store, verify


def run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, object]:
    with mock.patch.object(sys, "argv", ["research", *argv]):
        cli.main()
    out = capsys.readouterr().out.strip()
    envelope = json.loads(out)
    # Exactly one envelope on stdout: one top-level "ok": key (a nested
    # status value like "ok" inside the payload doesn't match the colon).
    assert out.count('"ok":') == 1
    return envelope


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Append rows to a scaffolded CSV, reading the header for field order."""
    with path.open(newline="", encoding="utf-8") as f:
        fieldnames = next(csv.reader(f))
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)


def seed_map_topic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold and seed a small map topic with known confidence math."""
    run(capsys, ["new", "demo", "Demo", "--dest", str(tmp_path)])
    data = tmp_path / "demo" / "data"
    append_rows(
        data / "taxonomy.csv",
        [
            {
                "category_id": "C1",
                "name": "Alpha things",
                "definition": "d",
                "boundary": "b",
            },
            {
                "category_id": "C2",
                "name": "Beta things",
                "definition": "d",
                "boundary": "b",
            },
        ],
    )
    common = {"pass": "1", "date_captured": "2026-07-10", "finding_verbatim": "f"}
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": "E001",
                "unit": "Alpha Corp",
                "category_id": "C1",
                "source_type": "Primary source",
                "source_url": "https://example.com/1",
                **common,
            },
            {
                "evidence_id": "E002",
                "unit": "Beta Inc",
                "category_id": "C1",
                "source_type": "posting",
                "source_url": "https://example.com/2",
                **common,
            },
            {
                "evidence_id": "E003",
                "unit": "Gamma LLC",
                "category_id": "C2",
                "source_type": "posting",
                "source_url": "https://example.com/3",
                **common,
            },
            {
                "evidence_id": "E004",
                "unit": "Delta Co",
                "category_id": "C2-div",
                "source_type": "posting",
                "source_url": "https://example.com/4",
                **common,
            },
        ],
    )
    append_rows(
        data / "sources.csv",
        [
            {
                "source_id": "S001",
                "unit": "Alpha Corp",
                "title": "t",
                "source_type": "Primary source",
                "pass": "1",
                "url": "https://example.com/1",
            }
        ],
    )
    return tmp_path / "demo"


def test_status_scores_map_exactly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin pre-v0.3 map scoring; the mode-branching refactor must not move it."""
    topic = seed_map_topic(tmp_path, capsys)
    envelope = run(capsys, ["status", "--dir", str(topic)])
    assert envelope["topic"] == "Demo"
    assert envelope["categories"] == [
        {
            "category_id": "C1",
            "name": "Alpha things",
            "supporting_units": 2,
            "diverging_units": 0,
            "evidence_count": 2,
            "confidence": 0.2,
            "primary_backed": True,
            "tier": "Low",
        },
        {
            "category_id": "C2",
            "name": "Beta things",
            "supporting_units": 1,
            "diverging_units": 1,
            "evidence_count": 1,
            "confidence": 0.0,
            "primary_backed": False,
            "tier": "Low",
        },
    ]
    assert envelope["counts"] == {
        "rows": {"taxonomy.csv": 2, "evidence.csv": 4, "sources.csv": 1},
        "distinct_units": 4,
        "max_pass": 1,
    }


def test_score_is_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`status` is an alias of the mode-dispatched `score`: same envelope."""
    topic = seed_map_topic(tmp_path, capsys)
    status_envelope = run(capsys, ["status", "--dir", str(topic)])
    score_envelope = run(capsys, ["score", "--dir", str(topic)])
    assert score_envelope == status_envelope


QUOTE = "alpha beta gamma delta"


def seed_verify_topic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold and seed a small verify topic with known certainty math."""
    run(
        capsys,
        ["new", "demo-v", "Demo Verify", "--dest", str(tmp_path), "--mode", "verify"],
    )
    data = tmp_path / "demo-v" / "data"
    append_rows(
        data / "claims.csv",
        [
            {"claim_id": "CL1", "claim": "First claim", "notes": ""},
            {"claim_id": "CL2", "claim": "Second claim", "notes": ""},
        ],
    )
    common = {
        "pass": "1",
        "date_captured": "2026-07-10",
        "quote": QUOTE,
        "source_type": "web",
    }
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": "E001",
                "claim_id": "CL1",
                "source_tier": "primary",
                "strength": "strong",
                "bearing": "supports",
                "source_url": "https://a.com/1",
                **common,
            },
            {
                "evidence_id": "E002",
                "claim_id": "CL1",
                "source_tier": "secondary",
                "strength": "moderate",
                "bearing": "supports",
                "source_url": "https://b.com/2",
                **common,
            },
            {
                "evidence_id": "E003",
                "claim_id": "CL2",
                "source_tier": "weak",
                "strength": "weak",
                "bearing": "supports",
                "source_url": "https://c.com/3",
                **common,
            },
            {
                "evidence_id": "E004",
                "claim_id": "CL2",
                "source_tier": "primary",
                "strength": "strong",
                "bearing": "refutes",
                "source_url": "https://d.com/4",
                **common,
            },
        ],
    )
    return tmp_path / "demo-v"


def test_verify_scores_exactly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the decibans certainty envelope for a known verify topic."""
    topic = seed_verify_topic(tmp_path, capsys)
    envelope = run(capsys, ["score", "--dir", str(topic)])
    assert envelope["topic"] == "Demo Verify"
    assert envelope["claims"] == [
        {
            "claim_id": "CL1",
            "claim": "First claim",
            "certainty": 97.5,
            "band": "established",
            "net_decibans": 16.0,
            "n_sources": 2,
            "capped": False,
        },
        {
            "claim_id": "CL2",
            "claim": "Second claim",
            "certainty": 6.9,
            "band": "refuted",
            "net_decibans": -11.33,
            "n_sources": 2,
            "capped": False,
        },
    ]


def test_verify_writes_citations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`research verify` persists per-row verdicts to data/citations.csv."""
    topic = seed_verify_topic(tmp_path, capsys)
    page = verify.FetchResult(200, "text/html", f"<p>{QUOTE}</p>")
    with mock.patch.object(verify, "fetch_url", return_value=page):
        envelope = run(capsys, ["verify", "--dir", str(topic), "--no-cache"])
    assert envelope["checked"] == 4
    citations = topic / "data" / "citations.csv"
    assert citations.exists()
    with citations.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["evidence_id"] for r in rows} == {"E001", "E002", "E003", "E004"}
    assert all(r["status"] == "verified" for r in rows)


def test_verify_no_write_skips_citations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    topic = seed_verify_topic(tmp_path, capsys)
    page = verify.FetchResult(200, "text/html", f"<p>{QUOTE}</p>")
    with mock.patch.object(verify, "fetch_url", return_value=page):
        run(capsys, ["verify", "--dir", str(topic), "--no-cache", "--no-write"])
    assert not (topic / "data" / "citations.csv").exists()


def seed_rank_topic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold and seed a small rank topic with a known rubric rollup."""
    run(
        capsys,
        ["new", "demo-r", "Demo Rank", "--dest", str(tmp_path), "--mode", "rank"],
    )
    data = tmp_path / "demo-r" / "data"
    append_rows(
        data / "candidates.csv",
        [
            {"candidate_id": "alpha", "name": "Alpha"},
            {"candidate_id": "beta", "name": "Beta"},
        ],
    )
    append_rows(
        data / "criteria.csv",
        [
            {
                "criterion_id": "quality",
                "text": "Quality",
                "weight": "2",
                "tier": "must",
            },
            {"criterion_id": "price", "text": "Price", "weight": "1", "tier": "should"},
        ],
    )
    common = {
        "pass": "1",
        "date_captured": "2026-07-10",
        "quote": QUOTE,
        "source_type": "web",
    }
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": "R1",
                "cell_id": "alpha--quality",
                "source_tier": "primary",
                "strength": "strong",
                "bearing": "supports",
                "source_url": "https://a.org/1",
                **common,
            },
            {
                "evidence_id": "R2",
                "cell_id": "alpha--price",
                "source_tier": "secondary",
                "strength": "moderate",
                "bearing": "supports",
                "source_url": "https://b.org/2",
                **common,
            },
            {
                "evidence_id": "R3",
                "cell_id": "beta--quality",
                "source_tier": "weak",
                "strength": "weak",
                "bearing": "supports",
                "source_url": "https://x.org/9",
                **common,
            },
        ],
    )
    return tmp_path / "demo-r"


def test_rank_scores_exactly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the rubric rollup envelope for a known rank topic."""
    topic = seed_rank_topic(tmp_path, capsys)
    envelope = run(capsys, ["score", "--dir", str(topic)])
    assert envelope["topic"] == "Demo Rank"
    assert envelope["candidates"] == [
        {
            "candidate_id": "alpha",
            "candidate": "Alpha",
            "score": 86.6,
            "blocked": False,
            "blocked_by": [],
            "least_resolved": "quality",
            "evidence_gaps": ["quality"],
            "criteria": [
                {
                    "criterion_id": "quality",
                    "tier": "must",
                    "certainty": 94.1,
                    "band": "established",
                    "n_sources": 1,
                    "capped": False,
                },
                {
                    "criterion_id": "price",
                    "tier": "should",
                    "certainty": 71.5,
                    "band": "likely",
                    "n_sources": 1,
                    "capped": False,
                },
            ],
        },
        {
            "candidate_id": "beta",
            "candidate": "Beta",
            "score": 52.5,
            "blocked": False,
            "blocked_by": [],
            "least_resolved": "quality",
            "evidence_gaps": ["quality"],
            "criteria": [
                {
                    "criterion_id": "quality",
                    "tier": "must",
                    "certainty": 53.8,
                    "band": "tentative",
                    "n_sources": 1,
                    "capped": False,
                },
                {
                    "criterion_id": "price",
                    "tier": "should",
                    "certainty": 50.0,
                    "band": "tentative",
                    "n_sources": 0,
                    "capped": False,
                },
            ],
        },
    ]


def seed_find_topic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold and seed a small find topic with known coverage math."""
    run(
        capsys,
        ["new", "demo-f", "Demo Find", "--dest", str(tmp_path), "--mode", "find"],
    )
    root = tmp_path / "demo-f"
    data = root / "data"
    # entities.csv is a wide table: core columns plus one column per attribute.
    with (data / "entities.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entity_id", "name", "in_frame", "role", "email"])
        w.writerow(["E001", "Ada", "yes", "CTO", "ada@x.com"])
        w.writerow(["E002", "Ben", "yes", "VP", ""])
        w.writerow(["E003", "Zed", "no", "", ""])
    append_rows(
        data / "attributes.csv",
        [
            {"attribute_id": "role", "name": "Role", "required": "yes"},
            {"attribute_id": "email", "name": "Email", "required": "no"},
        ],
    )
    common = {
        "pass": "1",
        "date_captured": "2026-07-10",
        "quote": QUOTE,
        "source_type": "web",
    }
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": "F1",
                "cell_id": "E001--role",
                "source_url": "https://a.com/1",
                **common,
            },
            {
                "evidence_id": "F2",
                "cell_id": "E001--email",
                "source_url": "https://a.com/2",
                **common,
            },
            {
                "evidence_id": "F3",
                "cell_id": "E002--role",
                "source_url": "https://b.com/3",
                **common,
            },
        ],
    )
    config = root / "research.toml"
    config.write_text(
        config
        .read_text()
        .replace('frame = "{{FRAME_DEFINITION}}"', 'frame = "top 4 orgs"')
        .replace('expected_count = ""', "expected_count = 4"),
        encoding="utf-8",
    )
    return root


def test_find_scores_exactly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the coverage envelope for a known find topic (no citations yet)."""
    topic = seed_find_topic(tmp_path, capsys)
    envelope = run(capsys, ["score", "--dir", str(topic)])
    assert envelope["topic"] == "Demo Find"
    assert envelope["frame"] == "top 4 orgs"
    assert envelope["expected"] == 4
    assert envelope["found"] == 2
    assert envelope["recall"] == 0.5
    assert envelope["field_fill"] == 0.75
    assert envelope["field_verified"] == 0.0
    assert envelope["saturating"] == [{"pass": 1, "new": 2}]
    assert envelope["thin_entities"] == []
    assert envelope["attributes"] == [
        {
            "attribute_id": "role",
            "name": "Role",
            "required": True,
            "n_filled": 2,
            "n_verified": 0,
            "fill_rate": 1.0,
            "verified_rate": 0.0,
        },
        {
            "attribute_id": "email",
            "name": "Email",
            "required": False,
            "n_filled": 1,
            "n_verified": 0,
            "fill_rate": 0.5,
            "verified_rate": 0.0,
        },
    ]


def test_find_verify_then_score_marks_fields_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After `research verify`, the scorer reads citations.csv as the per-field
    verified signal, so every sourced cell counts as verified."""
    topic = seed_find_topic(tmp_path, capsys)
    page = verify.FetchResult(200, "text/html", f"<p>{QUOTE}</p>")
    with mock.patch.object(verify, "fetch_url", return_value=page):
        run(capsys, ["verify", "--dir", str(topic), "--no-cache"])
    envelope = run(capsys, ["score", "--dir", str(topic)])
    assert envelope["field_verified"] == 1.0
    roles = next(a for a in envelope["attributes"] if a["attribute_id"] == "role")
    assert roles["verified_rate"] == 1.0
    assert roles["n_verified"] == 2


def seed_estimate_topic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold and seed a pure-product estimate topic (analytic path)."""
    run(
        capsys,
        [
            "new",
            "demo-e",
            "Demo Estimate",
            "--dest",
            str(tmp_path),
            "--mode",
            "estimate",
        ],
    )
    data = tmp_path / "demo-e" / "data"
    factor = {"distribution": "lognormal", "notes": ""}
    append_rows(
        data / "factors.csv",
        [
            {
                "factor_id": "F1",
                "name": "orgs",
                "op": "mul",
                "low": "1000",
                "mid": "",
                "high": "1000",
                **factor,
            },
            {
                "factor_id": "F2",
                "name": "rate",
                "op": "mul",
                "low": "0.05",
                "mid": "",
                "high": "0.20",
                **factor,
            },
            {
                "factor_id": "F3",
                "name": "seats",
                "op": "mul",
                "low": "10",
                "mid": "",
                "high": "40",
                **factor,
            },
        ],
    )
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": "EV1",
                "pass": "1",
                "date_captured": "2026-07-10",
                "factor_id": "F1",
                "quote": QUOTE,
                "source_type": "web",
                "source_url": "https://a.com/1",
                "published_date": "",
                "notes": "",
            }
        ],
    )
    return tmp_path / "demo-e"


def test_estimate_scores_exactly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the analytic lognormal envelope for a known pure-product estimate."""
    topic = seed_estimate_topic(tmp_path, capsys)
    envelope = run(capsys, ["score", "--dir", str(topic)])
    assert envelope["topic"] == "Demo Estimate"
    assert envelope["method"] == "analytic-lognormal"
    assert envelope["median"] == 2000.0
    assert envelope["low"] == 750.4
    assert envelope["high"] == 5330.0
    assert envelope["ci"] == 90.0
    assert envelope["dominant_factor"] == "F2"
    assert envelope["factors"] == [
        {
            "factor_id": "F1",
            "name": "orgs",
            "op": "mul",
            "mu": 6.9078,
            "sigma": 0.0,
            "variance_share": 0.0,
        },
        {
            "factor_id": "F2",
            "name": "rate",
            "op": "mul",
            "mu": -2.3026,
            "sigma": 0.4214,
            "variance_share": 0.5,
        },
        {
            "factor_id": "F3",
            "name": "seats",
            "op": "mul",
            "mu": 2.9957,
            "sigma": 0.4214,
            "variance_share": 0.5,
        },
    ]


def write_gold(topic: Path, rows: list[tuple[str, str]]) -> None:
    """Hand-author a data/gold.csv (item_id, label) for calibrate tests."""
    with (topic / "data" / "gold.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "label", "notes"])
        w.writerows([item_id, label, ""] for item_id, label in rows)


def empty_bins() -> list[dict[str, object]]:
    """The ten-bin reliability envelope shape with every bin empty."""
    return [
        {
            "lower": i / 10,
            "upper": (i + 1) / 10,
            "n": 0,
            "mean_probability": None,
            "hit_rate": None,
        }
        for i in range(10)
    ]


def test_calibrate_map_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin the reliability envelope for a known map topic and gold set."""
    topic = seed_map_topic(tmp_path, capsys)
    write_gold(topic, [("C1", "true"), ("C2", "false")])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["mode"] == "map"
    assert envelope["item_kind"] == "category"
    assert envelope["n_scored"] == 2
    assert envelope["n_gold"] == 2
    assert envelope["ece"] == 0.4
    assert envelope["brier"] == 0.32
    bins = empty_bins()
    bins[0] = {
        "lower": 0.0,
        "upper": 0.1,
        "n": 1,
        "mean_probability": 0.0,
        "hit_rate": 0.0,
    }
    bins[2] = {
        "lower": 0.2,
        "upper": 0.3,
        "n": 1,
        "mean_probability": 0.2,
        "hit_rate": 1.0,
    }
    assert envelope["bins"] == bins
    assert envelope["conformal"]["status"] == "ineligible"


def test_calibrate_verify_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin verify calibration: per-claim certainty (0-100) rescaled to 0-1."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [("CL1", "true"), ("CL2", "false")])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["mode"] == "verify"
    assert envelope["item_kind"] == "claim"
    assert envelope["n_scored"] == 2
    assert envelope["n_gold"] == 2
    assert envelope["ece"] == 0.047
    assert envelope["brier"] == 0.0027
    filled = [b for b in envelope["bins"] if b["n"]]
    assert filled == [
        {
            "lower": 0.0,
            "upper": 0.1,
            "n": 1,
            "mean_probability": 0.069,
            "hit_rate": 0.0,
        },
        {
            "lower": 0.9,
            "upper": 1.0,
            "n": 1,
            "mean_probability": 0.975,
            "hit_rate": 1.0,
        },
    ]
    assert envelope["conformal"] == {
        "status": "ineligible",
        "reason": "n=2 < 20",
        "n": 2,
        "required": 20,
    }


def test_calibrate_rank_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pin rank calibration: gold labels attach to <candidate>--<criterion> cells."""
    topic = seed_rank_topic(tmp_path, capsys)
    write_gold(topic, [("alpha--quality", "TRUE"), ("beta--quality", "false")])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["mode"] == "rank"
    assert envelope["item_kind"] == "cell"
    assert envelope["n_scored"] == 4
    assert envelope["n_gold"] == 2
    assert envelope["ece"] == 0.2985
    assert envelope["brier"] == 0.1465
    filled = [b for b in envelope["bins"] if b["n"]]
    assert [(b["mean_probability"], b["hit_rate"]) for b in filled] == [
        (0.538, 0.0),
        (0.941, 1.0),
    ]


def test_calibrate_verify_conformal_eligible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """20 identically sourced claims clear the n-gate; every nonconformity
    score is equal, so the conformal quantile is that score."""
    run(
        capsys,
        [
            "new",
            "demo-c",
            "Demo Conformal",
            "--dest",
            str(tmp_path),
            "--mode",
            "verify",
        ],
    )
    data = tmp_path / "demo-c" / "data"
    ids = [f"CL{i:02d}" for i in range(1, 21)]
    append_rows(
        data / "claims.csv",
        [{"claim_id": c, "claim": f"Claim {c}", "notes": ""} for c in ids],
    )
    common = {
        "pass": "1",
        "date_captured": "2026-07-10",
        "quote": QUOTE,
        "source_type": "web",
    }
    append_rows(
        data / "evidence.csv",
        [
            {
                "evidence_id": f"E{i:03d}",
                "claim_id": c,
                "source_tier": "primary",
                "strength": "strong",
                "bearing": "supports",
                "source_url": f"https://h{i}.example/{i}",
                **common,
            }
            for i, c in enumerate(ids, start=1)
        ],
    )
    write_gold(tmp_path / "demo-c", [(c, "true") for c in ids])
    envelope = run(capsys, ["calibrate", "--dir", str(tmp_path / "demo-c")])
    assert envelope["n_gold"] == 20
    # Each claim scores 94.1 (one primary/strong source), so every binary
    # nonconformity score is 1 - 0.941 = 0.059 and the quantile equals it.
    assert envelope["conformal"] == {
        "status": "ok",
        "n": 20,
        "alpha": 0.1,
        "quantile": 0.059,
        "threshold_true": 0.941,
        "threshold_false": 0.059,
    }


def write_gold_actuals(topic: Path, rows: list[tuple[str, str]]) -> None:
    """Hand-author estimate's data/gold.csv (item_id, actual)."""
    with (topic / "data" / "gold.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "actual", "notes"])
        w.writerows([item_id, actual, ""] for item_id, actual in rows)


def test_calibrate_estimate_ineligible_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two labeled factors sit under the n-gate: an honest ineligible block."""
    topic = seed_estimate_topic(tmp_path, capsys)
    write_gold_actuals(topic, [("F2", "0.1"), ("F3", "20")])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["mode"] == "estimate"
    assert envelope["conformal"] == {
        "status": "ineligible",
        "reason": "n=2 < 20",
        "n": 2,
        "required": 20,
    }


def test_calibrate_estimate_point_factors_excluded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sigma-0 factor makes no uncertainty claim; its label is excluded
    from the calibration set, never silently counted."""
    topic = seed_estimate_topic(tmp_path, capsys)
    write_gold_actuals(topic, [("F1", "1000"), ("F2", "0.1")])  # F1 is low==high
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["conformal"]["n"] == 1
    assert envelope["conformal"]["reason"] == "n=1 < 20"


def test_calibrate_estimate_mixed_structure_is_ineligible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An additive term breaks the lognormal closed form, so conformal
    declines regardless of how many factors are labeled."""
    topic = seed_estimate_topic(tmp_path, capsys)
    append_rows(
        topic / "data" / "factors.csv",
        [
            {
                "factor_id": "F4",
                "name": "extra",
                "op": "add",
                "low": "1",
                "mid": "",
                "high": "2",
                "distribution": "lognormal",
                "notes": "",
            }
        ],
    )
    write_gold_actuals(topic, [("F2", "0.1")])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["conformal"]["status"] == "ineligible"
    assert envelope["conformal"]["reason"] == "mixed additive structure"


def test_calibrate_estimate_without_gold_names_actual_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    topic = seed_estimate_topic(tmp_path, capsys)
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "item_id,actual,notes" in envelope["error"]


def test_calibrate_find_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """find has no per-item probability, so calibrate refuses cleanly."""
    topic = seed_find_topic(tmp_path, capsys)
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "does not support 'find'" in envelope["error"]


def test_calibrate_without_gold_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    topic = seed_verify_topic(tmp_path, capsys)
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "gold.csv" in envelope["error"]
    assert "item_id,label,notes" in envelope["error"]


def test_calibrate_unknown_gold_id_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gold row naming no scored item is an error, never silently dropped."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [("CL1", "true"), ("CL9", "false")])
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "unknown claim id(s): CL9" in envelope["error"]


def test_calibrate_bad_label_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The label vocabulary is strict: a typo must never coerce to False."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [("CL1", "yes")])
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "label must be true or false" in envelope["error"]


def calibrate_error(topic: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """Run `calibrate` expecting a clean error envelope; return its message."""
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    return envelope["error"]


def calibrate_check_messages(
    topic: Path, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    """Run `calibrate` expecting the store-check gate to reject it; return the
    structured validation-error messages."""
    with (
        mock.patch.object(sys, "argv", ["research", "calibrate", "--dir", str(topic)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    return [e["message"] for e in envelope["errors"]]


def test_calibrate_empty_gold_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A header-only gold set fails loud with actionable guidance, not the
    engine's internal 'needs at least one pair' message."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [])
    error = calibrate_error(topic, capsys)
    assert "gold.csv has no rows" in error
    assert "item_id,label" in error
    assert "reliability" not in error  # the raw engine guard never surfaces


def test_calibrate_duplicate_gold_id_rejected_by_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repeated item_id is caught by the store's id-integrity check (shared
    with every *_id table), never a silently last-wins calibration set."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [("CL1", "true"), ("CL1", "false")])
    messages = calibrate_check_messages(topic, capsys)
    assert any("duplicate item_id 'CL1'" in m for m in messages)


def test_calibrate_blank_gold_id_rejected_by_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blank item_id can't name a scored item; the store check rejects it."""
    topic = seed_verify_topic(tmp_path, capsys)
    write_gold(topic, [("", "true")])
    messages = calibrate_check_messages(topic, capsys)
    assert any("empty item_id" in m for m in messages)


def test_calibrate_estimate_duplicate_gold_id_rejected_by_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same id-integrity check guards estimate's actuals gold too."""
    topic = seed_estimate_topic(tmp_path, capsys)
    write_gold_actuals(topic, [("F2", "0.1"), ("F2", "0.2")])
    messages = calibrate_check_messages(topic, capsys)
    assert any("duplicate item_id 'F2'" in m for m in messages)


def test_calibrate_estimate_empty_gold_stays_ineligible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty actuals file is legitimately 'not enough data', not an error:
    estimate reports ineligible (n=0), never the reliability path's hard error."""
    topic = seed_estimate_topic(tmp_path, capsys)
    write_gold_actuals(topic, [])
    envelope = run(capsys, ["calibrate", "--dir", str(topic)])
    assert envelope["conformal"]["status"] == "ineligible"
    assert envelope["conformal"]["reason"] == "n=0 < 20"


def set_sheet_id(topic: Path) -> None:
    config = topic / "research.toml"
    config.write_text(
        config.read_text().replace('sheet_id = ""', 'sheet_id = "sheet-test-id"'),
        encoding="utf-8",
    )


# Each mode's seeder and the store CSV its computed block joins onto.
SYNC_SEEDS = {
    "map": (seed_map_topic, "taxonomy.csv"),
    "verify": (seed_verify_topic, "claims.csv"),
    "rank": (seed_rank_topic, "candidates.csv"),
    "find": (seed_find_topic, "attributes.csv"),
    "estimate": (seed_estimate_topic, "factors.csv"),
}


@pytest.mark.parametrize("mode", sorted(SYNC_SEEDS))
def test_sync_dispatches_per_mode(
    mode: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_sync builds the mode's SheetExtras and hands it to sheets.sync
    (our own seam is stubbed; the Google stack is never touched)."""
    seeder, block_csv = SYNC_SEEDS[mode]
    topic = seeder(tmp_path, capsys)
    set_sheet_id(topic)
    with mock.patch.object(sheets, "sync", return_value={"status": "dry-run"}) as fake:
        envelope = run(capsys, ["sync", "--dir", str(topic), "--dry-run"])
    assert envelope["status"] == "dry-run"
    (_, extras), kwargs = fake.call_args
    assert kwargs == {"dry_run": True, "force": False}
    assert [b.csv_name for b in extras.blocks] == [block_csv]


def test_sync_without_sheet_id_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    topic = seed_verify_topic(tmp_path, capsys)
    with (
        mock.patch.object(
            sys, "argv", ["research", "sync", "--dir", str(topic), "--dry-run"]
        ),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "sheet_id" in envelope["error"]


def test_mode_registries_agree() -> None:
    """Schema and scorer registries cover exactly the same implemented modes."""
    assert set(score.MODE_SCORERS) == set(store.MODE_SCHEMAS)
    assert set(store.MODE_SCHEMAS) <= store.MODE_NAMES
    # Calibrators cover the probability modes plus estimate's conformal
    # check; find reports coverage rates, not probabilities, so it stays out.
    assert set(score.MODE_CALIBRATORS) == {"map", "verify", "rank", "estimate"}
    # Every mode mirrors to a Sheet.
    assert set(mirror.MODE_MIRRORS) == set(store.MODE_SCHEMAS)


def test_new_check_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    envelope = run(capsys, ["new", "demo", "Demo", "--dest", str(tmp_path)])
    assert envelope["ok"] is True
    assert envelope["status"] == "created"

    topic = str(tmp_path / "demo")
    envelope = run(capsys, ["check", "--dir", topic])
    assert envelope["ok"] is True
    assert envelope["status"] == "clean"

    envelope = run(capsys, ["status", "--dir", topic])
    assert envelope["ok"] is True
    assert envelope["categories"] == []

    # A fresh topic has no evidence, so verify checks nothing and hits no network.
    envelope = run(capsys, ["verify", "--dir", topic])
    assert envelope["ok"] is True
    assert envelope["checked"] == 0
    assert envelope["needs_attention"] == []


def test_unknown_mode_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # All five names are implemented; an unrecognized mode in research.toml
    # fails at load with a clean envelope rather than validating.
    run(capsys, ["new", "demo", "Demo", "--dest", str(tmp_path)])
    config = tmp_path / "demo" / "research.toml"
    config.write_text(
        config.read_text().replace('mode = "map"', 'mode = "bogus"'), encoding="utf-8"
    )
    with (
        mock.patch.object(
            sys, "argv", ["research", "check", "--dir", str(tmp_path / "demo")]
        ),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "unknown mode" in envelope["error"]


def test_check_errors_exit_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, ["new", "demo", "Demo", "--dest", str(tmp_path)])
    (tmp_path / "demo" / "data" / "sources.csv").unlink()
    with pytest.raises(SystemExit) as excinfo:
        run(capsys, ["check", "--dir", str(tmp_path / "demo")])
    assert excinfo.value.code == 1


def test_not_a_topic_dir_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # run_cli converts the FileNotFoundError into an error envelope.
    with (
        mock.patch.object(sys, "argv", ["research", "check", "--dir", str(tmp_path)]),
        pytest.raises(SystemExit),
    ):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    assert "research.toml" in envelope["error"]
