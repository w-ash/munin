"""Tests for `research render`: the gate and the projected vault note.

Render is the enforcement point the supplement-timing incident bypassed: the
vault note is a projection of the verified store, and the gate refuses to write
it while any cited row is neither verified nor waived.
"""

import csv
import json
from pathlib import Path
import sys
from unittest import mock

import pytest

from vault_scripts.research import cli, render, store, verify

QUOTE = "alpha beta gamma delta epsilon zeta"


def run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, object]:
    """Run a subcommand expecting a success envelope on stdout."""
    with mock.patch.object(sys, "argv", ["research", *argv]):
        cli.main()
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is True
    return envelope


def run_error(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, object]:
    """Run a subcommand expecting a non-zero exit and an error envelope."""
    with (
        mock.patch.object(sys, "argv", ["research", *argv]),
        pytest.raises(SystemExit) as excinfo,
    ):
        cli.main()
    assert excinfo.value.code == 1
    envelope = json.loads(capsys.readouterr().out.strip())
    assert envelope["ok"] is False
    return envelope


def append_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open(newline="", encoding="utf-8") as f:
        fieldnames = next(csv.reader(f))
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fieldnames).writerows(rows)


def seed_find(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, note: str = "Notes/Demo.md"
) -> Path:
    """Scaffold a find topic (two in-frame entities, one out-of-frame) with a
    vault_note set, but no citations yet."""
    run(capsys, ["new", "demo-f", "Demo Find", "--dest", str(tmp_path), "--mode", "find"])
    root = tmp_path / "demo-f"
    data = root / "data"
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
    common = {"pass": "1", "date_captured": "2026-07-10", "quote": QUOTE, "source_type": "web"}
    append_rows(
        data / "evidence.csv",
        [
            {"evidence_id": "F1", "cell_id": "E001--role", "source_url": "https://a.com/1", **common},
            {"evidence_id": "F2", "cell_id": "E001--email", "source_url": "https://a.com/2", **common},
            {"evidence_id": "F3", "cell_id": "E002--role", "source_url": "https://b.com/3", **common},
        ],
    )
    config = root / "research.toml"
    config.write_text(
        config.read_text()
        .replace('frame = "{{FRAME_DEFINITION}}"', 'frame = "demo people"')
        .replace('vault_note = ""', f'vault_note = "{note}"'),
        encoding="utf-8",
    )
    return root


def do_verify(
    topic: Path, capsys: pytest.CaptureFixture[str], *, page_has_quote: bool
) -> None:
    """Run `research verify`, mocking the fetch so every quote is present (or
    absent) without touching the network."""
    text = f"<p>{QUOTE}</p>" if page_has_quote else "<p>nothing relevant here</p>"
    page = verify.FetchResult(200, "text/html", text)
    with mock.patch.object(verify, "fetch_url", return_value=page):
        run(capsys, ["verify", "--dir", str(topic), "--no-cache"])


def set_vault_note(topic: Path, note: str) -> None:
    """Point the topic's research.toml at a vault note path."""
    config = topic / "research.toml"
    config.write_text(
        config.read_text().replace('vault_note = ""', f'vault_note = "{note}"'),
        encoding="utf-8",
    )


def write_waivers(topic: Path, rows: list[tuple[str, str]]) -> None:
    with (topic / "data" / render.WAIVERS_CSV).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(render.WAIVER_COLUMNS)
        w.writerows([eid, reason, "2026-07-14"] for eid, reason in rows)


def render_args(topic: Path, tmp_path: Path, *extra: str) -> list[str]:
    return ["render", "--dir", str(topic), "--vault-root", str(tmp_path / "vault"), *extra]


# --- the gate ---


def test_render_blocks_empty_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fresh topic has no cited evidence; render refuses to write a note."""
    run(capsys, ["new", "empty", "Empty", "--dest", str(tmp_path), "--mode", "find"])
    config = tmp_path / "empty" / "research.toml"
    config.write_text(
        config.read_text().replace('vault_note = ""', 'vault_note = "N.md"'),
        encoding="utf-8",
    )
    envelope = run_error(capsys, render_args(tmp_path / "empty", tmp_path))
    assert "no cited evidence" in envelope["error"]
    assert not (tmp_path / "vault").exists()


def test_render_blocks_unverified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cited rows that verify never checked block the render as 'unchecked'."""
    topic = seed_find(tmp_path, capsys)
    envelope = run_error(capsys, render_args(topic, tmp_path))
    assert "neither verified nor waived" in envelope["error"]
    assert {b["evidence_id"] for b in envelope["blocking"]} == {"F1", "F2", "F3"}
    assert all(b["status"] == "unchecked" for b in envelope["blocking"])
    assert not (tmp_path / "vault").exists()


