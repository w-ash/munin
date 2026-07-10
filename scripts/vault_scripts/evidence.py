"""Standardized source-to-certainty scoring for durable, checkpointed research.

Back-ported from the provider-search exercise. Two jobs:

1. **Durability (write-as-you-go).** Research agents append each finding to an
   append-only JSONL shard the moment they produce it, so a stalled or
   disconnected agent loses one in-flight item, not the whole run. Shards live in
   a run directory under tmp (outside iCloud, so the vault's iCloud write-race
   does not apply); ``merge`` is idempotent, so a resumed run recombines cleanly.

2. **Numeric grounding (weight of evidence).** Each source moves a claim's
   certainty by a fixed, tier-based log-likelihood increment (decibans). Updates
   accumulate in log-odds, which is additive and order-independent, so
   independent agents' evidence composes by summation and results are comparable
   across agents and runs. Certainty maps to calibrated confidence bands; a
   ceiling gate blocks the top bands without a primary source. This is a
   consistency convention, not an empirically calibrated probability.

See ``.claude/rules/evidence.md`` for the full schema and rubric.

Beyond append/merge/score, three mechanical passes keep agents honest:

- ``verify-citations`` fetches every cited URL and checks the quote actually
  appears there (Wayback fallback separates link rot from fabrication); ``score``
  and ``rank`` then exclude quote-missing items and downgrade unverified ones.
- ``rank`` rolls per-claim certainties up into per-candidate fit scores against a
  weighted rubric (ranking mode), with blocker gating and weakest-link reporting.
- ``check`` reconciles shard claim ids against the run manifest so slug drift
  between agents surfaces instead of silently fragmenting the evidence.

Examples:

    scripts/vault-tool evidence rubric
    scripts/vault-tool evidence append --shard /tmp/run/agent-1.jsonl \\
        --json '{"claim_id":"c1","source_url":"https://x.org","source_tier":"primary","bearing":"supports","strength":"strong","quote":"..."}'
    scripts/vault-tool evidence manifest --run-dir /tmp/run --json '{"question":"...","claims":[...]}'
    scripts/vault-tool evidence merge --run-dir /tmp/run --out /tmp/run/merged.jsonl
    scripts/vault-tool evidence verify-citations --run-dir /tmp/run
    scripts/vault-tool evidence check --run-dir /tmp/run
    scripts/vault-tool evidence score --run-dir /tmp/run --markdown
    scripts/vault-tool evidence rank --run-dir /tmp/run --rubric /tmp/run/rubric.json --markdown
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import difflib
import hashlib
import html
import math
import operator
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from pydantic import ValidationError

from vault_scripts._cli import CliError, make_envelope, print_json
from vault_scripts._retry import (
    APIError,
    citation_retry,
    request_page,
    request_validated_json,
)
from vault_scripts._types import (
    Band,
    CandidateVerdict,
    CitationCacheEntry,
    CitationRecord,
    CitationStatus,
    ClaimVerdict,
    CriterionScore,
    EvidenceItem,
    ResearchManifest,
    Rubric,
    ScoreDriver,
    SourceTier,
    Strength,
    WaybackAvailable,
)
from vault_scripts._utils import parse_typed_args

_ID_KEY = "target"
_env = make_envelope(_ID_KEY)

# Base weight of evidence (decibans) for a *strong* item of each tier. A deciban
# is 10*log10 of the likelihood ratio; ~10 dB is a 10x update, and a deciban is
# roughly the smallest change in belief a person perceives (Good/Turing).
_TIER_DECIBANS: dict[SourceTier, float] = {
    "primary": 12.0,  # own authorship, peer-reviewed, official record
    "community": 8.0,  # a named human recommendation
    "secondary": 6.0,  # self-authored profile / practice-site copy
    "weak": 2.0,  # aggregator rating, third-party listicle, inference
}
_STRENGTH_MULT: dict[Strength, float] = {"weak": 1 / 3, "moderate": 2 / 3, "strong": 1.0}

# Same-source diminishing returns: the k-th item sharing a host contributes less,
# so one site can't stack certainty by restating itself.
_DOMAIN_FACTORS: tuple[float, ...] = (1.0, 0.5, 0.25)

_LN10 = math.log(10.0)

# Band thresholds (certainty %, minimum for each band, high to low); the ceiling
# cap sits just below "confident" so a claim without a primary source can reach
# "likely" but no higher.
_DEFAULT_PRIOR = 0.5
_DEFAULT_CEILING = 74.0
_DEFAULT_CEILING_TIER: SourceTier = "primary"
_BAND_MIN: dict[Band, float] = {
    "established": 90.0,
    "confident": 75.0,
    "likely": 55.0,
    "tentative": 35.0,
    "speculative": 15.0,
}


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def woe_decibans(item: EvidenceItem) -> float:
    """Signed weight of evidence for one item, in decibans."""
    base = _TIER_DECIBANS[item.source_tier]
    mult = _STRENGTH_MULT[item.strength]
    sign = 1.0 if item.bearing == "supports" else -1.0
    return sign * base * mult


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _band(certainty: float) -> Band:
    for band, low in _BAND_MIN.items():
        if certainty >= low:
            return band
    return "refuted"


def _dedup(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Drop exact duplicates (same source, bearing, quote) so a re-appended shard
    on resume does not double-count."""
    seen: set[tuple[str, str, str]] = set()
    out: list[EvidenceItem] = []
    for it in items:
        key = (it.source_url, it.bearing, it.quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def score_claim(
    items: list[EvidenceItem],
    *,
    prior: float = _DEFAULT_PRIOR,
    ceiling: float = _DEFAULT_CEILING,
    ceiling_tier: SourceTier = _DEFAULT_CEILING_TIER,
) -> ClaimVerdict:
    """Accumulate one claim's evidence into a calibrated certainty. Pure and
    order-independent: log-odds is additive, so shuffling ``items`` cannot change
    the result."""
    uniq = _dedup(items)
    by_domain: dict[str, list[EvidenceItem]] = defaultdict(list)
    for it in uniq:
        by_domain[_domain(it.source_url)].append(it)

    net = 0.0
    drivers: list[ScoreDriver] = []
    for group in by_domain.values():
        ranked = sorted(group, key=lambda x: abs(woe_decibans(x)), reverse=True)
        for i, it in enumerate(ranked):
            factor = _DOMAIN_FACTORS[i] if i < len(_DOMAIN_FACTORS) else _DOMAIN_FACTORS[-1]
            db = woe_decibans(it) * factor
            net += db
            drivers.append(
                ScoreDriver(
                    source_url=it.source_url,
                    source_tier=it.source_tier,
                    bearing=it.bearing,
                    decibans=round(db, 2),
                )
            )

    logodds = _logit(prior) + net / 10.0 * _LN10
    certainty = _sigmoid(logodds) * 100.0

    has_primary_support = any(
        it.bearing == "supports" and it.source_tier == ceiling_tier for it in uniq
    )
    capped = False
    if not has_primary_support and certainty > ceiling:
        certainty = ceiling
        capped = True

    drivers.sort(key=lambda d: abs(d["decibans"]), reverse=True)
    claim_text = next((it.claim for it in uniq if it.claim), "")
    return ClaimVerdict(
        claim_id=uniq[0].claim_id if uniq else "",
        claim=claim_text,
        certainty=round(certainty, 1),
        band=_band(certainty),
        net_decibans=round(net, 2),
        n_sources=len({it.source_url for it in uniq}),
        capped=capped,
        drivers=drivers,
    )


def score_items(
    items: list[EvidenceItem],
    *,
    prior: float = _DEFAULT_PRIOR,
    ceiling: float = _DEFAULT_CEILING,
    ceiling_tier: SourceTier = _DEFAULT_CEILING_TIER,
) -> list[ClaimVerdict]:
    """Group evidence by ``claim_id`` and score each claim, ranked by certainty."""
    by_claim: dict[str, list[EvidenceItem]] = defaultdict(list)
    for it in items:
        by_claim[it.claim_id].append(it)
    verdicts = [
        score_claim(group, prior=prior, ceiling=ceiling, ceiling_tier=ceiling_tier)
        for group in by_claim.values()
    ]
    verdicts.sort(key=operator.itemgetter("certainty"), reverse=True)
    return verdicts


# --- Citation verification (mechanical; agents are asked to check quotes, this
# actually checks them) ---

_WAYBACK_API = "https://archive.org/wayback/available"
_FETCH_HEADERS = {"User-Agent": "munin-evidence-citation-check/2 (personal research tool)"}
# Statuses where the page answered but won't show us content: can't judge the
# quote either way, so the item is "unfetchable", not "dead".
_BLOCKED_STATUSES = {401, 403, 405, 406, 429, 451}
_TEXTY_PREFIXES = ("text/",)
_TEXTY_TYPES = {"application/xhtml+xml", "application/xml", "application/json"}
# Quote matching: word 5-gram shingles; >=60% present counts as found. Absorbs
# small edit distance (typography, ellipses, truncation) without an HTML parser
# or fuzzy-match dependency.
_SHINGLE = 5
_SHINGLE_MIN = 0.6
# First non-success HTTP status (3xx never reaches us: requests follows redirects).
_HTTP_NON_SUCCESS = 300

_TAG_STRIP = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9]+")

