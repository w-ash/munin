# pyright: reportAny=false, reportExplicitAny=false
# Vendored research harness: this module reads the CSV store and argparse
# Namespaces, boundaries where the stdlib hands back `Any`. reportAny/
# reportExplicitAny are above basedpyright's standard strict (which this file
# passes); every other strict check still applies.
"""Render a verified store into its vault note, gated so it can't ship unverified.

The durable, vault-facing record of a topic is a projection of its verified
store, never a hand-authored artifact: ``research render`` reads the evidence
and citation verdicts and writes the note, so a claim reaches the vault only
with its quote, source, and a verification mark attached. This is the step the
supplement-timing incident skipped when it hand-transcribed finder conclusions
into a note over an empty, unchecked store.

The gate is resolve-or-waive: render refuses (a non-zero CLI exit) unless the
store has cited evidence and every cited row is either ``verified`` by
``research verify`` or listed in ``data/waivers.csv`` (a recorded exception with
a reason). No fuzzy verified-rate; an unverified cell is fixed or waived, never
silently shipped.

The note carries a managed evidence block between
``<!-- research:evidence:start -->`` and ``<!-- research:evidence:end -->``.
Render owns only that block; the hand-authored narrative outside the markers is
preserved byte-for-byte across re-renders (the three planes: evidence is
projected, the narrative is yours). A per-mode ``MODE_RENDERERS`` registry
mirrors ``score.MODE_SCORERS`` and ``mirror.MODE_MIRRORS``, one renderer per
mode in ``store.MODE_SCHEMAS``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from vault_scripts.research import (
    coverage as coverage_mod,
    score as score_mod,
    store as store_mod,
    verify as verify_mod,
)
from vault_scripts.research.confidence import (
    CELL_SEP,
    DIV_SUFFIX,
    REF_SUFFIX,
    VOID_ID,
)

WAIVERS_CSV = "waivers.csv"
WAIVER_COLUMNS = ("evidence_id", "reason", "date")

# The managed evidence block markers. Everything between them is rewritten by
# render; everything outside is the hand-authored narrative, left untouched.
EVIDENCE_START = "<!-- research:evidence:start -->"
EVIDENCE_END = "<!-- research:evidence:end -->"

# Per-row display marks, keyed by the effective bucket a row lands in (see
# ``evaluate_gate``). A shipped note only ever shows verified/waived, since the
# gate blocks render while any other bucket is present; the ⚠ marks surface in
# a --dry-run preview and in the blocking list.
_MARKS: dict[str, str] = {
    "verified": "✓ verified",
    verify_mod.QUOTE_MISSING: "⚠ quote not found on page today",
    verify_mod.DEAD: "⚠ dead link",
    verify_mod.UNFETCHABLE: "⚠ source unreachable",
    verify_mod.NO_QUOTE: "⚠ no quote to check",
    "unchecked": "⚠ not verified",
}

# An attribute `name` longer than this reads as a definition, not a column
# label (the supplement store puts a full sentence in `name`); fall back to the
# id humanized. Short names are used verbatim as the label.
_MAX_LABEL = 48


@dataclass(frozen=True)
class Blocking:
    """One cited row the gate will not pass: neither verified nor waived."""

    evidence_id: str
    bucket: str  # quote_missing | dead | unfetchable | no_quote | unchecked
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "status": self.bucket,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class Gate:
    """The render gate's verdict over a topic's cited evidence rows."""

    n_citable: int
    n_verified: int
    n_waived: int
    blocking: list[Blocking]
    status_counts: dict[str, int]  # effective bucket -> count, non-overlapping

    @property
    def ok(self) -> bool:
        """True when there is cited evidence and nothing is blocking."""
        return self.n_citable > 0 and not self.blocking

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_citable": self.n_citable,
            "n_verified": self.n_verified,
            "n_waived": self.n_waived,
            "blocking": [b.as_dict() for b in self.blocking],
            "status_counts": dict(self.status_counts),
        }


def _row_ref(row: dict[str, str]) -> str:
    """The row's mode-specific topic reference (any one may carry VOID)."""
    return (
        row.get("category_id")
        or row.get("claim_id")
        or row.get("cell_id")
        or row.get("factor_id")
        or ""
    )


