"""Shared tenacity retry policies and HTTP helpers for external API calls.

Exception taxonomy:

- ``TransientHTTPError`` — status 429/502/503/504 from any API; retryable.
- ``OverpassBusyError`` — Overpass returned HTML (server overloaded); retryable.
- ``OverpassUnavailableError`` — every Overpass mirror exhausted retries;
  raised by the caller's outer mirror-fallback loop so downstream code can
  distinguish "OSM confirmed empty" from "we never got an answer".
- ``requests.Timeout`` / ``requests.ConnectionError`` — network flakes; retryable.

``request_validated_json()`` checks the response for transient failures and
raises the appropriate exception so tenacity can retry. Google gets jittered
backoff to avoid thundering-herd under sustained rate limits; Overpass uses
plain exponential since its failures are usually server-wide and bouncing
off one mirror to the next handles uncorrelated load better than jitter alone.

Both decorators reraise on final failure so callers see the underlying
exception instead of a ``RetryError`` wrapper.

JSON validation is baked into the request: ``request_validated_json`` takes
a ``response_model`` and returns a typed Pydantic model instance directly,
parsing from ``resp.content`` (typed ``bytes``) via ``model_validate_json``.
Keeps ``Any`` out of the type graph and avoids ``model_validate(json.loads(...))``
boilerplate. The ``ok=`` predicate is preserved for Overpass HTML-in-200
busy detection.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

_TRANSIENT_STATUS = frozenset({429, 502, 503, 504})


class TransientHTTPError(Exception):
    """HTTP status in the transient set (429/5xx) — retry."""


class OverpassBusyError(Exception):
    """Overpass returned a non-JSON (HTML busy) response — retry."""


class OverpassUnavailableError(Exception):
    """All Overpass mirrors exhausted retries. Caller can't fill station_lines.

    Distinct from "OSM had no matching elements" (that's a successful
    empty response) — this means we never got a usable answer. Callers
    in refresh mode should preserve existing values rather than clear
    them on this exception.
    """


# All exception types an external API call can raise after retries are
# exhausted. Callers should ``except APIError`` around the call site.
# Schema drift and JSON-parse failures both raise ValidationError via
# model_validate_json(); tenacity's final reraise surfaces
# Transient/Overpass errors after retries.
APIError: tuple[type[BaseException], ...] = (
    requests.RequestException,
    ValidationError,
    TransientHTTPError,
    OverpassBusyError,
    OverpassUnavailableError,
)


google_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=8),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)


overpass_retry = retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1.1, min=1, max=8),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)


# Wikimedia's per-minute (not per-hour) global rate limits introduced in
# 2026 mean bursty failures arrive faster than under Google's per-day
# quota — jittered backoff avoids thundering-herd pressure on the
# per-minute bucket. Four attempts x max 16s wait ≈ 35s of backoff plus
# up to 4x per-attempt request timeout in worst case.
wikimedia_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_random_exponential(multiplier=1.5, max=16),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)


def _classify_transient(resp: requests.Response) -> None:
    """Raise :class:`TransientHTTPError` on 429/5xx, otherwise raise on
    other 4xx/5xx via ``raise_for_status``. Shared between request helpers
    so the transient-vs-permanent split stays consistent."""
    if resp.status_code in _TRANSIENT_STATUS:
        raise TransientHTTPError(f"HTTP {resp.status_code}")
    resp.raise_for_status()


def request_validated_json[M: BaseModel](
    method: str,
    url: str,
    *,
    response_model: type[M],
    timeout: int,
    headers: dict[str, str] | None = None,
    json: object | None = None,
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    ok: Callable[[requests.Response], bool] | None = None,
) -> M:
    """Issue an HTTP request and validate the JSON response against
    ``response_model``. Returns a typed model instance directly.

    Raises retryable exceptions on transient failure so callers can wrap
    with a tenacity decorator. ``ok`` is an optional predicate run on a
    2xx response; if it returns False the call raises
    :class:`OverpassBusyError`. Used by Overpass to treat HTML-in-200
    responses as retryable busy signals.

    Validates from ``resp.content`` (``bytes``) via ``model_validate_json``
    rather than ``resp.json()``: keeps ``Any`` out of the type graph and is
    Pydantic's documented perf-preferred path. Malformed JSON raises
    ``ValidationError`` (already in :data:`APIError`) instead of
    ``requests.JSONDecodeError``.
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