def test_render_blocks_quote_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A quote absent from the page blocks the render until fixed or waived."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=False)
    envelope = run_error(capsys, render_args(topic, tmp_path))
    assert {b["status"] for b in envelope["blocking"]} == {"quote_missing"}


def test_render_writes_when_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With every cited row verified, render writes the note as a projection."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["status"] == "rendered"
    assert envelope["action"] == "created"
    assert envelope["gate"]["n_verified"] == 3
    note = Path(str(envelope["note"]))
    assert note == tmp_path / "vault" / "Notes" / "Demo.md"
    text = note.read_text(encoding="utf-8")
    assert render.EVIDENCE_START in text
    assert render.EVIDENCE_END in text
    assert "## Verification status" in text
    assert "**3 verified**" in text
    assert "### Ada" in text
    assert "- **Role:** CTO" in text
    assert "✓ verified" in text
    # Ben's empty, unsourced email cell renders as an honest blank, not a guess.
    assert "- **Email:** (no value recorded)" in text
    assert "(no verbatim quote captured for this cell)" in text
    # Out-of-frame entities never reach the note.
    assert "### Zed" not in text


def test_render_waiver_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recorded waiver clears the gate and shows as ◐ waived, not hidden."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=False)  # all quote_missing
    write_waivers(topic, [("F1", "page paginated; quote confirmed by hand"), ("F2", "ok"), ("F3", "ok")])
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["gate"]["n_waived"] == 3
    text = Path(str(envelope["note"])).read_text(encoding="utf-8")
    assert "◐ waived: page paginated; quote confirmed by hand" in text
    assert "**0 verified, 3 waived**" in text


def test_render_preserves_narrative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A re-render rewrites only the evidence block; the narrative is kept."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    note = Path(str(run(capsys, render_args(topic, tmp_path))["note"]))
    edited = note.read_text(encoding="utf-8").replace(
        "> Summary and narrative go here.", "> My hand-written summary of the findings."
    )
    note.write_text(edited, encoding="utf-8")
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["action"] == "unchanged"  # store didn't change, block didn't either
    text = note.read_text(encoding="utf-8")
    assert "> My hand-written summary of the findings." in text
    assert "### Ada" in text


def test_pick_prefers_newest_superseding_row() -> None:
    """The store supersedes a changed source with a newer-dated row, so the
    newer row is the one projected: append order must not pin a cell to the
    source it retired."""
    old = {"evidence_id": "E1", "date_captured": "2026-07-12", "pass": "1"}
    new = {"evidence_id": "E2", "date_captured": "2026-07-17", "pass": "2"}
    citations = {"E1": verify.VERIFIED, "E2": verify.VERIFIED}
    assert render._pick([old, new], citations, {}) is new


def test_pick_keeps_verified_over_newer_unverified() -> None:
    """Recency orders within a tier; it never promotes an unverified row over a
    verified one."""
    old = {"evidence_id": "E1", "date_captured": "2026-07-12", "pass": "1"}
    new = {"evidence_id": "E2", "date_captured": "2026-07-17", "pass": "2"}
    assert render._pick([old, new], {"E1": verify.VERIFIED}, {}) is old


def test_pick_undated_rows_keep_append_order() -> None:
    """With no dates to compare, the file stays the tiebreaker."""
    first = {"evidence_id": "E1", "date_captured": "", "pass": ""}
    second = {"evidence_id": "E2", "date_captured": "", "pass": ""}
    citations = {"E1": verify.VERIFIED, "E2": verify.VERIFIED}
    assert render._pick([first, second], citations, {}) is first


def test_render_refuses_note_without_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An existing note with no evidence markers is refused, never clobbered."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    note = tmp_path / "vault" / "Notes" / "Demo.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Hand-written note\n\nPrecious prose.\n", encoding="utf-8")
    envelope = run_error(capsys, render_args(topic, tmp_path))
    assert "no evidence markers" in envelope["error"]
    assert note.read_text(encoding="utf-8") == "# Hand-written note\n\nPrecious prose.\n"


