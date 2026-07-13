"""Roster coverage as recall and per-field verification, as pure functions.

The `find` mode asks "get every entity matching a filter, with its attributes."
Its atom is the *field* (an entity's attribute value), and the question is not
how authoritative a source is but whether the roster is *complete* and the
fields are *right*. So there is no decibans score here: the quality bar is
**recall** (did we get everyone in the named frame) and **precision** (does each
field trace to a source that checks out).

Recall needs a denominator. When the frame declares an ``expected_count`` (a
known-size set like "the top 100 companies"), recall is ``found / expected``.
When it does not, the honest signal is *saturation*: the per-pass discovery
curve (new entities found each pass), which flattens as the frame is exhausted
(the capture-recapture intuition). Per-field verification reuses ``verify``'s
mechanical citation check: a cell is verified when one of its evidence rows has
a ``verified`` verdict in ``data/citations.csv``.

Everything is computed from the roster and evidence on every run, the same
computed-never-stored contract as ``confidence.py`` and ``certainty.py``.
Written fresh (no source-weighting to port); it reuses only the citation
verdicts, passed in as a set of verified evidence ids so this stays free of any
``verify`` import.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from vault_scripts.research.confidence import CELL_SEP


@dataclass(frozen=True)
class Entity:
    """One roster row. ``in_frame`` marks it as a member of the named frame
    (an out-of-frame row is kept for provenance but excluded from recall);
    ``fields`` maps ``attribute_id`` to the extracted value (empty = unfilled)
    and ``first_pass`` is the pass that first observed it, for the discovery
    curve (0 when no evidence dates it)."""

    entity_id: str
    name: str
    in_frame: bool
    fields: dict[str, str] = field(default_factory=dict)
    first_pass: int = 0


@dataclass(frozen=True)
class Attribute:
    """One extracted field. ``required`` fields must be filled (and ideally
    verified) for an entity to count as complete."""

    attribute_id: str
    name: str = ""
    required: bool = False


@dataclass(frozen=True)
class FieldObservation:
    """One sourced observation of a cell (an ``<entity>--<attribute>`` pair)."""

    cell_id: str
    evidence_id: str
    pass_num: int
    source_url: str


@dataclass(frozen=True)
class FieldCell:
    """One entity-attribute cell's fill and verification state."""

    entity_id: str
    attribute_id: str
    filled: bool
    verified: bool
    n_sources: int


@dataclass(frozen=True)
class AttributeCoverage:
    """Per-attribute rollup across the in-frame roster."""

    attribute_id: str
    name: str
    required: bool
    n_filled: int
    n_verified: int
    fill_rate: float
    verified_rate: float


@dataclass(frozen=True)
class CoverageReport:
    """Roster coverage: recall against the frame plus per-field completeness."""

    expected: int | None
    found: int
    recall: float | None
    saturating: list[tuple[int, int]]  # (pass, new-entities-that-pass), pass-ordered
    field_fill: float  # filled cells / (in-frame entities x attributes)
    field_verified: float  # verified cells / filled cells
    per_attribute: list[AttributeCoverage]
    thin_entities: list[str]  # in-frame entities missing a required field


def cell_id(entity_id: str, attribute_id: str) -> str:
    return f"{entity_id}{CELL_SEP}{attribute_id}"


def field_cells(
    entities: list[Entity],
    attributes: list[Attribute],
    observations: Iterable[FieldObservation],
    verified_ids: frozenset[str],
) -> list[FieldCell]:
    """Build the entity x attribute grid. A cell is ``filled`` when the entity
    carries a non-empty value for the attribute; ``verified`` when at least one
    of its observations has a verified citation verdict. Order-independent."""
    by_cell: dict[str, list[FieldObservation]] = {}
    for obs in observations:
        by_cell.setdefault(obs.cell_id, []).append(obs)

    cells: list[FieldCell] = []
    for ent in entities:
        for attr in attributes:
            cid = cell_id(ent.entity_id, attr.attribute_id)
            obs = by_cell.get(cid, [])
            cells.append(
                FieldCell(
                    entity_id=ent.entity_id,
                    attribute_id=attr.attribute_id,
                    filled=bool(ent.fields.get(attr.attribute_id, "").strip()),
                    verified=any(o.evidence_id in verified_ids for o in obs),
                    n_sources=len({o.source_url for o in obs if o.source_url}),
                )
            )
    return cells


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _attribute_coverage(
    attr: Attribute, frame_cells: list[FieldCell]
) -> AttributeCoverage:
    cells = [c for c in frame_cells if c.attribute_id == attr.attribute_id]
    filled = [c for c in cells if c.filled]
    verified = [c for c in filled if c.verified]
    return AttributeCoverage(
        attribute_id=attr.attribute_id,
        name=attr.name or attr.attribute_id,
        required=attr.required,
        n_filled=len(filled),
        n_verified=len(verified),
        fill_rate=_rate(len(filled), len(cells)),
        verified_rate=_rate(len(verified), len(filled)),
    )


def coverage(
    entities: list[Entity],
    attributes: list[Attribute],
    cells: list[FieldCell],
    *,
    expected_count: int | None,
) -> CoverageReport:
    """Recall against the frame plus per-field fill and verified rates.

    Recall is ``found / expected`` when ``expected_count`` is set, else ``None``
    and the caller reads the ``saturating`` discovery curve instead. Rates are
    over in-frame entities only; out-of-frame rows never inflate coverage.
    """
    in_frame = [e for e in entities if e.in_frame]
    found = len(in_frame)
    in_frame_ids = {e.entity_id for e in in_frame}
    recall = (
        round(found / expected_count, 4)
        if expected_count and expected_count > 0
        else None
    )

    new_by_pass: dict[int, int] = {}
    for ent in in_frame:
        # first_pass 0 means no dated observation yet (a hand-seeded roster
        # row not discovered in any pass); it is not a real point on the
        # discovery curve, so it never becomes a phantom "pass 0" bucket.
        if ent.first_pass:
            new_by_pass[ent.first_pass] = new_by_pass.get(ent.first_pass, 0) + 1
    saturating = sorted(new_by_pass.items())

    frame_cells = [c for c in cells if c.entity_id in in_frame_ids]
    filled = [c for c in frame_cells if c.filled]
    verified = [c for c in filled if c.verified]
    field_fill = _rate(len(filled), len(frame_cells))
    field_verified = _rate(len(verified), len(filled))

    per_attribute = [_attribute_coverage(attr, frame_cells) for attr in attributes]

    required_ids = {a.attribute_id for a in attributes if a.required}
    thin_entities = sorted(
        c.entity_id
        for c in frame_cells
        if c.attribute_id in required_ids and not c.filled
    )
    # De-dup while keeping the sorted order (an entity thin on several fields).
    thin_entities = list(dict.fromkeys(thin_entities))

    return CoverageReport(
        expected=expected_count,
        found=found,
        recall=recall,
        saturating=saturating,
        field_fill=field_fill,
        field_verified=field_verified,
        per_attribute=per_attribute,
        thin_entities=thin_entities,
    )