_fetch_page = citation_retry(request_page)


def _words(text: str) -> list[str]:
    return _WORD.findall(html.unescape(text).casefold())


def quote_present(quote: str, page: str) -> bool:
    """Does the quoted text appear in the page? Tag-stripped, case- and
    punctuation-insensitive, shingle-tolerant. Pure; the fetch happens elsewhere."""
    stripped = _TAG.sub(" ", _TAG_STRIP.sub(" ", page))
    haystack = f" {' '.join(_words(stripped))} "
    qw = _words(quote)
    if not qw:
        return False
    if len(qw) <= _SHINGLE:
        return f" {' '.join(qw)} " in haystack
    shingles = [" ".join(qw[i : i + _SHINGLE]) for i in range(len(qw) - _SHINGLE + 1)]
    hits = sum(1 for s in shingles if f" {s} " in haystack)
    return hits / len(shingles) >= _SHINGLE_MIN


def _is_texty(content_type: str) -> bool:
    base = content_type.split(";", 1)[0].strip().lower()
    return not base or base in _TEXTY_TYPES or base.startswith(_TEXTY_PREFIXES)


def _cached_fetch(url: str, cache_dir: Path | None, timeout: int) -> tuple[int, str, str]:
    """Fetch a page through the on-disk response cache so a resumed or repeated
    verification pass does not refetch every source."""
    entry_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        entry_path = cache_dir / f"{digest}.json"
        if entry_path.is_file():
            try:
                entry = CitationCacheEntry.model_validate_json(
                    entry_path.read_text(encoding="utf-8")
                )
            except ValidationError:
                pass  # stale/corrupt cache entry: refetch below
            else:
                return entry.status_code, entry.content_type, entry.text
    status, content_type, text = _fetch_page(url, timeout=timeout, headers=_FETCH_HEADERS)
    if entry_path is not None:
        entry = CitationCacheEntry(status_code=status, content_type=content_type, text=text)
        entry_path.write_text(entry.model_dump_json(), encoding="utf-8")
    return status, content_type, text


