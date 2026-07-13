"""Tests for topic loading and CSV validation."""

import csv
from pathlib import Path

import pytest

from vault_scripts.research import store

MAP_COLUMNS = store.MODE_SCHEMAS["map"].core_columns

CONFIG = """\
[topic]
slug = "demo"
title = "Demo"
unit_noun = "vendor"
category_prefix = "C"
units = []

[confidence]
step = 0.10
cap = 0.95

[sheets]
sheet_id = ""
auth = "oauth"
"""

TAXONOMY_ROWS = [
    {
        "category_id": "C1",
        "name": "Alpha things",
        "definition": "d",
        "boundary": "b",
        "examples": "",
        "synthesis_notes": "",
        "notes_coverage": "",
    },
    {
        "category_id": "C2",
        "name": "Beta things",
        "definition": "d",
        "boundary": "b",
        "examples": "",
        "synthesis_notes": "",
        "notes_coverage": "",
    },
]


def evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_id": "E001",
        "pass": "1",
        "date_captured": "2026-07-10",
        "unit": "Alpha Corp",
        "category_id": "C1",
        "finding_verbatim": "a finding",
        "detail_quote": "",
        "source_type": "posting",
        "source_url": "https://example.com/1",
        "published_date": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def topic_dir(tmp_path: Path) -> Path:
    (tmp_path / "research.toml").write_text(CONFIG)
    data = tmp_path / "data"
    data.mkdir()
    write_csv(data / "taxonomy.csv", list(MAP_COLUMNS["taxonomy.csv"]), TAXONOMY_ROWS)
    write_csv(
        data / "evidence.csv",
        list(MAP_COLUMNS["evidence.csv"]),
        [
            evidence_row(),
            evidence_row(
                evidence_id="E002", unit="Beta Inc", source_url="https://example.com/2"
            ),
        ],
    )
    write_csv(
        data / "sources.csv",
        list(MAP_COLUMNS["sources.csv"]),
        [
            {
                "source_id": "S001",
                "unit": "Alpha Corp",
                "title": "t",
                "source_type": "posting",
                "pass": "1",
                "url": "https://example.com/1",
            },
        ],
    )
    return tmp_path


def check_errors(root: Path) -> tuple[list[str], list[str]]:
    topic = store.load_topic(root)
    errors, warnings = store.check(topic)
    return [e.message for e in errors], [w.message for w in warnings]


def append_evidence(root: Path, rows: list[dict[str, str]]) -> None:
    path = root / "data" / "evidence.csv"
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(MAP_COLUMNS["evidence.csv"]))
        writer.writerows(rows)


def test_happy_path(topic_dir: Path) -> None:
    errors, warnings = check_errors(topic_dir)
    assert errors == []
    assert warnings == []
    topic = store.load_topic(topic_dir)
    assert topic.taxonomy_ids == ["C1", "C2"]
    assert topic.evidence_pairs() == [("Alpha Corp", "C1"), ("Beta Inc", "C1")]
    assert store.counts(topic)["distinct_units"] == 2
    assert store.counts(topic)["max_pass"] == 1


