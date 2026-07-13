# pyright: reportAny=false, reportExplicitAny=false
# Vendored research harness: this module fetches URLs and parses JSON/HTML, boundaries where the
# stdlib hands back `Any`. reportAny/reportExplicitAny are above
# basedpyright's standard strict (which this file passes); every other
# strict check still applies.
"""Mechanical citation verification.

`research check` proves the store is well-formed; it never proves a quote is
real. This module does: it fetches each cited ``source_url`` and confirms the
verbatim finding actually appears on the page, so a finder's mis-transcription
or fabrication is caught by machine rather than by the critic's manual
spot-check. Matching is shingle-tolerant (word 5-grams) with a Wayback fallback
for dead links, over a SHA256-keyed on-disk fetch cache.

Verification is advisory: it reports a per-row status the human resolves (VOID
the row or fix the quote); it never mutates the store or the confidence math.
The CSVs stay the single source of truth; the HTTP cache is a disposable
``.http-cache/`` dot-directory inside the topic, safe to delete anytime.
"""

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import cast
import urllib.error
import urllib.parse
import urllib.request

from vault_scripts.research.confidence import VOID_ID
from vault_scripts.research.store import CITATIONS_CSV, DATA_DIR, EVIDENCE_CSV, Topic

# The verdict columns persisted to data/citations.csv, keyed by evidence_id so
# the offline verify/rank scorer can exclude quote_missing and downgrade
# unverified rows. A companion file, never a mutation of evidence.csv.
CITATION_COLUMNS = ("evidence_id", "source_url", "status", "http_status", "archived")

# Per-row outcomes:
VERIFIED = "verified"  # quote found on the live or archived page
QUOTE_MISSING = "quote_missing"  # page responded but the quote is absent
DEAD = "dead"  # HTTP >= 300 and no Wayback snapshot
UNFETCHABLE = "unfetchable"  # could not connect, or a non-textual response
NO_QUOTE = "no_quote"  # the row carries no quote to check
STATUSES = (VERIFIED, QUOTE_MISSING, DEAD, UNFETCHABLE, NO_QUOTE)

_HTTP_OK = 200
_UA = "vault-research/1.0 (+citation verifier)"
_MAX_BYTES = 5_000_000
_TIMEOUT = 20.0
_SHINGLE = 5  # word n-gram size for the fuzzy quote match
_SHINGLE_MIN = 0.6  # fraction of a long quote's shingles that must be present
_WAYBACK_API = "https://archive.org/wayback/available?url="

_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WORD_RE = re.compile(r"\w+")


@dataclass(frozen=True)
class FetchResult:
    status_code: int  # 0 means the request never reached a server
    content_type: str
    text: str


@dataclass(frozen=True)
class CitationResult:
    status: str
    http_status: int
    archived: bool


@dataclass(frozen=True)
class CitationRecord:
    evidence_id: str
    unit: str
    category_id: str
    source_url: str
    status: str
    http_status: int
    archived: bool


# --- Quote matching (language-agnostic, no fuzzy-match dependency) ---


def _strip_html(html: str) -> str:
    return _TAG_RE.sub(" ", _SCRIPT_RE.sub(" ", html))


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _shingles(words: list[str], size: int) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + size]) for i in range(len(words) - size + 1)]


def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def quote_present(quote: str, page: str) -> bool:
    """True if ``quote`` appears in ``page``. Short quotes must match as a
    contiguous word run; longer quotes need >= 60% of their 5-word shingles
    present, tolerating typography and truncation."""
    words = _words(quote)
    if not words:
        return False
    page_words = _words(_strip_html(page))
    if len(words) <= _SHINGLE:
        return _contains_run(page_words, words)
    quote_shingles = _shingles(words, _SHINGLE)
    page_shingles = set(_shingles(page_words, _SHINGLE))
    hits = sum(1 for sh in quote_shingles if sh in page_shingles)
    return hits / len(quote_shingles) >= _SHINGLE_MIN


# --- Fetching, with a SHA256-keyed on-disk cache ---


def fetch_url(url: str, timeout: float) -> FetchResult:
    """Fetch a URL. Returns status 0 for anything that never reached a server
    (bad scheme, connection error, timeout). Never raises."""
    if not url.startswith(("http://", "https://")):
        return FetchResult(0, "", "")
    request = urllib.request.Request(url, headers={"User-Agent": _UA})  # noqa: S310 - scheme guarded above
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(_MAX_BYTES)
            text = raw.decode(charset, errors="replace")
            return FetchResult(
                response.status, response.headers.get_content_type(), text
            )
    except urllib.error.HTTPError as exc:
        content_type = exc.headers.get_content_type() if exc.headers else ""
        return FetchResult(exc.code, content_type, "")
    except urllib.error.URLError, TimeoutError, OSError, ValueError:
        return FetchResult(0, "", "")


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _read_cache(path: Path) -> FetchResult | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return FetchResult(
            int(data["status_code"]), str(data["content_type"]), str(data["text"])
        )
    except json.JSONDecodeError, KeyError, OSError, TypeError, ValueError:
        return None  # corrupt or stale entry: refetch


