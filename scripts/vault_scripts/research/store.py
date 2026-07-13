# pyright: reportAny=false, reportExplicitAny=false
# Vendored research harness: this module reads its CSV store and TOML config, boundaries where the
# stdlib hands back `Any`. reportAny/reportExplicitAny are above
# basedpyright's standard strict (which this file passes); every other
# strict check still applies.
"""Topic store: per-mode CSV schemas, loading, and integrity validation.

A topic directory holds ``research.toml`` plus ``data/*.csv``. The topic's
``mode`` selects its schema from ``MODE_SCHEMAS``, the single source of schema
truth: each mode names its core CSVs, their required columns, and its
integrity validators. Extra columns and extra ``data/*.csv`` files are allowed
and pass through to the Sheet mirror untouched.
"""

from collections.abc import Callable
import csv
from dataclasses import dataclass
from datetime import datetime
import difflib
from pathlib import Path
import tomllib
from typing import Any

from vault_scripts.research import certainty, coverage, magnitude
from vault_scripts.research._output import DATE_FMT
from vault_scripts.research.confidence import (
    CELL_SEP,
    DIV_SUFFIX,
    REF_SUFFIX,
    VOID_ID,
    ConfidenceParams,
)

DATA_DIR = "data"
CONFIG_NAME = "research.toml"

# The five research shapes; each earns its place by carrying a distinct
# scorer (docs/backlog/v0.3.x.md). A topic records its mode in research.toml.
# A mode is implemented once it has a row in MODE_SCHEMAS (defined after the
# validators below); a recognized but unimplemented mode is rejected at load
# so it can never validate or score against another mode's schema.
MODE_NAMES: frozenset[str] = frozenset({"map", "verify", "rank", "find", "estimate"})

# Two unit strings this similar almost certainly name the same unit and split
# its corroboration count; borrowed from munin's drift cutoff.
_NEAR_MISS_RATIO = 0.85

TAXONOMY_CSV = "taxonomy.csv"
EVIDENCE_CSV = "evidence.csv"
SOURCES_CSV = "sources.csv"
INDIVIDUALS_CSV = "individuals.csv"
CLAIMS_CSV = "claims.csv"  # verify: the claim list
CANDIDATES_CSV = "candidates.csv"  # rank: the options being compared
CRITERIA_CSV = "criteria.csv"  # rank: the weighted rubric
ENTITIES_CSV = "entities.csv"  # find: the roster (entity x attribute, wide)
ATTRIBUTES_CSV = "attributes.csv"  # find: the fields to extract per entity
FACTORS_CSV = "factors.csv"  # estimate: the decomposed quantity factors
CITATIONS_CSV = (
    "citations.csv"  # verify/rank/find: verdicts written by `research verify`
)
GOLD_CSV = "gold.csv"  # calibrate: human-authored labels keyed by the mode's item id

# individuals.csv validation_status values that count as primary validation.
_VALIDATED_STATUSES = {"validated", "confirmed", "verified"}


@dataclass(frozen=True)
class TopicConfig:
    slug: str
    title: str
    mode: str
    unit_noun: str
    category_prefix: str
    units: tuple[str, ...]
    params: ConfidenceParams
    primary_source_types: tuple[str, ...]
    certainty_params: certainty.CertaintyParams  # verify/rank per-source certainty
    rank_blocker_threshold: float  # rank: a blocker below this de-ranks a candidate
    find_frame: str  # find: the named, bounded population being enumerated
    find_expected_count: int | None  # find: frame size for recall, if known
    estimate_ci: float  # estimate: reported interval width (%)
    estimate_mc_samples: int  # estimate: Monte Carlo draws for the fallback path
    estimate_mc_seed: int  # estimate: fixed seed keeps Monte Carlo reproducible
    sheet_id: str
    auth: str


@dataclass(frozen=True)
class Table:
    """One loaded CSV: column order preserved, rows as dicts."""

    name: str
    columns: tuple[str, ...]
    rows: list[dict[str, str]]