def test_missing_config(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        store.load_topic(tmp_path)


def set_mode(root: Path, mode: str) -> None:
    """Insert a mode line into the fixture config's [topic] table."""
    path = root / "research.toml"
    path.write_text(
        path.read_text().replace('slug = "demo"', f'slug = "demo"\nmode = "{mode}"')
    )


def test_mode_defaults_to_map(topic_dir: Path) -> None:
    # The fixture CONFIG has no mode line, as every pre-v0.3 topic.
    assert store.load_config(topic_dir).mode == "map"


def test_mode_map_accepted_explicitly(topic_dir: Path) -> None:
    set_mode(topic_dir, "map")
    assert store.load_config(topic_dir).mode == "map"


def test_all_modes_accepted(topic_dir: Path) -> None:
    # All five modes are implemented from v0.3.2; each loads by name.
    config = topic_dir / "research.toml"
    for mode in ("map", "verify", "rank", "find", "estimate"):
        config.write_text(
            CONFIG.replace('slug = "demo"', f'slug = "demo"\nmode = "{mode}"')
        )
        assert store.load_config(topic_dir).mode == mode


def test_unknown_mode_rejected(topic_dir: Path) -> None:
    set_mode(topic_dir, "banana")
    with pytest.raises(ValueError, match="unknown mode"):
        store.load_config(topic_dir)


def test_missing_core_file(topic_dir: Path) -> None:
    (topic_dir / "data" / "sources.csv").unlink()
    errors, _ = check_errors(topic_dir)
    assert any("required file missing" in e for e in errors)


def test_missing_required_column(topic_dir: Path) -> None:
    write_csv(topic_dir / "data" / "sources.csv", ["source_id", "unit"], [])
    errors, _ = check_errors(topic_dir)
    assert any("missing required columns" in e for e in errors)


def test_extra_columns_ok(topic_dir: Path) -> None:
    columns = [*MAP_COLUMNS["evidence.csv"], "kpis"]
    write_csv(
        topic_dir / "data" / "evidence.csv", columns, [evidence_row() | {"kpis": "x"}]
    )
    errors, _ = check_errors(topic_dir)
    assert errors == []
    topic = store.load_topic(topic_dir)
    assert "kpis" in topic.tables["evidence.csv"].columns


def test_duplicate_ids(topic_dir: Path) -> None:
    append_evidence(topic_dir, [evidence_row()])  # E001 again
    errors, _ = check_errors(topic_dir)
    assert any("duplicate evidence_id 'E001'" in e for e in errors)


def test_void_id_may_repeat(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="VOID", source_url="", finding_verbatim="", unit=""
            ),
            evidence_row(
                evidence_id="VOID", source_url="", finding_verbatim="", unit=""
            ),
        ],
    )
    # VOID appears in category_id, not evidence_id; retired rows keep unique ids.
    # This test covers the id checker's VOID carve-out generically.
    errors, _ = check_errors(topic_dir)
    assert not any("duplicate evidence_id 'VOID'" in e for e in errors)


def test_unknown_category_id(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003", category_id="C9", source_url="https://e.com/3"
            )
        ],
    )
    errors, _ = check_errors(topic_dir)
    assert any("unknown category_id 'C9'" in e for e in errors)


def test_div_ref_void_category_ids_accepted(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003", category_id="C1-div", source_url="https://e.com/3"
            ),
            evidence_row(
                evidence_id="E004", category_id="C2-ref", source_url="https://e.com/4"
            ),
            evidence_row(
                evidence_id="E005",
                category_id="VOID",
                source_url="",
                finding_verbatim="",
                unit="",
            ),
        ],
    )
    errors, _ = check_errors(topic_dir)
    assert errors == []


def test_missing_source_url(topic_dir: Path) -> None:
    append_evidence(topic_dir, [evidence_row(evidence_id="E003", source_url="")])
    errors, _ = check_errors(topic_dir)
    assert any("empty source_url" in e for e in errors)


def test_missing_finding(topic_dir: Path) -> None:
    append_evidence(topic_dir, [evidence_row(evidence_id="E003", finding_verbatim="")])
    errors, _ = check_errors(topic_dir)
    assert any("empty finding_verbatim" in e for e in errors)


def test_bad_pass_and_date(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [evidence_row(evidence_id="E003", **{"pass": "zero"}, date_captured="July 4")],
    )
    errors, _ = check_errors(topic_dir)
    assert any("pass must be a positive integer" in e for e in errors)
    assert any("date_captured must be YYYY-MM-DD" in e for e in errors)


def test_units_enforced_when_listed(topic_dir: Path) -> None:
    config = CONFIG.replace("units = []", 'units = ["Alpha Corp", "Beta Inc"]')
    (topic_dir / "research.toml").write_text(config)
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003", unit="alpha corp", source_url="https://e.com/3"
            )
        ],
    )
    errors, _ = check_errors(topic_dir)
    assert any("not in research.toml units" in e for e in errors)