def _wayback_text(url: str, cache_dir: Path | None, timeout: int) -> str | None:
    """Closest Wayback snapshot's page text, or None when no snapshot exists or
    the archive is unreachable."""
    try:
        avail = citation_retry(request_validated_json)(
            "GET",
            _WAYBACK_API,
            response_model=WaybackAvailable,
            timeout=timeout,
            params={"url": url},
            headers=_FETCH_HEADERS,
        )
    except APIError:
        return None
    closest = avail.archived_snapshots.closest
    if closest is None or not closest.available or not closest.url:
        return None
    try:
        status, content_type, text = _cached_fetch(closest.url, cache_dir, timeout)
    except APIError:
        return None
    if status >= _HTTP_NON_SUCCESS or not _is_texty(content_type):
        return None
    return text


def check_citation(
    url: str, quote: str, *, cache_dir: Path | None, timeout: int
) -> CitationRecord:
    """Mechanically check one (url, quote) pair. See ``CitationRecord`` for the
    status vocabulary; the design principle is that a verifier *agent* being asked
    to check quotes is not the same as the quotes being checked."""
    checked_at = datetime.now(tz=UTC).isoformat(timespec="seconds")

    def rec(
        status: CitationStatus, *, http_status: int | None = None, archived: bool = False
    ) -> CitationRecord:
        return CitationRecord(
            source_url=url,
            quote=quote,
            status=status,
            http_status=http_status,
            archived=archived,
            checked_at=checked_at,
        )

    if not quote.strip():
        return rec("no_quote")
    try:
        status, content_type, text = _cached_fetch(url, cache_dir, timeout)
    except APIError:
        return rec("unfetchable")
    if status < _HTTP_NON_SUCCESS:
        if not _is_texty(content_type):
            return rec("unfetchable", http_status=status)
        if quote_present(quote, text):
            return rec("verified", http_status=status)
        # Live page without the quote: the content may simply have changed, so
        # give the snapshot a chance before calling it missing.
        archived_text = _wayback_text(url, cache_dir, timeout)
        if archived_text is not None and quote_present(quote, archived_text):
            return rec("verified", http_status=status, archived=True)
        return rec("quote_missing", http_status=status)
    if status in _BLOCKED_STATUSES:
        return rec("unfetchable", http_status=status)
    # Hard-dead URL: a snapshot containing the quote is link rot (kept, marked
    # archived); a snapshot without it is the fabrication signal.
    archived_text = _wayback_text(url, cache_dir, timeout)
    if archived_text is None:
        return rec("dead", http_status=status)
    if quote_present(quote, archived_text):
        return rec("verified", http_status=status, archived=True)
    return rec("quote_missing", http_status=status)