def test_render_dry_run_never_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--dry-run reports the verdict and writes nothing, even when it would pass."""
    topic = seed_find(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run(capsys, render_args(topic, tmp_path, "--dry-run"))
    assert envelope["status"] == "dry-run"
    assert envelope["would_pass"] is True
    assert not (tmp_path / "vault").exists()


def test_render_verify_flag_chains_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--verify runs a fresh citation check first, so a store with no citations
    can go straight to a written note in one command."""
    topic = seed_find(tmp_path, capsys)
    page = verify.FetchResult(200, "text/html", f"<p>{QUOTE}</p>")
    with mock.patch.object(verify, "fetch_url", return_value=page):
        envelope = run(capsys, render_args(topic, tmp_path, "--verify", "--no-cache"))
    assert envelope["status"] == "rendered"
    assert envelope["gate"]["n_verified"] == 3
    assert (topic / "data" / "citations.csv").exists()


# --- the other modes (map / rank / estimate) ---


def seed_map(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold a map topic (two categories, with supporting, diverging, and
    reference rows) with a vault_note set, but no citations yet."""
    run(capsys, ["new", "demo-m", "Demo Map", "--dest", str(tmp_path), "--mode", "map"])
    root = tmp_path / "demo-m"
    data = root / "data"
    append_rows(
        data / "taxonomy.csv",
        [
            {"category_id": "C1", "name": "Alpha things", "definition": "d", "boundary": "b"},
            {"category_id": "C2", "name": "Beta things", "definition": "d", "boundary": "b"},
        ],
    )
    common = {"pass": "1", "date_captured": "2026-07-10", "finding_verbatim": QUOTE}
    append_rows(
        data / "evidence.csv",
        [
            {"evidence_id": "M1", "unit": "Alpha Corp", "category_id": "C1",
             "source_type": "Primary source", "source_url": "https://a.com/1", **common},
            {"evidence_id": "M2", "unit": "Beta Inc", "category_id": "C1",
             "source_type": "posting", "source_url": "https://a.com/2",
             "detail_quote": "the deeper detail behind the finding", **common},
            {"evidence_id": "M3", "unit": "Gamma LLC", "category_id": "C2",
             "source_type": "posting", "source_url": "https://b.com/3", **common},
            {"evidence_id": "M4", "unit": "Delta Co", "category_id": "C2-div",
             "source_type": "posting", "source_url": "https://b.com/4", **common},
            {"evidence_id": "M5", "unit": "Epsilon AG", "category_id": "C1-ref",
             "source_type": "posting", "source_url": "https://a.com/5", **common},
        ],
    )
    set_vault_note(root, "Notes/Map.md")
    return root


def seed_rank(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold a rank topic (two candidates, two criteria; beta--price has no
    evidence) with a vault_note set, but no citations yet."""
    run(capsys, ["new", "demo-r", "Demo Rank", "--dest", str(tmp_path), "--mode", "rank"])
    root = tmp_path / "demo-r"
    data = root / "data"
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
            {"criterion_id": "quality", "text": "Quality", "weight": "2", "tier": "must"},
            {"criterion_id": "price", "text": "Price", "weight": "1", "tier": "should"},
        ],
    )
    common = {"pass": "1", "date_captured": "2026-07-10", "quote": QUOTE, "source_type": "web"}
    append_rows(
        data / "evidence.csv",
        [
            {"evidence_id": "R1", "cell_id": "alpha--quality", "source_tier": "primary",
             "strength": "strong", "bearing": "supports",
             "source_url": "https://a.org/1", **common},
            {"evidence_id": "R2", "cell_id": "alpha--price", "source_tier": "secondary",
             "strength": "moderate", "bearing": "supports",
             "source_url": "https://b.org/2", **common},
            {"evidence_id": "R3", "cell_id": "beta--quality", "source_tier": "weak",
             "strength": "weak", "bearing": "supports",
             "source_url": "https://x.org/9", **common},
        ],
    )
    set_vault_note(root, "Notes/Rank.md")
    return root