@dataclass(frozen=True)
class Topic:
    root: Path
    config: TopicConfig
    tables: dict[str, Table]  # keyed by filename, core CSVs first

    @property
    def taxonomy_ids(self) -> list[str]:
        return [r["category_id"] for r in self.tables[TAXONOMY_CSV].rows]

    def evidence_pairs(self) -> list[tuple[str, str]]:
        """(unit, category_id) pairs for the confidence engine."""
        return [(r["unit"], r["category_id"]) for r in self.tables[EVIDENCE_CSV].rows]

    def verify_evidence(self) -> list[certainty.Evidence]:
        """Evidence rows for the certainty engine (verify mode). Keyed by
        ``claim_id``; ``VOID`` rows are dropped, ``evidence_id`` is preserved so
        the citation pass can address rows individually."""
        return self._certainty_evidence("claim_id")

    def rank_evidence(self) -> list[certainty.Evidence]:
        """Evidence rows for the certainty engine (rank mode). Keyed by
        ``cell_id`` (``<candidate_id>--<criterion_id>``); otherwise identical to
        ``verify_evidence``."""
        return self._certainty_evidence("cell_id")

    def rank_candidates(self) -> list[certainty.Candidate]:
        return [
            certainty.Candidate(id=r["candidate_id"], name=r.get("name", ""))
            for r in self.tables[CANDIDATES_CSV].rows
        ]

    def rank_criteria(self) -> list[certainty.Criterion]:
        return [
            certainty.Criterion(
                id=r["criterion_id"],
                weight=_as_float(r.get("weight", ""), 1.0),
                tier=r.get("tier", "should"),
            )
            for r in self.tables[CRITERIA_CSV].rows
        ]

    def _certainty_evidence(self, key_col: str) -> list[certainty.Evidence]:
        return [
            certainty.Evidence(
                evidence_id=r.get("evidence_id", ""),
                claim_id=r.get(key_col, ""),
                source_url=r.get("source_url", ""),
                source_tier=r.get("source_tier", ""),
                strength=r.get("strength", ""),
                bearing=r.get("bearing", ""),
                quote=r.get("quote", ""),
            )
            for r in self.tables[EVIDENCE_CSV].rows
            if r.get(key_col, "") != VOID_ID
        ]

    def find_attributes(self) -> list[coverage.Attribute]:
        """The fields to extract per entity (find mode)."""
        return [
            coverage.Attribute(
                attribute_id=r["attribute_id"],
                name=r.get("name", ""),
                required=_as_bool(r.get("required", "")),
            )
            for r in self.tables[ATTRIBUTES_CSV].rows
        ]

    def find_observations(self) -> list[coverage.FieldObservation]:
        """Sourced cell observations for the coverage engine (find mode), keyed
        by ``cell_id`` (``<entity_id>--<attribute_id>``); ``VOID`` rows dropped."""
        return [
            coverage.FieldObservation(
                cell_id=r.get("cell_id", ""),
                evidence_id=r.get("evidence_id", ""),
                pass_num=int(r["pass"]) if r.get("pass", "").isdigit() else 0,
                source_url=r.get("source_url", ""),
            )
            for r in self.tables[EVIDENCE_CSV].rows
            if r.get("cell_id", "") != VOID_ID
        ]

    def find_entities(self) -> list[coverage.Entity]:
        """The roster rows (find mode). Attribute values are read from the
        matching wide columns; ``first_pass`` is the earliest pass that sourced
        the entity, for the discovery curve."""
        attribute_ids = [r["attribute_id"] for r in self.tables[ATTRIBUTES_CSV].rows]
        first_pass: dict[str, int] = {}
        for obs in self.find_observations():
            ent = obs.cell_id.partition(CELL_SEP)[0]
            if obs.pass_num and obs.pass_num < first_pass.get(ent, 1 << 30):
                first_pass[ent] = obs.pass_num
        return [
            coverage.Entity(
                entity_id=r["entity_id"],
                name=r.get("name", ""),
                in_frame=_as_bool(r.get("in_frame", "")),
                fields={aid: r.get(aid, "") for aid in attribute_ids},
                first_pass=first_pass.get(r["entity_id"], 0),
            )
            for r in self.tables[ENTITIES_CSV].rows
        ]

    def estimate_factors(self) -> list[magnitude.Factor]:
        """The decomposed quantity factors (estimate mode)."""
        return [
            magnitude.Factor(
                factor_id=r["factor_id"],
                name=r.get("name", ""),
                op=r.get("op", "") or "mul",
                low=_as_float(r.get("low", ""), 0.0),
                high=_as_float(r.get("high", ""), 0.0),
                mid=_as_float(r.get("mid", ""), 0.0),
                distribution=r.get("distribution", "") or "lognormal",
            )
            for r in self.tables[FACTORS_CSV].rows
        ]