def test_unit_collision_warning_when_unlisted(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003", unit="alpha corp ", source_url="https://e.com/3"
            )
        ],
    )
    _, warnings = check_errors(topic_dir)
    assert any("differ only by case/whitespace" in w for w in warnings)


def test_duplicate_source_url_warning(topic_dir: Path) -> None:
    path = topic_dir / "data" / "sources.csv"
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(MAP_COLUMNS["sources.csv"]))
        writer.writerow({
            "source_id": "S002",
            "unit": "Beta Inc",
            "title": "t2",
            "source_type": "posting",
            "pass": "1",
            "url": "https://example.com/1",
        })
    _, warnings = check_errors(topic_dir)
    assert any("duplicate url" in w for w in warnings)


def test_unit_near_miss_warning_when_unlisted(topic_dir: Path) -> None:
    # "Beta Inc" is already in the fixture; "Beta Inc." differs by a period, so
    # the casefold/strip collision check misses it but the fuzzy pass catches it.
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003", unit="Beta Inc.", source_url="https://e.com/3"
            )
        ],
    )
    _, warnings = check_errors(topic_dir)
    assert any("near-duplicates" in w for w in warnings)


def test_no_near_miss_for_distinct_units(topic_dir: Path) -> None:
    _, warnings = check_errors(topic_dir)
    assert not any("near-duplicates" in w for w in warnings)


def test_contested_category_warning(topic_dir: Path) -> None:
    # C1 has 2 supporting units (Alpha Corp, Beta Inc); add 2 diverging units so
    # diverging >= supporting and the category is flagged as contested.
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003",
                unit="Gamma LLC",
                category_id="C1-div",
                source_url="https://e.com/3",
            ),
            evidence_row(
                evidence_id="E004",
                unit="Delta Co",
                category_id="C1-div",
                source_url="https://e.com/4",
            ),
        ],
    )
    _, warnings = check_errors(topic_dir)
    assert any("C1" in w and "contested" in w for w in warnings)


def test_div_only_category_warning(topic_dir: Path) -> None:
    # C2 has no supporting evidence; a lone diverging row means its only
    # evidence contradicts the definition.
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003",
                unit="Gamma LLC",
                category_id="C2-div",
                source_url="https://e.com/3",
            )
        ],
    )
    _, warnings = check_errors(topic_dir)
    assert any("C2" in w and "only divergent evidence" in w for w in warnings)


def test_empty_category_is_not_warned(topic_dir: Path) -> None:
    # C2 is empty in the fixture; empty categories are normal early and must not
    # warn, or a fresh topic would be noisy.
    _, warnings = check_errors(topic_dir)
    assert not any("C2" in w for w in warnings)


def test_primary_backed_empty_without_primary_source(topic_dir: Path) -> None:
    # Fixture evidence uses source_type "posting", so nothing is primary-backed.
    topic = store.load_topic(topic_dir)
    assert store.primary_backed_categories(topic) == set()


def test_primary_backed_from_source_type(topic_dir: Path) -> None:
    append_evidence(
        topic_dir,
        [
            evidence_row(
                evidence_id="E003",
                unit="Gamma LLC",
                source_type="Primary source",
                source_url="https://e.com/3",
            )
        ],
    )
    topic = store.load_topic(topic_dir)
    assert store.primary_backed_categories(topic) == {"C1"}


def test_primary_backed_via_validated_individual(topic_dir: Path) -> None:
    # Alpha Corp supports C1; a validated individual for it clears the bar.
    write_csv(
        topic_dir / "data" / "individuals.csv",
        ["individual_id", "unit", "validation_status"],
        [
            {
                "individual_id": "I001",
                "unit": "Alpha Corp",
                "validation_status": "validated",
            }
        ],
    )
    topic = store.load_topic(topic_dir)
    assert "C1" in store.primary_backed_categories(topic)