def _citable_rows(topic: store_mod.Topic) -> list[dict[str, str]]:
    """Non-VOID evidence rows that carry a ``source_url`` (each makes a citation
    ``research verify`` checks)."""
    evidence = topic.tables.get(store_mod.EVIDENCE_CSV)
    if evidence is None:
        return []
    return [
        row
        for row in evidence.rows
        if _row_ref(row) != VOID_ID and row.get("source_url", "").strip()
    ]


def read_waivers(topic: store_mod.Topic) -> dict[str, str]:
    """The recorded citation exceptions, ``evidence_id -> reason``.

    ``data/waivers.csv`` (``evidence_id,reason,date``) is the resolve-or-waive
    escape hatch: a row here is an accepted, logged exception, so the gate treats
    it as passed and the note marks it ``◐ waived`` rather than hiding it."""
    table = topic.tables.get(WAIVERS_CSV)
    if table is None:
        return {}
    return {
        row["evidence_id"]: row.get("reason", "")
        for row in table.rows
        if row.get("evidence_id")
    }


def evaluate_gate(topic: store_mod.Topic) -> Gate:
    """Bucket every cited row as verified, waived, or blocking.

    Buckets are non-overlapping and precedence-ordered: a row is ``verified``
    when ``research verify`` confirmed its quote, else ``waived`` when it is in
    ``data/waivers.csv``, else it blocks under its raw verify status (or
    ``unchecked`` when verify never ran on it)."""
    citations = verify_mod.read_citations(topic)
    waivers = read_waivers(topic)
    counts: dict[str, int] = {}
    blocking: list[Blocking] = []
    citable = _citable_rows(topic)
    for row in citable:
        eid = row.get("evidence_id", "")
        status = citations.get(eid, "")
        if status == verify_mod.VERIFIED:
            bucket = "verified"
        elif eid in waivers:
            bucket = "waived"
        else:
            bucket = status or "unchecked"
            blocking.append(Blocking(eid, bucket, row.get("source_url", "")))
        counts[bucket] = counts.get(bucket, 0) + 1
    return Gate(
        n_citable=len(citable),
        n_verified=counts.get("verified", 0),
        n_waived=counts.get("waived", 0),
        blocking=blocking,
        status_counts=counts,
    )


# --- Rendering (per-mode block builders) ---


def _humanize(attribute_id: str) -> str:
    """``daytime_effect`` -> ``Daytime effect``: a column label from an id."""
    return attribute_id.replace("_", " ").replace("-", " ").capitalize()


def _display_label(name: str, fallback_id: str) -> str:
    """The display label for a named item: its ``name`` when that reads as a
    label, else the humanized id (the supplement store's attribute ``name`` is
    a full definition, so it falls back)."""
    name = name.strip()
    if name and len(name) <= _MAX_LABEL and "\n" not in name:
        return name
    return _humanize(fallback_id)


def _label(attr: coverage_mod.Attribute) -> str:
    """The display label for a find-mode attribute."""
    return _display_label(attr.name, attr.attribute_id)


def _mark(eid: str, citations: dict[str, str], waivers: dict[str, str]) -> str:
    """The verification mark for one evidence row, verified taking precedence
    over a waiver so a row that later verifies loses the waived mark."""
    status = citations.get(eid, "")
    if status == verify_mod.VERIFIED:
        return _MARKS["verified"]
    if eid in waivers:
        reason = waivers[eid].strip()
        return f"◐ waived: {reason}" if reason else "◐ waived"
    return _MARKS.get(status, _MARKS["unchecked"])