# How each citation status feeds back into scoring: fabricated-looking quotes are
# inadmissible in either bearing; merely-unverified sourcing loses one strength
# level so it can still contribute but cannot carry a verdict.
_DOWNGRADE: dict[Strength, Strength] = {"strong": "moderate", "moderate": "weak", "weak": "weak"}


def apply_citations(
    items: list[EvidenceItem], records: list[CitationRecord]
) -> tuple[list[EvidenceItem], dict[str, int]]:
    """Fold mechanical citation checks into the evidence before scoring.
    ``verified`` passes through; ``quote_missing`` is excluded; everything else
    (dead, unfetchable, no_quote, unchecked) is downgraded one strength level."""
    by_pair = {(r.source_url, r.quote): r.status for r in records}
    kept: list[EvidenceItem] = []
    stats = {"verified": 0, "excluded_quote_missing": 0, "downgraded": 0}
    for it in items:
        status = by_pair.get((it.source_url, it.quote))
        if status == "verified":
            stats["verified"] += 1
            kept.append(it)
        elif status == "quote_missing":
            stats["excluded_quote_missing"] += 1
        else:
            stats["downgraded"] += 1
            kept.append(it.model_copy(update={"strength": _DOWNGRADE[it.strength]}))
    return kept, stats


def _read_citations(path: Path) -> tuple[list[CitationRecord], int]:
    records: list[CitationRecord] = []
    dropped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(CitationRecord.model_validate_json(line))
        except ValidationError:
            dropped += 1
    return records, dropped


def _read_items(paths: list[Path]) -> tuple[list[EvidenceItem], int]:
    """Read and validate evidence from JSONL shards. A mangled line (crash-partial
    write, agent formatting slip) is skipped but *counted*, and every command
    reports the count: silent data loss is how an agent believes it recorded a
    finding that never scores."""
    items: list[EvidenceItem] = []
    dropped = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(EvidenceItem.model_validate_json(line))
            except ValidationError:
                dropped += 1
    return items, dropped


# Non-evidence JSONL files that live in a run dir; never read as shards.
_RESERVED_JSONL = {"citations.jsonl", "merged.jsonl"}


def _shard_paths(run_dir: str | None, shards: list[str] | None) -> list[Path]:
    paths: list[Path] = []
    if run_dir:
        d = Path(run_dir)
        if not d.is_dir():
            raise CliError(f"run-dir not found: {d}")
        paths.extend(p for p in sorted(d.glob("*.jsonl")) if p.name not in _RESERVED_JSONL)
    for s in shards or []:
        p = Path(s)
        if not p.is_file():
            raise CliError(f"shard not found: {p}")
        paths.append(p)
    if not paths:
        raise CliError("no input: pass --run-dir or --shard")
    return paths


# --- Ranking (rubric rollup; each grid cell is an ordinary scored claim) ---

# A load-bearing (blocker/must) cell resting on fewer sources than this is an
# evidence gap: the natural target for a re-research round.
_GAP_MIN_SOURCES = 2