def test_unvalidated_individual_does_not_back(topic_dir: Path) -> None:
    write_csv(
        topic_dir / "data" / "individuals.csv",
        ["individual_id", "unit", "validation_status"],
        [
            {
                "individual_id": "I001",
                "unit": "Alpha Corp",
                "validation_status": "pending",
            }
        ],
    )
    topic = store.load_topic(topic_dir)
    assert store.primary_backed_categories(topic) == set()


def test_extra_csv_loaded_and_id_checked(topic_dir: Path) -> None:
    write_csv(
        topic_dir / "data" / "individuals.csv",
        ["individual_id", "unit", "name"],
        [
            {"individual_id": "I001", "unit": "Alpha Corp", "name": "A"},
            {"individual_id": "I001", "unit": "Beta Inc", "name": "B"},
        ],
    )
    topic = store.load_topic(topic_dir)
    assert "individuals.csv" in topic.tables
    errors, _ = store.check(topic)
    assert any("duplicate individual_id" in e.message for e in errors)


# --- verify / rank schemas ---

VERIFY_CONFIG = """\
[topic]
slug = "demo-v"
title = "Demo Verify"
mode = "verify"
"""

RANK_CONFIG = """\
[topic]
slug = "demo-r"
title = "Demo Rank"
mode = "rank"
"""


def verify_evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_id": "E001",
        "pass": "1",
        "date_captured": "2026-07-10",
        "claim_id": "CL1",
        "source_tier": "primary",
        "strength": "strong",
        "bearing": "supports",
        "quote": "a quote",
        "source_type": "web",
        "source_url": "https://example.com/1",
        "published_date": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def make_verify_topic(tmp_path: Path, evidence: list[dict[str, str]]) -> Path:
    (tmp_path / "research.toml").write_text(VERIFY_CONFIG)
    data = tmp_path / "data"
    data.mkdir()
    cols = store.MODE_SCHEMAS["verify"].core_columns
    write_csv(
        data / "claims.csv",
        list(cols["claims.csv"]),
        [{"claim_id": "CL1", "claim": "First", "notes": ""}],
    )
    write_csv(data / "evidence.csv", list(cols["evidence.csv"]), evidence)
    return tmp_path


def test_verify_happy_path(tmp_path: Path) -> None:
    root = make_verify_topic(tmp_path, [verify_evidence_row()])
    errors, _ = check_errors(root)
    assert errors == []


def test_verify_rejects_unknown_claim_and_vocab(tmp_path: Path) -> None:
    root = make_verify_topic(
        tmp_path,
        [
            verify_evidence_row(evidence_id="E001", claim_id="NOPE"),
            verify_evidence_row(evidence_id="E002", source_tier="gold"),
            verify_evidence_row(evidence_id="E003", bearing="maybe"),
        ],
    )
    msgs, _ = check_errors(root)
    assert any("unknown claim_id 'NOPE'" in m for m in msgs)
    assert any("unknown source_tier 'gold'" in m for m in msgs)
    assert any("unknown bearing 'maybe'" in m for m in msgs)


def test_verify_void_row_skips_checks(tmp_path: Path) -> None:
    root = make_verify_topic(
        tmp_path, [verify_evidence_row(claim_id="VOID", source_url="", quote="")]
    )
    errors, _ = check_errors(root)
    assert errors == []


