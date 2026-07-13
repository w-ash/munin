"""Tests for topic scaffolding."""

from pathlib import Path

import pytest

from vault_scripts.research import scaffold, store


@pytest.fixture
def created(tmp_path: Path) -> scaffold.CreatedTopic:
    return scaffold.create_topic("demo-topic", "Demo Topic", tmp_path)


def test_file_set(created: scaffold.CreatedTopic) -> None:
    expected = {
        "CLAUDE.md",
        "HANDOFF.md",
        "FINDER-PROMPT.md",
        "SYNTHESIS.md",
        "research.toml",
        "narrative/README.md",
        ".claude/rules/evidence.md",
        ".claude/rules/orchestration.md",
        "data/taxonomy.csv",
        "data/evidence.csv",
        "data/sources.csv",
    }
    assert set(created.files) == expected
    for rel in expected:
        assert (created.root / rel).is_file()


def test_no_topic_local_skills(created: scaffold.CreatedTopic) -> None:
    # run-pass lives once in the plugin; topics no longer carry a copy.
    assert not (created.root / ".claude" / "skills").exists()


def test_placeholders(created: scaffold.CreatedTopic) -> None:
    claude_md = (created.root / "CLAUDE.md").read_text()
    assert "Demo Topic" in claude_md
    assert "{{TOPIC_TITLE}}" not in claude_md
    config = (created.root / "research.toml").read_text()
    assert 'slug = "demo-topic"' in config
    handoff = (created.root / "HANDOFF.md").read_text()
    assert "{{DATE}}" not in handoff
    # Seeding placeholders survive for the seeding interview.
    assert "{{UNIT_1}}" in handoff
    assert "{{RESEARCH_QUESTION}}" in claude_md


def test_mode_recorded(created: scaffold.CreatedTopic) -> None:
    config = (created.root / "research.toml").read_text()
    assert 'mode = "map"' in config
    assert store.load_config(created.root).mode == "map"


def test_rejects_unknown_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        scaffold.create_topic("demo-topic", "Demo Topic", tmp_path, mode="bogus")
    # Rejected before anything was written.
    assert not (tmp_path / "demo-topic").exists()


@pytest.mark.parametrize(
    ("mode", "core_csvs", "seeding_placeholder"),
    [
        (
            "find",
            ["entities.csv", "attributes.csv", "evidence.csv"],
            "{{FRAME_DEFINITION}}",
        ),
        ("estimate", ["factors.csv", "evidence.csv"], "{{TARGET_QUANTITY}}"),
    ],
)
def test_mode_overlay_renders(
    tmp_path: Path, mode: str, core_csvs: list[str], seeding_placeholder: str
) -> None:
    """A mode overlay replaces the base docs, records the mode, scaffolds its
    own core CSVs, and leaves only seeding placeholders (no map-only ones)."""
    created = scaffold.create_topic("demo-topic", "Demo Topic", tmp_path, mode=mode)
    root = created.root
    assert store.load_config(root).mode == mode
    for csv_name in core_csvs:
        assert (root / "data" / csv_name).is_file()
    # The mode's seeding placeholder survives; map-only placeholders never leak.
    claude_md = (root / "CLAUDE.md").read_text()
    assert seeding_placeholder in claude_md
    for map_only in ("{{TAXONOMY_LIST}}", "{{UNIT_1}}", "{{PRIORITY_CATEGORIES}}"):
        for rel in ("CLAUDE.md", "HANDOFF.md", "FINDER-PROMPT.md", "SYNTHESIS.md"):
            assert map_only not in (root / rel).read_text()
    # The overlays drive `research score`, not the map-only `research status`.
    assert "research score" in (root / "CLAUDE.md").read_text()
    # Shared files are inherited, not forked.
    assert (root / ".claude" / "rules" / "orchestration.md").is_file()
    assert (root / "narrative" / "README.md").is_file()


def test_fresh_topic_passes_check(created: scaffold.CreatedTopic) -> None:
    topic = store.load_topic(created.root)
    errors, warnings = store.check(topic)
    assert errors == []
    assert warnings == []


@pytest.mark.usefixtures("created")
def test_refuses_overwrite(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        scaffold.create_topic("demo-topic", "Demo Topic", tmp_path)


@pytest.mark.parametrize("slug", ["Bad Slug", "UPPER", "-leading", "trailing space "])
def test_rejects_bad_slug(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ValueError, match="kebab-case"):
        scaffold.create_topic(slug, "Title", tmp_path)


def test_verify_overlay(tmp_path: Path) -> None:
    created = scaffold.create_topic("demo-v", "Demo V", tmp_path, mode="verify")
    files = set(created.files)
    # Overlaid docs replace the base; orchestration + narrative are inherited.
    assert "data/claims.csv" in files
    assert "data/evidence.csv" in files
    assert "data/taxonomy.csv" not in files  # map-only
    assert ".claude/rules/orchestration.md" in files  # inherited from base
    claude_md = (created.root / "CLAUDE.md").read_text()
    assert "verify" in claude_md.lower()
    assert "{{TOPIC_TITLE}}" not in claude_md  # base substitutions still applied
    config = (created.root / "research.toml").read_text()
    assert "[verify]" in config
    assert store.load_config(created.root).mode == "verify"


def test_rank_overlay(tmp_path: Path) -> None:
    created = scaffold.create_topic("demo-r", "Demo R", tmp_path, mode="rank")
    files = set(created.files)
    assert {"data/candidates.csv", "data/criteria.csv", "data/evidence.csv"} <= files
    config = (created.root / "research.toml").read_text()
    assert "[rank]" in config
    assert store.load_config(created.root).mode == "rank"


def test_verify_scaffold_checks_clean(tmp_path: Path) -> None:
    created = scaffold.create_topic("demo-v", "Demo V", tmp_path, mode="verify")
    topic = store.load_topic(created.root)
    errors, _ = store.check(topic)
    assert errors == []


def test_rank_scaffold_checks_clean(tmp_path: Path) -> None:
    created = scaffold.create_topic("demo-r", "Demo R", tmp_path, mode="rank")
    topic = store.load_topic(created.root)
    errors, _ = store.check(topic)
    assert errors == []