@dataclass(frozen=True)
class Issue:
    file: str
    row: int | None  # 1-based CSV line number (header = 1), None for file-level
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.file, "row": self.row, "message": self.message}


# A deep integrity pass: appends to errors/warnings, returns nothing. Only run
# once every core CSV is present with its required columns.
Validator = Callable[[Topic, list[Issue], list[Issue]], None]


@dataclass(frozen=True)
class ModeSchema:
    """One mode's store shape: core CSVs, their id columns, and validators.

    The registry row is a mode's whole schema contract; adding a mode means
    adding one entry to ``MODE_SCHEMAS``, never editing branching logic in
    ``check``/``load_topic``/``scaffold``.
    """

    core_columns: dict[str, tuple[str, ...]]
    id_columns: dict[str, str]
    validators: tuple[Validator, ...]


def load_config(root: Path) -> TopicConfig:
    path = root / CONFIG_NAME
    if not path.exists():
        raise FileNotFoundError(f"No {CONFIG_NAME} in {root} (not a topic directory?)")
    with path.open("rb") as f:
        raw = tomllib.load(f)
    topic = raw.get("topic", {})
    conf = raw.get("confidence", {})
    verify = raw.get("verify", {})
    rank = raw.get("rank", {})
    find = raw.get("find", {})
    estimate = raw.get("estimate", {})
    sheets = raw.get("sheets", {})
    mode = str(topic.get("mode", "map"))
    validate_mode(mode)
    defaults = certainty.CertaintyParams()
    raw_expected = find.get("expected_count")
    return TopicConfig(
        slug=str(topic.get("slug", "")),
        title=str(topic.get("title", "")),
        mode=mode,
        unit_noun=str(topic.get("unit_noun", "unit")),
        category_prefix=str(topic.get("category_prefix", "C")),
        units=tuple(str(u) for u in topic.get("units", [])),
        params=ConfidenceParams(
            step=float(conf.get("step", 0.10)),
            cap=float(conf.get("cap", 0.95)),
            primary_ceiling=float(conf.get("primary_ceiling", 0.84)),
        ),
        primary_source_types=tuple(
            str(t) for t in conf.get("primary_source_types", ["Primary source"])
        ),
        certainty_params=certainty.CertaintyParams(
            prior=float(verify.get("prior", defaults.prior)),
            ceiling=float(verify.get("ceiling", defaults.ceiling)),
            ceiling_tier=str(verify.get("ceiling_tier", defaults.ceiling_tier)),
        ),
        rank_blocker_threshold=float(rank.get("blocker_threshold", 50.0)),
        find_frame=str(find.get("frame", "")),
        find_expected_count=(
            int(raw_expected) if raw_expected not in {None, ""} else None
        ),
        estimate_ci=float(estimate.get("ci", 90.0)),
        estimate_mc_samples=int(estimate.get("mc_samples", 10000)),
        estimate_mc_seed=int(estimate.get("mc_seed", 1729)),
        sheet_id=str(sheets.get("sheet_id", "")),
        auth=str(sheets.get("auth", "oauth")),
    )


def validate_mode(mode: str) -> None:
    """Reject unknown modes outright and known-but-unimplemented ones clearly."""
    if mode not in MODE_NAMES:
        raise ValueError(
            f"unknown mode {mode!r} in {CONFIG_NAME}; "
            f"expected one of: {', '.join(sorted(MODE_NAMES))}"
        )
    if mode not in MODE_SCHEMAS:
        raise ValueError(
            f"mode {mode!r} is not implemented yet "
            f"(implemented: {', '.join(sorted(MODE_SCHEMAS))}; "
            f"the rest arrive across the v0.3.x releases)"
        )


def _read_csv(path: Path) -> Table:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = tuple(reader.fieldnames or ())
        rows = [
            {k: (v or "") for k, v in row.items() if k is not None} for row in reader
        ]
    return Table(name=path.name, columns=columns, rows=rows)


