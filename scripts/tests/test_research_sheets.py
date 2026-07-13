"""Tests for the Sheet grid builders, per-mode mirrors, and digest (no network)."""

import csv
from pathlib import Path

import pytest

from vault_scripts.research import mirror, scaffold, sheets, store

TAXONOMY = """\
category_id,name,definition,boundary,examples,synthesis_notes,notes_coverage
C1,Alpha things,d,b,,,
C2,Beta things,d,b,,,
"""

EVIDENCE = """\
evidence_id,pass,date_captured,unit,category_id,finding_verbatim,detail_quote,source_type,source_url,published_date,notes
E001,1,2026-07-10,Alpha Corp,C1,f1,,posting,https://e.com/1,,
E002,1,2026-07-10,Beta Inc,C1,f2,,posting,https://e.com/2,,
E003,1,2026-07-10,Gamma LLC,C1-div,f3,,posting,https://e.com/3,,
"""

QUOTE = "alpha beta gamma delta"


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Append rows to a scaffolded CSV, reading the header for field order."""
    with path.open(newline="", encoding="utf-8") as f:
        fieldnames = next(csv.reader(f))
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)


@pytest.fixture
def topic(tmp_path: Path) -> store.Topic:
    created = scaffold.create_topic("demo", "Demo", tmp_path)
    (created.root / "data" / "taxonomy.csv").write_text(TAXONOMY)
    (created.root / "data" / "evidence.csv").write_text(EVIDENCE)
    (created.root / "data" / "individuals.csv").write_text(
        "individual_id,unit,name\nI001,Alpha Corp,A Person\n"
    )
    return store.load_topic(created.root)


def grids_for(topic: store.Topic) -> dict[str, list[list[object]]]:
    return sheets.build_grids(topic, mirror.MODE_MIRRORS["map"](topic))


def test_tab_set(topic: store.Topic) -> None:
    grids = grids_for(topic)
    assert set(grids) == {
        "Taxonomy",
        "Evidence",
        "Sources",
        "Individuals",
        "Confidence model",
    }


def test_taxonomy_computed_block(topic: store.Topic) -> None:
    grid = grids_for(topic)["Taxonomy"]
    header = grid[0]
    assert header[-6:] == [
        "supporting_units",
        "diverging_units",
        "evidence_count",
        "confidence",
        "tier",
        "primary_backed",
    ]
    c1 = grid[1]
    assert c1[0] == "C1"
    # 2 supporting units, 1 diverging: 0.20 - 0.10 = 0.10, Low. No primary
    # source (source_type "posting"), so primary_backed is "no".
    assert c1[-6:] == [2, 1, 2, 0.10, "Low", "no"]
    c2 = grid[2]
    assert c2[-6:] == [0, 0, 0, 0.0, "Low", "no"]


def test_passthrough_tabs(topic: store.Topic) -> None:
    grids = grids_for(topic)
    evidence = grids["Evidence"]
    assert evidence[0] == list(store.MODE_SCHEMAS["map"].core_columns["evidence.csv"])
    assert len(evidence) == 4  # header + 3 rows
    individuals = grids["Individuals"]
    assert individuals[0] == ["individual_id", "unit", "name"]
    assert individuals[1] == ["I001", "Alpha Corp", "A Person"]


def test_confidence_doc_tab(topic: store.Topic) -> None:
    doc = grids_for(topic)["Confidence model"]
    text = "\n".join(str(row[0]) for row in doc)
    assert "min(95%, 10% x supporting" in text
    assert "one-way mirror" in text
    assert topic.config.title in text


def test_map_percent_headers(topic: store.Topic) -> None:
    extras = mirror.MODE_MIRRORS["map"](topic)
    assert sheets.percent_headers_by_tab(extras) == {
        "Taxonomy": frozenset({"confidence"})
    }


@pytest.fixture
def verify_topic(tmp_path: Path) -> store.Topic:
    created = scaffold.create_topic("demo-v", "Demo Verify", tmp_path, mode="verify")
    data = created.root / "data"
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
    return store.load_topic(created.root)


def test_verify_grids(verify_topic: store.Topic) -> None:
    extras = mirror.MODE_MIRRORS["verify"](verify_topic)
    grids = sheets.build_grids(verify_topic, extras)
    claims = grids["Claims"]
    assert claims[0][-5:] == [
        "certainty",
        "band",
        "net_decibans",
        "n_sources",
        "capped",
    ]
    assert claims[1][0] == "CL1"
    assert claims[1][-5:] == [97.5, "established", 16.0, 2, "no"]
    assert claims[2][-5:] == [6.9, "refuted", -11.33, 2, "no"]
    doc = "\n".join(str(row[0]) for row in grids["Certainty model"])
    assert "decibans" in doc
    assert "one-way mirror" in doc
    assert "research calibrate" in doc
    # certainty is 0-100: it must never be percent-formatted.
    assert sheets.percent_headers_by_tab(extras) == {"Claims": frozenset()}


@pytest.fixture
def rank_topic(tmp_path: Path) -> store.Topic:
    created = scaffold.create_topic("demo-r", "Demo Rank", tmp_path, mode="rank")
    data = created.root / "data"
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
    return store.load_topic(created.root)


def test_rank_grids(rank_topic: store.Topic) -> None:
    extras = mirror.MODE_MIRRORS["rank"](rank_topic)
    grids = sheets.build_grids(rank_topic, extras)
    candidates = grids["Candidates"]
    assert candidates[0][-5:] == [
        "score",
        "blocked",
        "blocked_by",
        "least_resolved",
        "evidence_gaps",
    ]
    assert candidates[1][0] == "alpha"
    assert candidates[1][-5:] == [86.6, "no", "", "quality", "quality"]
    assert candidates[2][-5:] == [52.5, "no", "", "quality", "quality"]
    doc = "\n".join(str(row[0]) for row in grids["Fit model"])
    assert "blocker" in doc
    assert "one-way mirror" in doc


@pytest.fixture
def find_topic(tmp_path: Path) -> store.Topic:
    created = scaffold.create_topic("demo-f", "Demo Find", tmp_path, mode="find")
    data = created.root / "data"
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
    config = created.root / "research.toml"
    config.write_text(
        config
        .read_text()
        .replace('frame = "{{FRAME_DEFINITION}}"', 'frame = "top 4 orgs"')
        .replace('expected_count = ""', "expected_count = 4"),
        encoding="utf-8",
    )
    return store.load_topic(created.root)


def test_find_grids(find_topic: store.Topic) -> None:
    extras = mirror.MODE_MIRRORS["find"](find_topic)
    grids = sheets.build_grids(find_topic, extras)
    attributes = grids["Attributes"]
    assert attributes[0][-4:] == [
        "n_filled",
        "n_verified",
        "fill_rate",
        "verified_rate",
    ]
    assert attributes[1][0] == "role"
    assert attributes[1][-4:] == [2, 0, 1.0, 0.0]
    assert attributes[2][-4:] == [1, 0, 0.5, 0.0]
    # The roster stays a pure passthrough (wide attribute columns intact).
    assert grids["Entities"][0] == ["entity_id", "name", "in_frame", "role", "email"]
    doc = "\n".join(str(row[0]) for row in grids["Coverage model"])
    assert "top 4 orgs" in doc
    assert "recall 50.0%" in doc
    assert "one-way mirror" in doc
    assert sheets.percent_headers_by_tab(extras) == {
        "Attributes": frozenset({"fill_rate", "verified_rate"})
    }


@pytest.fixture
def estimate_topic(tmp_path: Path) -> store.Topic:
    created = scaffold.create_topic(
        "demo-e", "Demo Estimate", tmp_path, mode="estimate"
    )
    data = created.root / "data"
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
    return store.load_topic(created.root)


def test_estimate_grids(estimate_topic: store.Topic) -> None:
    extras = mirror.MODE_MIRRORS["estimate"](estimate_topic)
    grids = sheets.build_grids(estimate_topic, extras)
    factors = grids["Factors"]
    assert factors[0][-3:] == ["mu", "sigma", "variance_share"]
    assert factors[1][0] == "F1"
    assert factors[1][-3:] == [6.9078, 0.0, 0.0]
    assert factors[2][-3:] == [-2.3026, 0.4214, 0.5]
    assert factors[3][-3:] == [2.9957, 0.4214, 0.5]
    doc = "\n".join(str(row[0]) for row in grids["Estimate model"])
    assert "analytic-lognormal" in doc
    assert "2000" in doc
    assert "one-way mirror" in doc
    assert sheets.percent_headers_by_tab(extras) == {
        "Factors": frozenset({"variance_share"})
    }


def test_block_join_misses_leave_empty_cells(topic: store.Topic) -> None:
    """A store row whose id has no computed entry gets empty block cells."""
    extras = sheets.SheetExtras(
        blocks=(
            sheets.ComputedBlock(
                csv_name="taxonomy.csv",
                join_column="category_id",
                columns=("only", "c1"),
                rows={"C1": ("x", "y")},
            ),
        ),
        doc_title="Doc",
        doc_lines=("hello",),
    )
    grid = sheets.build_grids(topic, extras)["Taxonomy"]
    assert grid[1][-2:] == ["x", "y"]  # C1
    assert grid[2][-2:] == ["", ""]  # C2 has no computed entry


def test_digest_changes_on_csv_and_config_edits(topic: store.Topic) -> None:
    before = sheets.digest(topic)
    evidence = topic.root / "data" / "evidence.csv"
    evidence.write_text(evidence.read_text() + "\n")
    assert sheets.digest(topic) != before

    before = sheets.digest(topic)
    config = topic.root / "research.toml"
    config.write_text(config.read_text().replace("step = 0.10", "step = 0.05"))
    assert sheets.digest(topic) != before