def rank_candidates(
    items: list[EvidenceItem],
    rubric: Rubric,
    *,
    prior: float = _DEFAULT_PRIOR,
    ceiling: float = _DEFAULT_CEILING,
    ceiling_tier: SourceTier = _DEFAULT_CEILING_TIER,
) -> list[CandidateVerdict]:
    """Roll per-cell claim certainties (``<candidate>--<criterion>``) up into
    per-candidate fit scores. Deterministic: the LLM layer only gathers evidence;
    every number here comes from the same weight-of-evidence engine as ``score``.

    - fit = weight-normalized mean of criterion certainties (0-100).
    - A ``blocker`` criterion below ``rubric.blocker_threshold`` marks the
      candidate blocked and caps its fit at that criterion's certainty.
    - A cell with no evidence sits at the prior (50 by default): unknown, not
      failing. Thin load-bearing cells are surfaced as ``evidence_gaps``;
      ``least_resolved`` names the load-bearing criterion closest to 50, the
      natural target for a re-research round."""
    total_weight = sum(c.weight for c in rubric.criteria)
    if total_weight <= 0:
        raise CliError("rubric has no positive criterion weight")
    by_claim: dict[str, list[EvidenceItem]] = defaultdict(list)
    for it in items:
        by_claim[it.claim_id].append(it)

    verdicts: list[CandidateVerdict] = []
    for cand in rubric.candidates:
        scores: list[CriterionScore] = []
        for crit in rubric.criteria:
            group = by_claim.get(f"{cand.id}--{crit.id}", [])
            if group:
                cv = score_claim(group, prior=prior, ceiling=ceiling, ceiling_tier=ceiling_tier)
                cell = CriterionScore(
                    criterion_id=crit.id,
                    tier=crit.tier,
                    weight=crit.weight,
                    certainty=cv["certainty"],
                    band=cv["band"],
                    n_sources=cv["n_sources"],
                    capped=cv["capped"],
                )
            else:
                certainty = round(prior * 100.0, 1)
                cell = CriterionScore(
                    criterion_id=crit.id,
                    tier=crit.tier,
                    weight=crit.weight,
                    certainty=certainty,
                    band=_band(certainty),
                    n_sources=0,
                    capped=False,
                )
            scores.append(cell)

        fit = sum(s["certainty"] * s["weight"] for s in scores) / total_weight
        failing = [
            s
            for s in scores
            if s["tier"] == "blocker" and s["certainty"] < rubric.blocker_threshold
        ]
        if failing:
            fit = min(fit, *(s["certainty"] for s in failing))
        load_bearing = [s for s in scores if s["tier"] in {"blocker", "must"}]
        least_resolved = (
            min(load_bearing, key=lambda s: abs(s["certainty"] - 50.0))["criterion_id"]
            if load_bearing
            else ""
        )
        verdicts.append(
            CandidateVerdict(
                candidate_id=cand.id,
                candidate=cand.name or cand.id,
                score=round(fit, 1),
                blocked=bool(failing),
                blocked_by=[s["criterion_id"] for s in failing],
                least_resolved=least_resolved,
                evidence_gaps=[
                    s["criterion_id"] for s in load_bearing if s["n_sources"] < _GAP_MIN_SOURCES
                ],
                criteria=scores,
            )
        )
    # Unblocked candidates first, then by fit; a blocked candidate never outranks
    # a clean one regardless of score.
    verdicts.sort(key=lambda v: (not v["blocked"], v["score"]), reverse=True)
    return verdicts


def _rank_markdown(verdicts: list[CandidateVerdict]) -> str:
    lines = [
        "| Rank | Candidate | Fit | Status | Least resolved | Evidence gaps |",
        "|---|---|---|---|---|---|",
    ]
    for i, v in enumerate(verdicts, 1):
        status = "blocked: " + ", ".join(v["blocked_by"]) if v["blocked"] else "ok"
        gaps = ", ".join(v["evidence_gaps"]) or "-"
        lines.append(
            f"| {i} | {v['candidate']} | {v['score']:g} | {status} "
            f"| {v['least_resolved'] or '-'} | {gaps} |"
        )
    for v in verdicts:
        lines += [
            "",
            f"### {v['candidate']}",
            "| Criterion | Tier | Certainty | Band | Sources |",
            "|---|---|---|---|---|",
        ]
        for s in v["criteria"]:
            cap = " (capped)" if s["capped"] else ""
            lines.append(
                f"| {s['criterion_id']} | {s['tier']} | {s['certainty']:g}{cap} "
                f"| {s['band']} | {s['n_sources']} |"
            )
    return "\n".join(lines)


# --- Run reconciliation (shards vs manifest) ---

# Similarity above which a coined claim id is treated as a typo of a registered
# one rather than a genuinely new claim.
_DRIFT_CUTOFF = 0.85