def load_topic(root: Path) -> Topic:
    """Load a topic directory. Missing core CSVs surface later via check()."""
    config = load_config(root)
    data = root / DATA_DIR
    tables: dict[str, Table] = {}
    core = list(MODE_SCHEMAS[config.mode].core_columns)
    extras = sorted(p.name for p in data.glob("*.csv") if p.name not in core)
    for name in [*core, *extras]:
        path = data / name
        if path.exists():
            tables[name] = _read_csv(path)
    return Topic(root=root, config=config, tables=tables)


def check(topic: Topic) -> tuple[list[Issue], list[Issue]]:
    """Validate the store against the topic mode's schema.

    Returns (errors, warnings)."""
    schema = MODE_SCHEMAS[topic.config.mode]
    errors: list[Issue] = []
    warnings: list[Issue] = []

    errors.extend(
        Issue(name, None, "required file missing")
        for name in schema.core_columns
        if name not in topic.tables
    )

    for name, required in schema.core_columns.items():
        table = topic.tables.get(name)
        if table is None:
            continue
        missing = [c for c in required if c not in table.columns]
        if missing:
            errors.append(Issue(name, 1, f"missing required columns: {missing}"))

    for name, table in topic.tables.items():
        _check_ids(table, name, schema.id_columns, errors)

    if all(
        name in topic.tables and not _columns_missing(topic.tables[name], required)
        for name, required in schema.core_columns.items()
    ):
        for validator in schema.validators:
            validator(topic, errors, warnings)

    return errors, warnings


def _columns_missing(table: Table, required: tuple[str, ...]) -> bool:
    return any(c not in table.columns for c in required)


def _check_ids(
    table: Table, name: str, id_columns: dict[str, str], errors: list[Issue]
) -> None:
    """Unique-id check: core id columns, plus first column of *_id extras."""
    id_col = id_columns.get(name)
    if id_col is None:
        if not table.columns:
            errors.append(Issue(name, 1, "empty header row"))
            return
        first = table.columns[0]
        if not first.endswith("_id"):
            return
        id_col = first
    if id_col not in table.columns:
        return
    seen: dict[str, int] = {}
    for i, row in enumerate(table.rows, start=2):
        value = row.get(id_col, "")
        if not value:
            errors.append(Issue(name, i, f"empty {id_col}"))
        elif value in seen and value != VOID_ID:
            errors.append(
                Issue(
                    name,
                    i,
                    f"duplicate {id_col} {value!r} (first at row {seen[value]})",
                )
            )
        else:
            seen.setdefault(value, i)


def _check_evidence(topic: Topic, errors: list[Issue], warnings: list[Issue]) -> None:
    name = EVIDENCE_CSV
    taxonomy_ids = set(topic.taxonomy_ids)
    canonical = set(topic.config.units)
    seen_units: set[str] = set()

    for i, row in enumerate(topic.tables[name].rows, start=2):
        cid = row["category_id"]
        if cid != VOID_ID:
            base = cid.removesuffix(DIV_SUFFIX).removesuffix(REF_SUFFIX)
            if base not in taxonomy_ids:
                errors.append(Issue(name, i, f"unknown category_id {cid!r}"))
            if not row["finding_verbatim"]:
                errors.append(Issue(name, i, "empty finding_verbatim"))
            if not row["source_url"]:
                errors.append(Issue(name, i, "empty source_url on a non-VOID row"))

        unit = row["unit"]
        if not unit and cid != VOID_ID:
            errors.append(Issue(name, i, "empty unit"))
        elif unit:
            if canonical and unit not in canonical:
                errors.append(
                    Issue(name, i, f"unit {unit!r} not in research.toml units")
                )
            seen_units.add(unit)

        if not row["pass"].isdigit() or int(row["pass"]) < 1:
            errors.append(
                Issue(name, i, f"pass must be a positive integer, got {row['pass']!r}")
            )
        try:
            datetime.strptime(row["date_captured"], DATE_FMT)  # noqa: DTZ007
        except ValueError:
            errors.append(
                Issue(
                    name,
                    i,
                    f"date_captured must be YYYY-MM-DD, got {row['date_captured']!r}",
                )
            )

    if not canonical:
        _warn_unit_collisions(seen_units, warnings)
        _warn_unit_near_miss(seen_units, warnings)


