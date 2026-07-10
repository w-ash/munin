"""Shared tenacity retry policies and HTTP helpers for external API calls.

Exception taxonomy:

- ``TransientHTTPError``: status 429 or any 5xx from any API; retryable.
  Carries the server's Retry-After (seconds) when present, honored by the wait.
- ``OverpassBusyError``: Overpass returned HTML (server overloaded); retryable.
- ``OverpassUnavailableError``: every Overpass mirror exhausted retries;
  raised by the caller's outer mirror-fallback loop so downstream code can
  distinguish "OSM confirmed empty" from "we never got an answer".
- ``requests.Timeout`` / ``requests.ConnectionError``: network flakes; retryable.

``request_validated_json()`` checks the response for transient failures and
raises the appropriate exception so tenacity can retry. Google gets jittered
backoff to avoid thundering-herd under sustained rate limits; Overpass uses
plain exponential since its failures are usually server-wide and bouncing
off one mirror to the next handles uncorrelated load better than jitter alone.

Both decorators reraise on final failure so callers see the underlying
exception instead of a ``RetryError`` wrapper.

``request_validated_json`` validates JSON responses against a Pydantic model
in one call. It parses from ``resp.content`` via ``model_validate_json`` so
``Any`` never enters the type graph.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from pydantic import BaseModel, ValidationError
import requests
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)
from tenacity.wait import wait_base

# 429 + any 5xx are transient; matches the official google-api-python-client
# (`_should_retry_response`), which retries all 5xx rather than a fixed subset.
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500
# Cap a server-provided Retry-After so a huge/hostile value can't hang a call.
_MAX_RETRY_AFTER_S = 60


class TransientHTTPError(Exception):
    """HTTP status in the transient set (429 or any 5xx); retry.

    ``retry_after`` carries the server's Retry-After delay in seconds when the
    response provided one, so the wait strategy can honor it over plain backoff.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after: float | None = retry_after


class OverpassBusyError(Exception):
    """Overpass returned a non-JSON (HTML busy) response; retry."""


class OverpassUnavailableError(Exception):
    """All Overpass mirrors exhausted retries. Caller can't fill station_lines.

    Distinct from "OSM had no matching elements" (that's a successful
    empty response); this means we never got a usable answer. Callers
    in refresh mode should preserve existing values rather than clear
    them on this exception.
    """


# All exception types an external API call can raise after retries are
# exhausted. Callers should ``except APIError`` around the call site.
# Schema drift and JSON-parse failures both raise ValidationError;
# tenacity's final reraise surfaces Transient/Overpass errors after retries.
APIError: tuple[type[BaseException], ...] = (
    requests.RequestException,
    ValidationError,
    TransientHTTPError,
    OverpassBusyError,
    OverpassUnavailableError,
)