def rank_evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_id": "R001",
        "pass": "1",
        "date_captured": "2026-07-10",
        "cell_id": "alpha--quality",
        "source_tier": "primary",
        "strength": "strong",
        "bearing": "supports",
        "quote": "a quote",
        "source_type": "web",
        "source_url": "https://example.com/1",
        "published_date": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def make_rank_topic(
    tmp_path: Path, criteria: list[dict[str, str]], evidence: list[dict[str, str]]
) -> Path:
    (tmp_path / "research.toml").write_text(RANK_CONFIG)
    data = tmp_path / "data"
    data.mkdir()
    cols = store.MODE_SCHEMAS["rank"].core_columns
    write_csv(
        data / "candidates.csv",
        list(cols["candidates.csv"]),
        [{"candidate_id": "alpha", "name": "Alpha"}],
    )
    write_csv(data / "criteria.csv", list(cols["criteria.csv"]), criteria)
    write_csv(data / "evidence.csv", list(cols["evidence.csv"]), evidence)
    return tmp_path


GOOD_CRITERIA = [
    {"criterion_id": "quality", "text": "Q", "weight": "2", "tier": "must"},
]


def test_rank_happy_path(tmp_path: Path) -> None:
    root = make_rank_topic(tmp_path, GOOD_CRITERIA, [rank_evidence_row()])
    errors, _ = check_errors(root)
    assert errors == []


def test_rank_rejects_bad_cell_and_criteria(tmp_path: Path) -> None:
    root = make_rank_topic(
        tmp_path,
        [
            {"criterion_id": "quality", "text": "Q", "weight": "0", "tier": "must"},
            {"criterion_id": "price", "text": "P", "weight": "1", "tier": "banana"},
        ],
        [
            rank_evidence_row(evidence_id="R001", cell_id="alpha--quality"),
            rank_evidence_row(evidence_id="R002", cell_id="ghost--quality"),
            rank_evidence_row(evidence_id="R003", cell_id="loose"),
        ],
    )
    msgs, _ = check_errors(root)
    assert any("weight must be positive" in m for m in msgs)
    assert any("unknown tier 'banana'" in m for m in msgs)
    assert any("cell_id 'ghost--quality'" in m for m in msgs)
    assert any("cell_id 'loose'" in m for m in msgs)


FIND_CONFIG = """\
[topic]
slug = "demo-f"
title = "Demo Find"
mode = "find"

[find]
frame = "top 4 orgs"
expected_count = 4
"""

ESTIMATE_CONFIG = """\
[topic]
slug = "demo-e"
title = "Demo Estimate"
mode = "estimate"
"""


def find_evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_id": "F001",
        "pass": "1",
        "date_captured": "2026-07-10",
        "cell_id": "E1--role",
        "quote": "a quote",
        "source_type": "web",
        "source_url": "https://example.com/1",
        "published_date": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def make_find_topic(tmp_path: Path, evidence: list[dict[str, str]]) -> Path:
    (tmp_path / "research.toml").write_text(FIND_CONFIG)
    data = tmp_path / "data"
    data.mkdir()
    cols = store.MODE_SCHEMAS["find"].core_columns
    # entities.csv is wide: core columns plus one column per attribute.
    write_csv(
        data / "entities.csv",
        [*cols["entities.csv"], "role"],
        [
            {"entity_id": "E1", "name": "Ada", "in_frame": "yes", "role": "CTO"},
            {"entity_id": "E2", "name": "Ben", "in_frame": "no", "role": ""},
        ],
    )
    write_csv(
        data / "attributes.csv",
        list(cols["attributes.csv"]),
        [{"attribute_id": "role", "name": "Role", "required": "yes"}],
    )
    write_csv(data / "evidence.csv", list(cols["evidence.csv"]), evidence)
    return tmp_path


def test_find_happy_path(tmp_path: Path) -> None:
    root = make_find_topic(tmp_path, [find_evidence_row()])
    errors, _ = check_errors(root)
    assert errors == []
    topic = store.load_topic(root)
    assert topic.config.find_expected_count == 4
    assert [e.entity_id for e in topic.find_entities()] == ["E1", "E2"]


