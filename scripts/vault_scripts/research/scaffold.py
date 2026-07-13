"""Scaffold a new topic directory from the packaged templates.

Templates ship as package data under ``vault_scripts/research/templates/``. The
``dot-claude`` directory maps to ``.claude`` on write (dot-directories are a
packaging edge case). Only ``{{TOPIC_TITLE}}``, ``{{TOPIC_SLUG}}``,
``{{MODE}}``, and ``{{DATE}}`` are substituted; the richer seeding
placeholders stay intact for the seeding step (the ``new-research`` skill
walks through them).

The base tree is ``map``-shaped. A mode with its own operational docs ships
them under ``templates/modes/<mode>/``; they render *over* the base after it,
so a mode overrides only the files that differ (``FINDER-PROMPT.md``,
``evidence.md``, ``SYNTHESIS.md``, ``research.toml``, and the two docs that
carry map-only placeholders, ``CLAUDE.md`` and ``HANDOFF.md``) and inherits
the rest (``orchestration.md``, ``narrative/``). The base walk skips the
``modes`` directory so it never renders into the topic.
"""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
import re

from vault_scripts.research.store import DATA_DIR, MODE_SCHEMAS, validate_mode

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class CreatedTopic:
    root: Path
    files: list[str]


MODES_DIR = "modes"  # templates/modes/<mode>/ overlays; skipped by the base walk


def _render_tree(
    node: Traversable,
    target: Path,
    replacements: dict[str, str],
    written: list[str],
    rel: str = "",
) -> None:
    for entry in node.iterdir():
        # The mode overlays under templates/modes/ render separately, over the
        # base; the base walk skips them. `modes` only exists at the top level.
        if entry.name == MODES_DIR and not rel:
            continue
        name = ".claude" if entry.name == "dot-claude" else entry.name
        entry_rel = f"{rel}{name}"
        if entry.is_dir():
            _render_tree(entry, target, replacements, written, f"{entry_rel}/")
            continue
        text = entry.read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        out = target / entry_rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(entry_rel)


def create_topic(slug: str, title: str, dest: Path, mode: str = "map") -> CreatedTopic:
    """Create ``dest/slug`` from the templates plus header-only data CSVs."""
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(f"slug must be kebab-case ([a-z0-9-]), got {slug!r}")
    validate_mode(mode)  # before any file is written
    target = dest / slug
    if target.exists():
        raise FileExistsError(f"{target} already exists; refusing to overwrite")

    today = datetime.now(tz=UTC).astimezone().date().isoformat()
    replacements = {
        "{{TOPIC_TITLE}}": title,
        "{{TOPIC_SLUG}}": slug,
        "{{MODE}}": mode,
        "{{DATE}}": today,
    }

    written: list[str] = []
    templates = files("vault_scripts.research") / "templates"
    _render_tree(templates, target, replacements, written)
    overlay = templates / MODES_DIR / mode
    if overlay.is_dir():
        _render_tree(overlay, target, replacements, written)

    data = target / DATA_DIR
    data.mkdir(parents=True, exist_ok=True)
    for name, columns in MODE_SCHEMAS[mode].core_columns.items():
        path = data / name
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(columns)
        written.append(f"{DATA_DIR}/{name}")

    # An overlaid file is written twice (base then override); report it once.
    return CreatedTopic(root=target, files=sorted(set(written)))