def check_run(run_dir: Path, manifest: ResearchManifest) -> tuple[dict[str, object], list[str]]:
    """Reconcile a run directory against its manifest. Returns (report, problems);
    problems are structural failures the orchestrator should react to (invalid
    shard lines, ranking-grid slug drift). Claims coined by finders beyond the
    registry are reported, not flagged: coining is allowed, fragmenting is not."""
    shard_files = [p for p in sorted(run_dir.glob("*.jsonl")) if p.name not in _RESERVED_JSONL]
    registered = {c.id for c in manifest.claims}
    grid: set[str] = set()
    if manifest.rubric is not None:
        grid = {
            f"{cand.id}--{crit.id}"
            for cand in manifest.rubric.candidates
            for crit in manifest.rubric.criteria
        }
        registered |= grid

    problems: list[str] = []
    found: set[str] = set()
    verify_covered: set[str] = set()
    invalid_by_shard: dict[str, int] = {}
    for p in shard_files:
        items, dropped = _read_items([p])
        if dropped:
            invalid_by_shard[p.name] = dropped
            problems.append(f"{p.name}: {dropped} invalid line(s) dropped")
        ids = {it.claim_id for it in items}
        found |= ids
        if p.name.startswith("verify"):
            verify_covered |= ids

    coined = found - registered
    if grid:
        # A coined id that *looks like* a grid cell is slug drift: evidence meant
        # for a rubric cell that will silently never score against it.
        problems.extend(
            f"grid drift: {cid} is not a rubric cell"
            for cid in sorted(c for c in coined if "--" in c)
        )
        coined = {c for c in coined if "--" not in c}
    # Near-miss drift the grid heuristic can't see (observed live: an agent wrote
    # `logseq-icloud-sync` for the cell `logseq--icloud-sync`): a coined id almost
    # identical to a registered one is a typo fragmenting that claim's evidence.
    for cid in sorted(coined):
        close = difflib.get_close_matches(cid, registered, n=1, cutoff=_DRIFT_CUTOFF)
        if close:
            problems.append(f"probable drift: {cid} resembles registered {close[0]}")
            coined -= {cid}

    report: dict[str, object] = {
        "shards": len(shard_files),
        "registered": len(registered),
        "found": len(found),
        "coined": sorted(coined),
        "no_evidence": sorted(registered - found),
        "verify_covered": len(verify_covered & found),
        "invalid_by_shard": invalid_by_shard,
        "problems": problems,
    }
    return report, problems


def _markdown_table(verdicts: list[ClaimVerdict]) -> str:
    lines = ["| Claim | Certainty | Band | Sources | Top driver |", "|---|---|---|---|---|"]
    for v in verdicts:
        top = v["drivers"][0] if v["drivers"] else None
        driver = f"{top['source_tier']} {top['decibans']:+g} dB" if top else "-"
        claim = (v["claim"] or v["claim_id"]).replace("|", "/")
        cap = " (capped)" if v["capped"] else ""
        lines.append(
            f"| {claim} | {v['certainty']:g}{cap} | {v['band']} | {v['n_sources']} | {driver} |"
        )
    return "\n".join(lines)


def _rubric() -> dict[str, object]:
    return {
        "method": "weight of evidence in log-odds; decibans = 10*log10(LR); "
        "certainty = logistic(logit(prior) + sum(decibans)/10*ln10)",
        "tier_decibans_strong": dict(_TIER_DECIBANS),
        "strength_multiplier": dict(_STRENGTH_MULT),
        "same_domain_factors": list(_DOMAIN_FACTORS),
        "prior_default": _DEFAULT_PRIOR,
        "ceiling": {
            "cap_certainty": _DEFAULT_CEILING,
            "requires_supporting_tier": _DEFAULT_CEILING_TIER,
            "note": "top bands (confident/established) need >=1 supporting source of this tier",
        },
        "bands": {
            **{b: f">={low:g}" for b, low in _BAND_MIN.items()},
            "refuted": f"<{_BAND_MIN['speculative']:g}",
        },
        "note": "a consistency convention across agents, not an empirically calibrated probability",
    }


class _Args(argparse.Namespace):
    command: str
    shard_path: str | None
    record: str | None
    run_dir: str | None
    shards: list[str] | None
    out: str | None
    prior: float
    ceiling: float
    ceiling_tier: str
    markdown: bool
    rubric_path: str | None
    manifest_path: str | None
    citations: str | None
    cache_dir: str | None
    timeout: int


def _cmd_append(args: _Args) -> None:
    if not args.shard_path:
        raise CliError("append: --shard is required")
    if not args.record:
        raise CliError("append: --json is required")
    try:
        item = EvidenceItem.model_validate_json(args.record)
    except ValidationError as e:
        raise CliError(f"invalid evidence item: {e}") from e
    path = Path(args.shard_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        _ = fh.write(item.model_dump_json() + "\n")
    print_json(_env("append", str(path), {"appended": item.model_dump()}))


def _cmd_merge(args: _Args) -> None:
    paths = _shard_paths(args.run_dir, args.shards)
    raw, dropped = _read_items(paths)
    merged = _dedup(raw)
    target = args.out or args.run_dir or (args.shards or ["-"])[0]
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(it.model_dump_json() + "\n" for it in merged), encoding="utf-8"
        )
    result: dict[str, object] = {
        "shards": len(paths),
        "items_raw": len(raw),
        "items_deduped": len(merged),
        "dropped_lines": dropped,
        "claims": sorted({it.claim_id for it in merged}),
        "written": args.out or None,
    }
    print_json(_env("merge", str(target), result))