def _warn_unit_collisions(units: set[str], warnings: list[Issue]) -> None:
    """With no canonical list, near-identical unit strings split the counts."""
    by_folded: dict[str, list[str]] = {}
    for unit in units:
        by_folded.setdefault(unit.casefold().strip(), []).append(unit)
    warnings.extend(
        Issue(
            EVIDENCE_CSV,
            None,
            f"unit strings differ only by case/whitespace: {sorted(variants)}",
        )
        for variants in by_folded.values()
        if len(variants) > 1
    )


def _warn_unit_near_miss(units: set[str], warnings: list[Issue]) -> None:
    """Distinct-but-similar unit strings (``Acme Inc`` vs ``Acme Inc.``) split a
    unit's corroboration. Case/whitespace-only pairs are already reported by
    ``_warn_unit_collisions``; this catches the fuzzier near-duplicates."""
    reps: dict[str, str] = {}
    for unit in sorted(units):
        reps.setdefault(unit.casefold().strip(), unit)
    keys = list(reps)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if ratio >= _NEAR_MISS_RATIO:
                warnings.append(
                    Issue(
                        EVIDENCE_CSV,
                        None,
                        f"unit strings are near-duplicates (ratio {ratio:.2f}) and "
                        f"may split the count: {sorted((reps[a], reps[b]))}",
                    )
                )


def _check_coverage(topic: Topic, _errors: list[Issue], warnings: list[Issue]) -> None:
    """Flag taxonomy categories whose evidence contradicts them: audit
    candidates surfaced mechanically instead of waiting for the every-3rd-pass
    eyeball. Anchored on divergence, so a fresh topic with empty categories
    stays clean (empty is normal for many passes; contested is not)."""
    taxonomy_ids = topic.taxonomy_ids
    supporting: dict[str, set[str]] = {cid: set() for cid in taxonomy_ids}
    diverging: dict[str, set[str]] = {cid: set() for cid in taxonomy_ids}
    for row in topic.tables[EVIDENCE_CSV].rows:
        cid = row["category_id"]
        if cid in supporting:
            supporting[cid].add(row["unit"])
        elif cid.endswith(DIV_SUFFIX):
            base = cid.removesuffix(DIV_SUFFIX)
            if base in diverging:
                diverging[base].add(row["unit"])
    for cid in taxonomy_ids:
        sup = len(supporting[cid])
        div = len(diverging[cid])
        if div and div >= sup:
            detail = (
                f"only divergent evidence ({div} diverging unit(s), none supporting)"
                if sup == 0
                else f"contested ({div} diverging >= {sup} supporting unit(s))"
            )
            warnings.append(Issue(TAXONOMY_CSV, None, f"category {cid!r}: {detail}"))


def _check_pass_date(
    name: str, i: int, row: dict[str, str], errors: list[Issue]
) -> None:
    """The `pass` (positive int) and `date_captured` (YYYY-MM-DD) checks shared
    by every evidence-carrying mode. Kept out of map's `_check_evidence` so map's
    issue ordering stays pinned."""
    if not row.get("pass", "").isdigit() or int(row["pass"]) < 1:
        errors.append(
            Issue(
                name, i, f"pass must be a positive integer, got {row.get('pass', '')!r}"
            )
        )
    try:
        datetime.strptime(row.get("date_captured", ""), DATE_FMT)  # noqa: DTZ007
    except ValueError:
        errors.append(
            Issue(
                name,
                i,
                f"date_captured must be YYYY-MM-DD, got {row.get('date_captured', '')!r}",
            )
        )


def _check_source_vocab(
    name: str, i: int, row: dict[str, str], errors: list[Issue]
) -> None:
    """Reject unknown source_tier / strength / bearing values on a source-weighted
    evidence row (verify and rank)."""
    tier = row.get("source_tier", "")
    if tier not in certainty.SOURCE_TIERS:
        errors.append(Issue(name, i, f"unknown source_tier {tier!r}"))
    strength = row.get("strength", "")
    if strength not in certainty.STRENGTHS:
        errors.append(Issue(name, i, f"unknown strength {strength!r}"))
    bearing = row.get("bearing", "")
    if bearing not in certainty.BEARINGS:
        errors.append(Issue(name, i, f"unknown bearing {bearing!r}"))