def test_find_rejects_bad_cells(tmp_path: Path) -> None:
    root = make_find_topic(
        tmp_path,
        [
            find_evidence_row(evidence_id="F001", cell_id="ghost--role"),
            find_evidence_row(evidence_id="F002", cell_id="E1--nope"),
            find_evidence_row(evidence_id="F003", cell_id="loose"),
            find_evidence_row(evidence_id="F004", source_url="", quote=""),
        ],
    )
    msgs, _ = check_errors(root)
    assert any("cell_id 'ghost--role'" in m for m in msgs)
    assert any("cell_id 'E1--nope'" in m for m in msgs)
    assert any("cell_id 'loose'" in m for m in msgs)
    assert any("empty source_url" in m for m in msgs)
    assert any("empty quote" in m for m in msgs)


def test_find_void_row_skips_checks(tmp_path: Path) -> None:
    root = make_find_topic(
        tmp_path, [find_evidence_row(cell_id="VOID", source_url="", quote="")]
    )
    errors, _ = check_errors(root)
    assert errors == []


def test_find_rejects_attribute_without_roster_column(tmp_path: Path) -> None:
    # An attribute with no matching entities.csv column would silently read as
    # empty for every entity (0% fill on data that may exist under a mis-named
    # column), so the schema check rejects the mismatch up front.
    root = make_find_topic(tmp_path, [find_evidence_row()])
    cols = store.MODE_SCHEMAS["find"].core_columns
    write_csv(
        root / "data" / "attributes.csv",
        list(cols["attributes.csv"]),
        [
            {"attribute_id": "role", "name": "Role", "required": "yes"},
            {"attribute_id": "email", "name": "Email", "required": "no"},
        ],
    )
    msgs, _ = check_errors(root)
    assert any("attribute 'email' has no matching column" in m for m in msgs)


def estimate_evidence_row(**overrides: str) -> dict[str, str]:
    row = {
        "evidence_id": "V001",
        "pass": "1",
        "date_captured": "2026-07-10",
        "factor_id": "F1",
        "quote": "a quote",
        "source_type": "web",
        "source_url": "https://example.com/1",
        "published_date": "",
        "notes": "",
    }
    row.update(overrides)
    return row


def factor_row(**overrides: str) -> dict[str, str]:
    row = {
        "factor_id": "F1",
        "name": "orgs",
        "op": "mul",
        "low": "100",
        "mid": "",
        "high": "400",
        "distribution": "lognormal",
        "notes": "",
    }
    row.update(overrides)
    return row


def make_estimate_topic(
    tmp_path: Path, factors: list[dict[str, str]], evidence: list[dict[str, str]]
) -> Path:
    (tmp_path / "research.toml").write_text(ESTIMATE_CONFIG)
    data = tmp_path / "data"
    data.mkdir()
    cols = store.MODE_SCHEMAS["estimate"].core_columns
    write_csv(data / "factors.csv", list(cols["factors.csv"]), factors)
    write_csv(data / "evidence.csv", list(cols["evidence.csv"]), evidence)
    return tmp_path


def test_estimate_happy_path(tmp_path: Path) -> None:
    root = make_estimate_topic(tmp_path, [factor_row()], [estimate_evidence_row()])
    errors, _ = check_errors(root)
    assert errors == []
    assert store.load_topic(root).estimate_factors()[0].op == "mul"


def test_estimate_rejects_bad_factors_and_evidence(tmp_path: Path) -> None:
    root = make_estimate_topic(
        tmp_path,
        [
            factor_row(factor_id="F1", op="times"),
            factor_row(factor_id="F2", low="400", high="100"),
            factor_row(factor_id="F3", low="0", high="10"),
            factor_row(factor_id="F4", distribution="normal"),
        ],
        [estimate_evidence_row(factor_id="GHOST")],
    )
    msgs, _ = check_errors(root)
    assert any("unknown op 'times'" in m for m in msgs)
    assert any("exceeds high" in m for m in msgs)
    assert any("must be positive" in m for m in msgs)
    assert any("unknown distribution 'normal'" in m for m in msgs)
    assert any("unknown factor_id 'GHOST'" in m for m in msgs)