def _scored_input(args: _Args) -> tuple[list[EvidenceItem], dict[str, object]]:
    """Shared score/rank input path: read shards, report dropped lines, and fold
    in the mechanical citation pass when its output is present (explicit
    ``--citations`` path, or ``citations.jsonl`` in the run dir)."""
    paths = _shard_paths(args.run_dir, args.shards)
    items, dropped = _read_items(paths)
    meta: dict[str, object] = {"n_items": len(items), "dropped_lines": dropped}
    cit_path = (
        Path(args.citations)
        if args.citations
        else (Path(args.run_dir) / "citations.jsonl" if args.run_dir else None)
    )
    if cit_path is not None and cit_path.is_file():
        records, cit_dropped = _read_citations(cit_path)
        items, stats = apply_citations(items, records)
        meta["citations"] = {**stats, "records": len(records), "dropped_lines": cit_dropped}
    return items, meta


def _ceiling_tier(args: _Args) -> SourceTier:
    if args.ceiling_tier not in _TIER_DECIBANS:
        return "primary"
    return args.ceiling_tier  # pyright: ignore[reportReturnType]


def _cmd_score(args: _Args) -> None:
    items, meta = _scored_input(args)
    verdicts = score_items(
        items, prior=args.prior, ceiling=args.ceiling, ceiling_tier=_ceiling_tier(args)
    )
    result: dict[str, object] = {**meta, "claims": verdicts}
    if args.markdown:
        result["markdown"] = _markdown_table(verdicts)
    target = args.run_dir or (args.shards or ["-"])[0]
    print_json(_env("score", str(target), result))