def cached_fetch(url: str, cache_dir: Path | None, timeout: float) -> FetchResult:
    """Fetch with an on-disk cache. Connection failures (status 0) are never
    cached, so a transient blip retries on the next run."""
    path = _cache_path(cache_dir, url) if cache_dir is not None else None
    if path is not None and path.exists():
        cached = _read_cache(path)
        if cached is not None:
            return cached
    result = fetch_url(url, timeout)
    if path is not None and result.status_code != 0:
        cache_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        path.write_text(
            json.dumps({
                "status_code": result.status_code,
                "content_type": result.content_type,
                "text": result.text,
            }),
            encoding="utf-8",
        )
    return result


# --- Citation checking ---


def _is_textual(content_type: str) -> bool:
    ct = content_type.lower()
    return (
        not ct
        or ct.startswith("text/")
        or any(token in ct for token in ("html", "xml", "json"))
    )


def _get(obj: object, key: str) -> object:
    """Read a key from a value that may or may not be a dict (untyped JSON)."""
    return cast("dict[str, object]", obj).get(key) if isinstance(obj, dict) else None


def _wayback_snapshot(url: str, timeout: float) -> str | None:
    result = fetch_url(_WAYBACK_API + urllib.parse.quote(url, safe=""), timeout)
    if result.status_code != _HTTP_OK or not result.text:
        return None
    try:
        payload: object = json.loads(result.text)
    except json.JSONDecodeError:
        return None
    closest = _get(_get(payload, "archived_snapshots"), "closest")
    snapshot_url = _get(closest, "url")
    if _get(closest, "available") and isinstance(snapshot_url, str):
        return snapshot_url
    return None


def check_citation(
    url: str, quote: str, *, cache_dir: Path | None, timeout: float = _TIMEOUT
) -> CitationResult:
    """Fetch ``url`` and decide whether ``quote`` is on the page, falling back
    to the Wayback Machine when the live page is gone."""
    if not quote.strip():
        return CitationResult(NO_QUOTE, 0, False)

    live = cached_fetch(url, cache_dir, timeout)
    if live.status_code == _HTTP_OK and _is_textual(live.content_type):
        status = VERIFIED if quote_present(quote, live.text) else QUOTE_MISSING
        return CitationResult(status, _HTTP_OK, False)

    snapshot_url = _wayback_snapshot(url, timeout)
    if snapshot_url is not None:
        snapshot = cached_fetch(snapshot_url, cache_dir, timeout)
        if snapshot.status_code == _HTTP_OK and _is_textual(snapshot.content_type):
            status = VERIFIED if quote_present(quote, snapshot.text) else QUOTE_MISSING
            return CitationResult(status, live.status_code, True)

    if live.status_code >= 300:  # noqa: PLR2004 - HTTP redirect/error boundary
        return CitationResult(DEAD, live.status_code, False)
    return CitationResult(UNFETCHABLE, live.status_code, False)


def default_cache_dir(topic: Topic) -> Path:
    """The topic's disposable on-disk fetch cache (``.http-cache/`` under the
    topic root). Topic directories already live outside iCloud, so the cache
    does too; delete it to force a refetch."""
    return topic.root / ".http-cache"


def write_citations(topic: Topic, records: list[CitationRecord]) -> Path:
    """Persist the per-row verdicts to ``data/citations.csv``, overwriting the
    prior run's. Keyed by ``evidence_id`` for the offline scorer. Writing this
    companion file is verify's only side effect; the evidence log is untouched."""
    path = topic.root / DATA_DIR / CITATIONS_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CITATION_COLUMNS)
        for r in records:
            writer.writerow([
                r.evidence_id,
                r.source_url,
                r.status,
                r.http_status,
                "yes" if r.archived else "no",
            ])
    return path


def read_citations(topic: Topic) -> dict[str, str]:
    """The persisted ``evidence_id -> status`` verdicts, empty if never run."""
    table = topic.tables.get(CITATIONS_CSV)
    if table is None:
        return {}
    return {
        r["evidence_id"]: r.get("status", "")
        for r in table.rows
        if r.get("evidence_id")
    }


def verify_topic(
    topic: Topic,
    *,
    cache_dir: Path | None,
    timeout: float = _TIMEOUT,
) -> tuple[list[CitationRecord], dict[str, int]]:
    """Verify every non-VOID evidence row that carries a ``source_url``.
    Returns the per-row records and a status histogram."""
    records: list[CitationRecord] = []
    counts: dict[str, int] = dict.fromkeys(STATUSES, 0)
    for row in topic.tables[EVIDENCE_CSV].rows:
        # The row's topic reference is mode-specific: category_id (map),
        # claim_id (verify), cell_id (rank/find), or factor_id (estimate). Any
        # of them can carry VOID.
        category_id = (
            row.get("category_id")
            or row.get("claim_id")
            or row.get("cell_id")
            or row.get("factor_id")
            or ""
        )
        url = row.get("source_url", "")
        if category_id == VOID_ID or not url:
            continue
        quote = (
            row.get("finding_verbatim")
            or row.get("detail_quote")
            or row.get("quote")
            or ""
        )
        result = check_citation(url, quote, cache_dir=cache_dir, timeout=timeout)
        counts[result.status] += 1
        records.append(
            CitationRecord(
                evidence_id=row.get("evidence_id", ""),
                unit=row.get("unit", ""),
                category_id=category_id,
                source_url=url,
                status=result.status,
                http_status=result.http_status,
                archived=result.archived,
            )
        )
    return records, counts