def seed_estimate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """Scaffold a pure-product estimate topic (one sourced factor, two without
    evidence) with a vault_note set, but no citations yet."""
    run(
        capsys,
        ["new", "demo-e", "Demo Estimate", "--dest", str(tmp_path), "--mode", "estimate"],
    )
    root = tmp_path / "demo-e"
    data = root / "data"
    factor = {"distribution": "lognormal", "notes": ""}
    append_rows(
        data / "factors.csv",
        [
            {"factor_id": "F1", "name": "orgs", "op": "mul",
             "low": "1000", "mid": "", "high": "1000", **factor},
            {"factor_id": "F2", "name": "rate", "op": "mul",
             "low": "0.05", "mid": "", "high": "0.20", **factor},
            {"factor_id": "F3", "name": "seats", "op": "mul",
             "low": "10", "mid": "", "high": "40", **factor},
        ],
    )
    append_rows(
        data / "evidence.csv",
        [
            {"evidence_id": "EV1", "pass": "1", "date_captured": "2026-07-10",
             "factor_id": "F1", "quote": QUOTE, "source_type": "web",
             "source_url": "https://a.com/1", "published_date": "", "notes": ""},
        ],
    )
    set_vault_note(root, "Notes/Estimate.md")
    return root


def test_render_map_projects_categories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verified map store renders per-category confidence with every finding
    marked; diverging and reference rows are labeled, not hidden."""
    topic = seed_map(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["status"] == "rendered"
    assert envelope["gate"]["n_verified"] == 5
    text = Path(str(envelope["note"])).read_text(encoding="utf-8")
    assert "## Categories" in text
    assert "### Alpha things" in text
    assert "Confidence 20% (Low): 2 supporting unit(s), 0 diverging." in text
    assert "Confidence 0% (Low): 1 supporting unit(s), 1 diverging." in text
    assert f"- **Alpha Corp:** {QUOTE}" in text
    # detail_quote renders as the deeper blockquote only where one was captured.
    assert '> "the deeper detail behind the finding"' in text
    assert "Diverging:" in text
    assert "- **Delta Co:**" in text
    assert "Reference (excluded from confidence):" in text
    assert "- **Epsilon AG:**" in text
    assert "✓ verified" in text
    # C1 has a primary source; posting-only C2 shows the held-below-High note.
    assert text.count("No primary source yet") == 1


def test_render_rank_projects_ranking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verified rank store renders the fit ranking and per-cell evidence,
    with an honest prior line for an evidence-free cell."""
    topic = seed_rank(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["status"] == "rendered"
    assert envelope["gate"]["n_verified"] == 3
    text = Path(str(envelope["note"])).read_text(encoding="utf-8")
    assert "## Ranking" in text
    assert "1. **Alpha**: fit 86.6%" in text
    assert "2. **Beta**: fit 52.5%" in text
    assert "## Per-candidate evidence" in text
    assert "### Alpha" in text
    assert "Least resolved: quality." in text
    assert "- **Quality:** certainty 94% (established), from 1 source" in text
    assert "(supports) (✓ verified)" in text
    # beta--price has no rows: the cell shows its prior, never a hidden gap.
    assert "(no sourced evidence for this cell; certainty sits at the prior)" in text


def test_render_estimate_projects_magnitude(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verified estimate store renders the propagated interval and each
    factor's range, with honest blanks for unsourced factors."""
    topic = seed_estimate(tmp_path, capsys)
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run(capsys, render_args(topic, tmp_path))
    assert envelope["status"] == "rendered"
    assert envelope["gate"]["n_verified"] == 1
    text = Path(str(envelope["note"])).read_text(encoding="utf-8")
    assert "## Estimate" in text
    assert "**2000** [90% CI 750.4 .. 5330] (analytic-lognormal)." in text
    assert "Dominant uncertainty: rate" in text
    assert "## Factors" in text
    assert "### orgs" in text
    assert "Range 1000 .. 1000 (mul), 0% of total variance." in text
    assert "Range 0.05 .. 0.2 (mul), 50% of total variance." in text
    assert "✓ verified" in text
    # F2 and F3 carry no evidence rows; the note says so instead of guessing.
    assert text.count("(no sourced evidence for this factor)") == 2


def test_render_registry_matches_schemas() -> None:
    """Renderer parity: every mode in the schema registry renders, no extras."""
    assert set(render.MODE_RENDERERS) == set(store.MODE_SCHEMAS)


def test_render_missing_vault_note_is_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verified store with no vault_note set fails with actionable guidance."""
    topic = seed_find(tmp_path, capsys, note="")
    do_verify(topic, capsys, page_has_quote=True)
    envelope = run_error(capsys, render_args(topic, tmp_path))
    assert "vault_note is empty" in envelope["error"]