def _citation(
    row: dict[str, str],
    citations: dict[str, str],
    waivers: dict[str, str],
    *,
    with_bearing: bool = False,
) -> str:
    """The markdown source line for one evidence row: link, optional bearing
    tail (verify/rank evidence is source-weighted), and verification mark."""
    url = row.get("source_url", "").strip()
    src = row.get("source_type", "").strip() or "source"
    mark = _mark(row.get("evidence_id", ""), citations, waivers)
    bearing = row.get("bearing", "").strip() if with_bearing else ""
    tail = f" ({bearing})" if bearing else ""
    return f"[{src}]({url}){tail} ({mark})"


def _evidence_by(topic: store_mod.Topic, key: str) -> dict[str, list[dict[str, str]]]:
    """Group non-VOID evidence rows by the mode's id column (``claim_id``,
    ``cell_id``, or ``factor_id``)."""
    grouped: dict[str, list[dict[str, str]]] = {}
    evidence = topic.tables.get(store_mod.EVIDENCE_CSV)
    if evidence is None:
        return grouped
    for row in evidence.rows:
        ref = row.get(key, "")
        if ref and ref != VOID_ID:
            grouped.setdefault(ref, []).append(row)
    return grouped


def _evidence_by_category(
    topic: store_mod.Topic,
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Group non-VOID map evidence rows by base category, bucketed by the id's
    suffix: ``supporting`` (the bare id), ``diverging`` (``-div``), and
    ``reference`` (``-ref``, context excluded from the confidence counts)."""
    grouped: dict[str, dict[str, list[dict[str, str]]]] = {}
    evidence = topic.tables.get(store_mod.EVIDENCE_CSV)
    if evidence is None:
        return grouped
    for row in evidence.rows:
        cid = row.get("category_id", "")
        if not cid or cid == VOID_ID:
            continue
        if cid.endswith(DIV_SUFFIX):
            base, bucket = cid.removesuffix(DIV_SUFFIX), "diverging"
        elif cid.endswith(REF_SUFFIX):
            base, bucket = cid.removesuffix(REF_SUFFIX), "reference"
        else:
            base, bucket = cid, "supporting"
        grouped.setdefault(base, {}).setdefault(bucket, []).append(row)
    return grouped


def _newest_first(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rows newest-dated first, honoring the store convention that a newer-dated
    row supersedes the source it replaces. Ties and undated rows keep their
    append order, so the file remains the tiebreaker."""
    return sorted(
        rows,
        key=lambda r: (r.get("date_captured", "") or "", r.get("pass", "") or ""),
        reverse=True,
    )


def _pick(
    rows: list[dict[str, str]], citations: dict[str, str], waivers: dict[str, str]
) -> dict[str, str] | None:
    """The representative evidence row to show for a cell: prefer a verified
    row, then a waived one, then the first. Within each tier the newest-dated
    row wins, so a superseding row displaces the source it replaced rather than
    losing to it on append order."""
    ordered = _newest_first(rows)
    for row in ordered:
        if citations.get(row.get("evidence_id", "")) == verify_mod.VERIFIED:
            return row
    for row in ordered:
        if row.get("evidence_id", "") in waivers:
            return row
    return ordered[0] if ordered else None


def _status_block(gate: Gate, unit: str) -> list[str]:
    """The ``## Verification status`` header lines from the gate counts."""
    parts = [f"{gate.n_verified} verified"]
    if gate.n_waived:
        parts.append(f"{gate.n_waived} waived")
    for bucket, label in (
        (verify_mod.QUOTE_MISSING, "quote-not-found"),
        (verify_mod.DEAD, "dead"),
        (verify_mod.UNFETCHABLE, "unreachable"),
        ("unchecked", "unchecked"),
    ):
        n = gate.status_counts.get(bucket, 0)
        if n:
            parts.append(f"{n} {label}")
    return [
        "## Verification status",
        "",
        (
            "A mechanical citation check fetched each cited page and confirmed the "
            f"verbatim quote. **{', '.join(parts)}**, over {gate.n_citable} cited "
            f"{unit}. Each entry below carries its quote, source, and mark; a "
            "waived cell is a recorded exception in `data/waivers.csv`, not a hidden "
            "gap. The evidence store lives outside the vault; this note is its "
            "readable, verified record."
        ),
    ]


def render_find(
    topic: store_mod.Topic,
    citations: dict[str, str],
    waivers: dict[str, str],
    gate: Gate,
) -> str:
    """Project a find-mode store: per-entity, per-attribute cells with marks."""
    entities = topic.find_entities()
    attributes = topic.find_attributes()
    by_cell = _evidence_by(topic, "cell_id")

    lines = [*_status_block(gate, "claims"), "", "## Per-entity evidence", ""]
    for ent in entities:
        if not ent.in_frame:
            continue
        lines.extend((f"### {ent.name or ent.entity_id}", ""))
        for attr in attributes:
            value = ent.fields.get(attr.attribute_id, "").strip()
            lines.append(f"- **{_label(attr)}:** {value or '(no value recorded)'}")
            cell = coverage_mod.cell_id(ent.entity_id, attr.attribute_id)
            rep = _pick(by_cell.get(cell, []), citations, waivers)
            if rep is None:
                lines.append("  > (no verbatim quote captured for this cell)")
                continue
            quote = rep.get("quote", "").strip()
            lines.extend((f'  > "{quote}"', f"  {_citation(rep, citations, waivers)}"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_verify(
    topic: store_mod.Topic,
    citations: dict[str, str],
    waivers: dict[str, str],
    gate: Gate,
) -> str:
    """Project a verify-mode store: per-claim certainty plus marked sources."""
    verdicts = {v.claim_id: v for v in score_mod.verify_rows(topic)}
    claims = {r["claim_id"]: r["claim"] for r in topic.tables[store_mod.CLAIMS_CSV].rows}
    by_claim = _evidence_by(topic, "claim_id")

    lines = [*_status_block(gate, "sources"), "", "## Claims", ""]
    for cid, text in claims.items():
        lines.append(f"### {text}")
        v = verdicts.get(cid)
        if v is not None:
            lines.extend((
                "",
                f"Certainty {v.certainty:.0f}% ({v.band}), from {v.n_sources} "
                f"source{'s' if v.n_sources != 1 else ''}.",
            ))
        lines.append("")
        for row in by_claim.get(cid, []):
            if row.get("source_url", "").strip():
                quote = row.get("quote", "").strip()
                lines.extend((
                    f'- > "{quote}"',
                    f"  {_citation(row, citations, waivers, with_bearing=True)}",
                ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_map(
    topic: store_mod.Topic,
    citations: dict[str, str],
    waivers: dict[str, str],
    gate: Gate,
) -> str:
    """Project a map-mode store: per-category confidence plus marked findings,
    diverging and reference rows labeled rather than hidden."""
    results = score_mod.map_rows(topic)
    names = {r["category_id"]: r["name"] for r in topic.tables[store_mod.TAXONOMY_CSV].rows}
    grouped = _evidence_by_category(topic)
    noun = topic.config.unit_noun

    lines = [*_status_block(gate, "findings"), "", "## Categories", ""]
    for r in results:
        buckets = grouped.get(r.category_id, {})
        lines.extend((f"### {names.get(r.category_id) or r.category_id}", ""))
        lines.append(
            f"Confidence {r.confidence:.0%} ({r.tier}): {r.supporting_units} "
            f"supporting {noun}(s), {r.diverging_units} diverging."
        )
        if not r.primary_backed:
            lines.append("No primary source yet, so confidence is held below High.")
        lines.append("")
        supporting = buckets.get("supporting", [])
        if not supporting:
            lines.extend(("(no findings recorded for this category)", ""))
        for row in supporting:
            lines.extend(_map_row_lines(row, citations, waivers))
        if supporting:
            lines.append("")
        for label, bucket in (
            ("Diverging:", "diverging"),
            ("Reference (excluded from confidence):", "reference"),
        ):
            rows = buckets.get(bucket, [])
            if not rows:
                continue
            lines.append(label)
            for row in rows:
                lines.extend(_map_row_lines(row, citations, waivers))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _map_row_lines(
    row: dict[str, str], citations: dict[str, str], waivers: dict[str, str]
) -> list[str]:
    """One map finding as note lines: unit, verbatim finding, the deeper quote
    when one was captured, and the marked source."""
    unit = row.get("unit", "").strip()
    finding = row.get("finding_verbatim", "").strip()
    detail = row.get("detail_quote", "").strip()
    lines = [f"- **{unit}:** {finding}"]
    if detail:
        lines.append(f'  > "{detail}"')
    lines.append(f"  {_citation(row, citations, waivers)}")
    return lines


def render_rank(
    topic: store_mod.Topic,
    citations: dict[str, str],
    waivers: dict[str, str],
    gate: Gate,
) -> str:
    """Project a rank-mode store: the fit ranking plus per-cell marked sources."""
    verdicts = score_mod.rank_rows(topic)
    texts = {
        r["criterion_id"]: r.get("text", "")
        for r in topic.tables[store_mod.CRITERIA_CSV].rows
    }
    by_cell = _evidence_by(topic, "cell_id")

    lines = [*_status_block(gate, "sources"), "", "## Ranking", ""]
    for i, v in enumerate(verdicts, start=1):
        blocked = f" (blocked: {', '.join(v.blocked_by)})" if v.blocked else ""
        lines.append(f"{i}. **{v.candidate}**: fit {v.score:.1f}%{blocked}")
    lines.extend(("", "## Per-candidate evidence", ""))
    for v in verdicts:
        lines.extend((
            f"### {v.candidate}",
            "",
            f"Least resolved: {v.least_resolved or '-'}. "
            f"Evidence gaps: {', '.join(v.evidence_gaps) or 'none'}.",
            "",
        ))
        for s in v.criteria:
            label = _display_label(texts.get(s.criterion_id, ""), s.criterion_id)
            lines.append(
                f"- **{label}:** certainty {s.certainty:.0f}% ({s.band}), from "
                f"{s.n_sources} source{'s' if s.n_sources != 1 else ''}"
            )
            rows = by_cell.get(f"{v.candidate_id}{CELL_SEP}{s.criterion_id}", [])
            if not rows:
                lines.append(
                    "  (no sourced evidence for this cell; certainty sits at "
                    "the prior)"
                )
                continue
            for row in rows:
                quote = row.get("quote", "").strip()
                lines.extend((
                    f'  > "{quote}"',
                    f"  {_citation(row, citations, waivers, with_bearing=True)}",
                ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_estimate(
    topic: store_mod.Topic,
    citations: dict[str, str],
    waivers: dict[str, str],
    gate: Gate,
) -> str:
    """Project an estimate-mode store: the propagated magnitude plus each
    factor's sourced range and marked evidence."""
    factors = topic.estimate_factors()
    result = score_mod.estimate_result(topic, factors)
    stats = {s.factor_id: s for s in result.factors}
    by_factor = _evidence_by(topic, "factor_id")

    dominant = stats.get(result.dominant_factor)
    lines = [
        *_status_block(gate, "sources"),
        "",
        "## Estimate",
        "",
        f"**{result.median:g}** [{result.ci:.0f}% CI {result.low:g} .. "
        f"{result.high:g}] ({result.method}).",
        f"Dominant uncertainty: {dominant.name if dominant else '-'} (largest "
        "variance share; the natural refutation target).",
        "",
        "## Factors",
        "",
    ]
    for f in factors:
        s = stats[f.factor_id]
        lines.extend((
            f"### {s.name}",
            "",
            f"Range {f.low:g} .. {f.high:g} ({s.op}), {s.variance_share:.0%} "
            "of total variance.",
            "",
        ))
        rows = by_factor.get(f.factor_id, [])
        if not rows:
            lines.extend(("(no sourced evidence for this factor)", ""))
            continue
        for row in rows:
            quote = row.get("quote", "").strip()
            lines.extend((
                f'- > "{quote}"',
                f"  {_citation(row, citations, waivers)}",
            ))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


Renderer = Callable[
    [store_mod.Topic, dict[str, str], dict[str, str], Gate], str
]

# Keyed by the same names as store.MODE_SCHEMAS, one renderer per mode; a
# parity test ties the keys to the schema registry.
MODE_RENDERERS: dict[str, Renderer] = {
    "map": render_map,
    "verify": render_verify,
    "rank": render_rank,
    "find": render_find,
    "estimate": render_estimate,
}


def build_evidence_block(topic: store_mod.Topic, gate: Gate) -> str:
    """Build the managed evidence block for the topic's mode."""
    renderer = MODE_RENDERERS[topic.config.mode]
    citations = verify_mod.read_citations(topic)
    waivers = read_waivers(topic)
    return renderer(topic, citations, waivers, gate)


# --- Writing the note (managed block, narrative preserved) ---


def vault_root(explicit: str | None) -> Path:
    """The vault root a relative ``vault_note`` resolves against: an explicit
    ``--vault-root``, else the ``VAULT_DIR`` the dispatcher exports."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("VAULT_DIR")
    if env:
        return Path(env)
    raise ValueError(
        "no vault root: pass --vault-root, or run through the vault-tool "
        "dispatcher (which exports VAULT_DIR)"
    )


def resolve_note_path(topic: store_mod.Topic, root: Path) -> Path:
    """The note's path, from ``research.toml`` ``[topic] vault_note`` resolved
    against the vault root (an absolute ``vault_note`` is honored as-is)."""
    rel = topic.config.vault_note.strip()
    if not rel:
        raise ValueError(
            "research.toml [topic] vault_note is empty; set it to the note's "
            "path within the vault (e.g. \"Health/Supplements/Timing Study.md\")"
        )
    path = Path(rel)
    return path if path.is_absolute() else root / path


def _scaffold_note(topic: store_mod.Topic, block: str) -> str:
    """A fresh note: frontmatter, title, a narrative placeholder, and the
    managed evidence block."""
    today = datetime.now(tz=UTC).astimezone().date().isoformat()
    return (
        f'---\ncreated: "{today}"\ntags:\n  - reference\n---\n\n'
        f"# {topic.config.title}\n\n"
        "> Summary and narrative go here. Everything outside the evidence block "
        "below is yours to edit; `research render` only rewrites the block "
        "between the markers.\n\n"
        f"{EVIDENCE_START}\n{block}\n{EVIDENCE_END}\n"
    )


def _splice(existing: str, block: str) -> str:
    """Replace the content between the evidence markers, preserving the rest."""
    start = existing.find(EVIDENCE_START)
    end = existing.find(EVIDENCE_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"note exists but has no evidence markers; add a {EVIDENCE_START} / "
            f"{EVIDENCE_END} pair where the evidence block should go, or delete "
            "the note to regenerate it"
        )
    before = existing[:start]
    after = existing[end + len(EVIDENCE_END) :]
    return f"{before}{EVIDENCE_START}\n{block}\n{EVIDENCE_END}{after}"


def write_note(topic: store_mod.Topic, root: Path, block: str) -> tuple[Path, str]:
    """Write the note, returning its path and the action taken.

    A missing note is scaffolded whole; an existing one has only its managed
    block replaced (the narrative is preserved). An existing note without
    markers is refused rather than clobbered. Returns action ``created`` /
    ``updated`` / ``unchanged``; an unchanged note is not rewritten (no needless
    iCloud write)."""
    path = resolve_note_path(topic, root)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        new = _splice(existing, block)
        action = "unchanged" if new == existing else "updated"
    else:
        new = _scaffold_note(topic, block)
        action = "created"
    if action != "unchanged":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return path, action