def _check_sourced_row(
    name: str, i: int, row: dict[str, str], errors: list[Issue], *, vocab: bool
) -> None:
    """The non-VOID evidence-row checks shared by verify/rank/find/estimate: a
    quote and source_url must be present, and pass/date must be well-formed.
    ``vocab`` adds the source_tier/strength/bearing vocabulary check (verify and
    rank, whose evidence is source-weighted)."""
    if not row["source_url"]:
        errors.append(Issue(name, i, "empty source_url on a non-VOID row"))
    if not row["quote"]:
        errors.append(Issue(name, i, "empty quote on a non-VOID row"))
    if vocab:
        _check_source_vocab(name, i, row, errors)
    _check_pass_date(name, i, row, errors)


def _check_verify_evidence(
    topic: Topic, errors: list[Issue], _warnings: list[Issue]
) -> None:
    name = EVIDENCE_CSV
    claim_ids = {r["claim_id"] for r in topic.tables[CLAIMS_CSV].rows}
    for i, row in enumerate(topic.tables[name].rows, start=2):
        cid = row["claim_id"]
        if cid == VOID_ID:
            continue
        if cid not in claim_ids:
            errors.append(Issue(name, i, f"unknown claim_id {cid!r}"))
        _check_sourced_row(name, i, row, errors, vocab=True)