def _load_rubric(args: _Args) -> Rubric:
    """Explicit ``--rubric`` file, else the rubric embedded in the run manifest
    (the normal path for workflow runs: scope registers it once, rank reuses it)."""
    if args.rubric_path:
        rubric_file = Path(args.rubric_path)
        if not rubric_file.is_file():
            raise CliError(f"rubric not found: {rubric_file}")
        try:
            return Rubric.model_validate_json(rubric_file.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise CliError(f"invalid rubric: {e}") from e
    manifest_file = Path(args.run_dir) / "manifest.json" if args.run_dir else None
    if manifest_file is None or not manifest_file.is_file():
        raise CliError("rank: pass --rubric, or --run-dir with a manifest carrying one")
    try:
        manifest = ResearchManifest.model_validate_json(
            manifest_file.read_text(encoding="utf-8")
        )
    except ValidationError as e:
        raise CliError(f"invalid manifest: {e}") from e
    if manifest.rubric is None:
        raise CliError(f"no rubric in {manifest_file}; pass --rubric")
    return manifest.rubric


def _cmd_rank(args: _Args) -> None:
    rubric = _load_rubric(args)
    items, meta = _scored_input(args)
    verdicts = rank_candidates(
        items, rubric, prior=args.prior, ceiling=args.ceiling, ceiling_tier=_ceiling_tier(args)
    )
    result: dict[str, object] = {**meta, "candidates": verdicts}
    if args.markdown:
        result["markdown"] = _rank_markdown(verdicts)
    target = args.run_dir or (args.shards or ["-"])[0]
    print_json(_env("rank", str(target), result))


def _cmd_verify_citations(args: _Args) -> None:
    if not args.run_dir and not args.out:
        raise CliError("verify-citations: pass --run-dir (or --out for the record file)")
    paths = _shard_paths(args.run_dir, args.shards)
    items, dropped = _read_items(paths)
    pairs = list(dict.fromkeys((it.source_url, it.quote) for it in _dedup(items)))
    cache_dir = (
        Path(args.cache_dir)
        if args.cache_dir
        else (Path(args.run_dir) / ".http-cache" if args.run_dir else None)
    )
    records = [
        check_citation(url, quote, cache_dir=cache_dir, timeout=args.timeout)
        for url, quote in pairs
    ]
    out = Path(args.out) if args.out else Path(args.run_dir or ".") / "citations.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        counts[r.status] += 1
    result: dict[str, object] = {
        "checked": len(records),
        "counts": dict(counts),
        "dropped_lines": dropped,
        "written": str(out),
    }
    print_json(_env("verify-citations", str(args.run_dir or out), result))


def _cmd_check(args: _Args) -> None:
    if not args.run_dir:
        raise CliError("check: --run-dir is required")
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        raise CliError(f"run-dir not found: {run_dir}")
    manifest_file = Path(args.manifest_path) if args.manifest_path else run_dir / "manifest.json"
    if not manifest_file.is_file():
        raise CliError(f"manifest not found: {manifest_file}")
    try:
        manifest = ResearchManifest.model_validate_json(
            manifest_file.read_text(encoding="utf-8")
        )
    except ValidationError as e:
        raise CliError(f"invalid manifest: {e}") from e
    report, problems = check_run(run_dir, manifest)
    print_json(_env("check", str(run_dir), report))
    if problems:
        sys.exit(3)


def _cmd_manifest(args: _Args) -> None:
    if not args.run_dir:
        raise CliError("manifest: --run-dir is required")
    if not args.record:
        raise CliError("manifest: --json is required")
    try:
        manifest = ResearchManifest.model_validate_json(args.record)
    except ValidationError as e:
        raise CliError(f"invalid manifest: {e}") from e
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "manifest.json"
    out.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    grid = (
        len(manifest.rubric.candidates) * len(manifest.rubric.criteria)
        if manifest.rubric is not None
        else 0
    )
    result: dict[str, object] = {
        "written": str(out),
        "facets": len(manifest.facets),
        "claims": len(manifest.claims),
        "grid_cells": grid,
    }
    print_json(_env("manifest", str(run_dir), result))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standardized source-to-certainty scoring for durable research.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_inputs(p: argparse.ArgumentParser) -> None:
        _ = p.add_argument("--run-dir", dest="run_dir", help="dir of *.jsonl shards")
        _ = p.add_argument(
            "--shard", dest="shards", action="append", help="explicit shard (repeatable)"
        )

    def add_scoring(p: argparse.ArgumentParser) -> None:
        _ = p.add_argument("--prior", dest="prior", type=float, default=_DEFAULT_PRIOR)
        _ = p.add_argument("--ceiling", dest="ceiling", type=float, default=_DEFAULT_CEILING)
        _ = p.add_argument("--ceiling-tier", dest="ceiling_tier", default=_DEFAULT_CEILING_TIER)
        _ = p.add_argument(
            "--citations",
            dest="citations",
            help="citations.jsonl from verify-citations (default: <run-dir>/citations.jsonl)",
        )
        _ = p.add_argument("--markdown", dest="markdown", action="store_true")

    ap = sub.add_parser("append", help="durably append one evidence item to a shard")
    _ = ap.add_argument("--shard", dest="shard_path", required=True, help="shard file")
    _ = ap.add_argument("--json", dest="record", required=True, help="EvidenceItem JSON")

    np_ = sub.add_parser("manifest", help="validate + write the run manifest")
    _ = np_.add_argument("--run-dir", dest="run_dir", required=True)
    _ = np_.add_argument("--json", dest="record", required=True, help="ResearchManifest JSON")

    mp = sub.add_parser("merge", help="merge + dedup shards (idempotent)")
    add_inputs(mp)
    _ = mp.add_argument("--out", dest="out", help="write merged JSONL here")

    vp = sub.add_parser(
        "verify-citations", help="mechanically check every cited (url, quote) pair"
    )
    add_inputs(vp)
    _ = vp.add_argument("--out", dest="out", help="record file (default: <run-dir>/citations.jsonl)")
    _ = vp.add_argument(
        "--cache-dir", dest="cache_dir", help="HTTP cache dir (default: <run-dir>/.http-cache)"
    )
    _ = vp.add_argument("--timeout", dest="timeout", type=int, default=20)

    kp = sub.add_parser("check", help="reconcile shards against the run manifest")
    _ = kp.add_argument("--run-dir", dest="run_dir", required=True)
    _ = kp.add_argument(
        "--manifest", dest="manifest_path", help="manifest file (default: <run-dir>/manifest.json)"
    )

    sp = sub.add_parser("score", help="score claims from shards")
    add_inputs(sp)
    add_scoring(sp)

    rp = sub.add_parser("rank", help="rank rubric candidates from scored grid claims")
    add_inputs(rp)
    add_scoring(rp)
    _ = rp.add_argument(
        "--rubric",
        dest="rubric_path",
        help="Rubric JSON file (default: the rubric in <run-dir>/manifest.json)",
    )

    _ = sub.add_parser("rubric", help="print the scoring convention")

    args = parse_typed_args(parser, _Args)
    commands = {
        "append": _cmd_append,
        "manifest": _cmd_manifest,
        "merge": _cmd_merge,
        "verify-citations": _cmd_verify_citations,
        "check": _cmd_check,
        "score": _cmd_score,
        "rank": _cmd_rank,
    }
    try:
        if args.command == "rubric":
            print_json(_env("rubric", "rubric", _rubric()))
        else:
            commands[args.command](args)
    except CliError as e:
        print_json({"ok": False, "cmd": args.command, "error": str(e)})
        sys.exit(e.code)


if __name__ == "__main__":
    main()