# The subset worth retrying a single request on. Hard 4xx (raise_for_status
# -> requests.HTTPError) and schema drift (ValidationError) stay in APIError
# so callers still catch them, but retrying can't help; they fail fast
# instead of burning the full backoff budget on a deterministic failure.
_RETRYABLE: tuple[type[BaseException], ...] = (
    TransientHTTPError,
    OverpassBusyError,
    requests.ConnectionError,
    requests.Timeout,
    # Body truncated/garbled mid-transfer: a transient transport failure, not a
    # hard 4xx. Both subclass RequestException directly (not ConnectionError), so
    # they'd otherwise be dropped from the retry set.
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


class WaitRetryAfter(wait_base):
    """Honor a server Retry-After when the last failure carried one (capped at
    :data:`_MAX_RETRY_AFTER_S`); otherwise defer to the wrapped backoff strategy.

    Keeps the Retry-After timing inside tenacity rather than a hand-rolled sleep,
    so all the usual machinery (attempt cap, reraise, jittered fallback) still
    applies. Wrapped around each decorator's existing wait, so it only changes
    behavior when a response actually provided the header.
    """

    def __init__(self, fallback: wait_base) -> None:
        self._fallback = fallback

    def __call__(self, retry_state: RetryCallState) -> float:
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome is not None else None
        if isinstance(exc, TransientHTTPError) and exc.retry_after is not None:
            return min(exc.retry_after, float(_MAX_RETRY_AFTER_S))
        return self._fallback(retry_state)


# Five attempts at up to 30s of jittered backoff lets a call ride out a 60s
# quota window (Sheets quotas reset each minute) instead of failing fast.
google_retry = retry(
    stop=stop_after_attempt(5),
    wait=WaitRetryAfter(wait_random_exponential(multiplier=1, max=30)),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)


overpass_retry = retry(
    stop=stop_after_attempt(2),
    wait=WaitRetryAfter(wait_exponential(multiplier=1.1, min=1, max=8)),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)


# Wikimedia's per-minute (not per-hour) global rate limits introduced in
# 2026 mean bursty failures arrive faster than under Google's per-day
# quota; jittered backoff avoids thundering-herd pressure on the
# per-minute bucket. Four attempts x max 16s wait ≈ 35s of backoff plus
# up to 4x per-attempt request timeout in worst case.
wikimedia_retry = retry(
    stop=stop_after_attempt(4),
    wait=WaitRetryAfter(wait_random_exponential(multiplier=1.5, max=16)),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)


# Citation checks sweep dozens of unrelated hosts; a slow or flaky one should
# cost seconds, not a full backoff budget, and the caller records the failure
# as "unfetchable" rather than aborting the sweep.
citation_retry = retry(
    stop=stop_after_attempt(3),
    wait=WaitRetryAfter(wait_random_exponential(multiplier=1, max=8)),
    retry=retry_if_exception_type(_RETRYABLE),
    reraise=True,
)


def _parse_retry_after(resp: requests.Response) -> float | None:
    """Parse a ``Retry-After`` header (RFC 7231): integer seconds or an HTTP-date.
    Returns the delay in seconds (never negative), or None when absent/unparseable.
    Google's Sheets quota errors rarely set it, but honoring it when present is the
    correct, server-directed backoff."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(tz=UTC)).total_seconds(), 0.0)


def _classify_transient(resp: requests.Response) -> None:
    """Raise :class:`TransientHTTPError` on 429 or any 5xx, otherwise raise on
    other 4xx via ``raise_for_status``. Shared between request helpers so the
    transient-vs-permanent split stays consistent. A server-provided Retry-After
    is attached so the wait strategy can honor it."""
    if resp.status_code == _TOO_MANY_REQUESTS or resp.status_code >= _SERVER_ERROR:
        raise TransientHTTPError(
            f"HTTP {resp.status_code}", retry_after=_parse_retry_after(resp)
        )
    resp.raise_for_status()


def request_validated_json[M: BaseModel](
    method: str,
    url: str,
    *,
    response_model: type[M],
    timeout: int,
    headers: dict[str, str] | None = None,
    json: object | None = None,
    data: dict[str, str] | bytes | None = None,
    params: dict[str, str] | None = None,
    ok: Callable[[requests.Response], bool] | None = None,
) -> M:
    """Issue an HTTP request and validate the JSON response against
    ``response_model``. Returns a typed model instance directly.

    Raises retryable exceptions on transient failure so callers can wrap
    with a tenacity decorator. ``ok`` is an optional predicate run on a
    2xx response; if it returns False the call raises
    :class:`OverpassBusyError`. Used by Overpass to treat HTML-in-200
    responses as retryable busy signals. ``data`` accepts raw ``bytes`` (with a
    caller-set Content-Type header) for the Drive multipart Markdown upload.

    Malformed JSON raises ``ValidationError`` (already in :data:`APIError`).
    """
    resp = requests.request(
        method,
        url,
        timeout=timeout,
        headers=headers,
        json=json,
        data=data,
        params=params,
    )
    _classify_transient(resp)
    if ok is not None and not ok(resp):
        raise OverpassBusyError("response predicate failed")
    return response_model.model_validate_json(resp.content)


def request_page(
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """GET a page for citation checking; returns ``(status_code, content_type,
    text)``. Raises :class:`TransientHTTPError` on 429/5xx so a tenacity
    decorator can retry, but returns hard 4xx instead of raising: for citation
    liveness a 404 is the finding (dead link), not a failure."""
    resp = requests.get(url, timeout=timeout, headers=headers)
    if resp.status_code == _TOO_MANY_REQUESTS or resp.status_code >= _SERVER_ERROR:
        raise TransientHTTPError(
            f"HTTP {resp.status_code}", retry_after=_parse_retry_after(resp)
        )
    return resp.status_code, resp.headers.get("Content-Type", ""), resp.text


def request_image_bytes(
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> bytes:
    """GET a binary payload (image). Raises :class:`TransientHTTPError` on
    429/5xx so a tenacity decorator (e.g. :data:`wikimedia_retry`) can back
    off and retry."""
    resp = requests.get(url, timeout=timeout, headers=headers)
    _classify_transient(resp)
    return resp.content