def _as_float(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


_TRUTHY = {"yes", "true", "1", "y", "t"}


def _as_bool(value: str) -> bool:
    return value.strip().casefold() in _TRUTHY


def _check_rank(topic: Topic, errors: list[Issue], _warnings: list[Issue]) -> None:
    candidate_ids = {r["candidate_id"] for r in topic.tables[CANDIDATES_CSV].rows}
    criterion_ids = {r["criterion_id"] for r in topic.tables[CRITERIA_CSV].rows}

    for i, row in enumerate(topic.tables[CRITERIA_CSV].rows, start=2):
        tier = row.get("tier", "")
        if tier not in certainty.CRITERION_TIERS:
            errors.append(Issue(CRITERIA_CSV, i, f"unknown tier {tier!r}"))
        weight = row.get("weight", "")
        try:
            if float(weight) <= 0:
                errors.append(
                    Issue(CRITERIA_CSV, i, f"weight must be positive, got {weight!r}")
                )
        except ValueError:
            errors.append(
                Issue(CRITERIA_CSV, i, f"weight must be a number, got {weight!r}")
            )

    name = EVIDENCE_CSV
    for i, row in enumerate(topic.tables[name].rows, start=2):
        cell = row["cell_id"]
        if cell == VOID_ID:
            continue
        cand, sep, crit = cell.partition(CELL_SEP)
        if not sep or cand not in candidate_ids or crit not in criterion_ids:
            errors.append(
                Issue(
                    name, i, f"cell_id {cell!r} is not a <candidate>--<criterion> cell"
                )
            )
        _check_sourced_row(name, i, row, errors, vocab=True)


def _check_find(topic: Topic, errors: list[Issue], _warnings: list[Issue]) -> None:
    entity_ids = {r["entity_id"] for r in topic.tables[ENTITIES_CSV].rows}
    attribute_ids = {r["attribute_id"] for r in topic.tables[ATTRIBUTES_CSV].rows}

    # Each declared attribute needs a matching wide column on the roster, or its
    # values read as empty for every entity and the coverage report silently
    # shows 0% fill on data that is actually present under a mis-named column.
    entity_columns = set(topic.tables[ENTITIES_CSV].columns)
    errors.extend(
        Issue(
            ATTRIBUTES_CSV,
            None,
            f"attribute {missing!r} has no matching column in {ENTITIES_CSV}",
        )
        for missing in sorted(attribute_ids - entity_columns)
    )

    name = EVIDENCE_CSV
    for i, row in enumerate(topic.tables[name].rows, start=2):
        cell = row["cell_id"]
        if cell == VOID_ID:
            continue
        ent, sep, attr = cell.partition(CELL_SEP)
        if not sep or ent not in entity_ids or attr not in attribute_ids:
            errors.append(
                Issue(name, i, f"cell_id {cell!r} is not an <entity>--<attribute> cell")
            )
        _check_sourced_row(name, i, row, errors, vocab=False)


def _check_factor(i: int, row: dict[str, str], errors: list[Issue]) -> None:
    """Validate one estimate factor row: op/distribution vocab and a positive,
    ordered low/high (lognormal) with an optional positive mid."""
    op = row.get("op", "") or "mul"
    if op not in magnitude.OPS:
        errors.append(Issue(FACTORS_CSV, i, f"unknown op {op!r}"))
    dist = row.get("distribution", "") or "lognormal"
    if dist not in magnitude.DISTRIBUTIONS:
        errors.append(Issue(FACTORS_CSV, i, f"unknown distribution {dist!r}"))
    low, high = row.get("low", ""), row.get("high", "")
    try:
        lo, hi = float(low), float(high)
    except ValueError:
        errors.append(
            Issue(FACTORS_CSV, i, f"low/high must be numbers, got {low!r}/{high!r}")
        )
        return
    if lo <= 0 or hi <= 0:
        errors.append(Issue(FACTORS_CSV, i, "low/high must be positive (lognormal)"))
    elif lo > hi:
        errors.append(Issue(FACTORS_CSV, i, f"low {lo} exceeds high {hi}"))
    mid = row.get("mid", "")
    if mid:
        try:
            if float(mid) <= 0:
                errors.append(Issue(FACTORS_CSV, i, "mid must be positive"))
        except ValueError:
            errors.append(Issue(FACTORS_CSV, i, f"mid must be a number, got {mid!r}"))


def _check_estimate(topic: Topic, errors: list[Issue], _warnings: list[Issue]) -> None:
    factor_ids = {r["factor_id"] for r in topic.tables[FACTORS_CSV].rows}

    for i, row in enumerate(topic.tables[FACTORS_CSV].rows, start=2):
        _check_factor(i, row, errors)

    name = EVIDENCE_CSV
    for i, row in enumerate(topic.tables[name].rows, start=2):
        fid = row["factor_id"]
        if fid == VOID_ID:
            continue
        if fid not in factor_ids:
            errors.append(Issue(name, i, f"unknown factor_id {fid!r}"))
        _check_sourced_row(name, i, row, errors, vocab=False)


def _check_sources(topic: Topic, _errors: list[Issue], warnings: list[Issue]) -> None:
    seen: dict[str, int] = {}
    for i, row in enumerate(topic.tables[SOURCES_CSV].rows, start=2):
        url = row.get("url", "")
        if url and url in seen:
            warnings.append(
                Issue(SOURCES_CSV, i, f"duplicate url (first at row {seen[url]})")
            )
        elif url:
            seen[url] = i


# The per-mode schema registry, the extension point every later mode adds a
# row to. `map`: a taxonomy categorized across a sampled unit population.
# Validator order is load-bearing for stable issue ordering.
MODE_SCHEMAS: dict[str, ModeSchema] = {
    "map": ModeSchema(
        core_columns={
            TAXONOMY_CSV: (
                "category_id",
                "name",
                "definition",
                "boundary",
                "examples",
                "synthesis_notes",
                "notes_coverage",
            ),
            EVIDENCE_CSV: (
                "evidence_id",
                "pass",
                "date_captured",
                "unit",
                "category_id",
                "finding_verbatim",
                "detail_quote",
                "source_type",
                "source_url",
                "published_date",
                "notes",
            ),
            SOURCES_CSV: (
                "source_id",
                "unit",
                "title",
                "source_type",
                "pass",
                "url",
            ),
        },
        id_columns={
            TAXONOMY_CSV: "category_id",
            EVIDENCE_CSV: "evidence_id",
            SOURCES_CSV: "source_id",
        },
        validators=(_check_evidence, _check_sources, _check_coverage),
    ),
    "verify": ModeSchema(
        core_columns={
            CLAIMS_CSV: ("claim_id", "claim", "notes"),
            EVIDENCE_CSV: (
                "evidence_id",
                "pass",
                "date_captured",
                "claim_id",
                "source_tier",
                "strength",
                "bearing",
                "quote",
                "source_type",
                "source_url",
                "published_date",
                "notes",
            ),
        },
        id_columns={
            CLAIMS_CSV: "claim_id",
            EVIDENCE_CSV: "evidence_id",
        },
        validators=(_check_verify_evidence,),
    ),
    "rank": ModeSchema(
        core_columns={
            CANDIDATES_CSV: ("candidate_id", "name"),
            CRITERIA_CSV: ("criterion_id", "text", "weight", "tier"),
            EVIDENCE_CSV: (
                "evidence_id",
                "pass",
                "date_captured",
                "cell_id",
                "source_tier",
                "strength",
                "bearing",
                "quote",
                "source_type",
                "source_url",
                "published_date",
                "notes",
            ),
        },
        id_columns={
            CANDIDATES_CSV: "candidate_id",
            CRITERIA_CSV: "criterion_id",
            EVIDENCE_CSV: "evidence_id",
        },
        validators=(_check_rank,),
    ),
    "find": ModeSchema(
        core_columns={
            ENTITIES_CSV: ("entity_id", "name", "in_frame"),
            ATTRIBUTES_CSV: ("attribute_id", "name", "required"),
            EVIDENCE_CSV: (
                "evidence_id",
                "pass",
                "date_captured",
                "cell_id",
                "quote",
                "source_type",
                "source_url",
                "published_date",
                "notes",
            ),
        },
        id_columns={
            ENTITIES_CSV: "entity_id",
            ATTRIBUTES_CSV: "attribute_id",
            EVIDENCE_CSV: "evidence_id",
        },
        validators=(_check_find,),
    ),
    "estimate": ModeSchema(
        core_columns={
            FACTORS_CSV: (
                "factor_id",
                "name",
                "op",
                "low",
                "mid",
                "high",
                "distribution",
                "notes",
            ),
            EVIDENCE_CSV: (
                "evidence_id",
                "pass",
                "date_captured",
                "factor_id",
                "quote",
                "source_type",
                "source_url",
                "published_date",
                "notes",
            ),
        },
        id_columns={
            FACTORS_CSV: "factor_id",
            EVIDENCE_CSV: "evidence_id",
        },
        validators=(_check_estimate,),
    ),
}


def primary_backed_categories(topic: Topic) -> set[str]:
    """Taxonomy categories that a primary source supports, for the confidence
    ceiling. A category qualifies when a supporting evidence row carries a
    primary ``source_type`` (per ``research.toml``), or, as the optional
    individuals-plane bridge, when a supporting row's unit has a validated
    entry in ``individuals.csv``. Backing can only be added, never removed."""
    taxonomy = set(topic.taxonomy_ids)
    primary_types = {t.casefold() for t in topic.config.primary_source_types}
    validated_units = _validated_units(topic)
    backed: set[str] = set()
    evidence = topic.tables.get(EVIDENCE_CSV)
    if evidence is None:
        return backed
    for row in evidence.rows:
        cid = row["category_id"]
        if cid not in taxonomy:
            continue
        is_primary_source = row.get("source_type", "").casefold() in primary_types
        has_validated_unit = bool(validated_units) and row["unit"] in validated_units
        if is_primary_source or has_validated_unit:
            backed.add(cid)
    return backed


def _validated_units(topic: Topic) -> set[str]:
    """Units with a validated entry in the optional ``individuals.csv``."""
    table = topic.tables.get(INDIVIDUALS_CSV)
    if table is None or "unit" not in table.columns:
        return set()
    if "validation_status" not in table.columns:
        return set()
    return {
        row["unit"]
        for row in table.rows
        if row.get("validation_status", "").casefold() in _VALIDATED_STATUSES
    }


def counts(topic: Topic) -> dict[str, Any]:
    """Row counts and coverage totals for CLI envelopes."""
    evidence = topic.tables.get(EVIDENCE_CSV)
    rows = evidence.rows if evidence else []
    passes = [int(r["pass"]) for r in rows if r.get("pass", "").isdigit()]
    return {
        "rows": {name: len(t.rows) for name, t in topic.tables.items()},
        # `unit` is map-shaped; verify/rank evidence has no unit column, so the
        # count is simply 0 there rather than a KeyError.
        "distinct_units": len({r["unit"] for r in rows if r.get("unit")}),
        "max_pass": max(passes) if passes else 0,
    }
