"""Unit tests for the shared retry layer: transient classification, Retry-After
parsing, and the WaitRetryAfter wait strategy. No network — fake Response objects
and a stub fallback wait stand in for the real request/tenacity machinery."""

from __future__ import annotations

import pytest
import requests

from vault_scripts import _retry
from vault_scripts._retry import TransientHTTPError, WaitRetryAfter


def _resp(status: int, headers: dict[str, str] | None = None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    if headers:
        r.headers.update(headers)
    return r


# --- _classify_transient: 429 + all 5xx are transient; other 4xx raise ---


@pytest.mark.parametrize("status", [429, 500, 501, 502, 503, 504, 599])
def test_classify_transient_retries_429_and_5xx(status):
    with pytest.raises(TransientHTTPError):
        _retry._classify_transient(_resp(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 412])
def test_classify_transient_raises_http_error_on_4xx(status):
    with pytest.raises(requests.HTTPError):
        _retry._classify_transient(_resp(status))


def test_classify_transient_ok_on_2xx():
    _retry._classify_transient(_resp(200))  # no raise


def test_classify_transient_attaches_retry_after():
    with pytest.raises(TransientHTTPError) as exc:
        _retry._classify_transient(_resp(429, {"Retry-After": "7"}))
    assert exc.value.retry_after == pytest.approx(7.0)


# --- _parse_retry_after ---


def test_parse_retry_after_integer():
    assert _retry._parse_retry_after(
        _resp(429, {"Retry-After": "12"})
    ) == pytest.approx(12.0)


def test_parse_retry_after_absent():
    assert _retry._parse_retry_after(_resp(429)) is None


def test_parse_retry_after_garbage():
    assert _retry._parse_retry_after(_resp(429, {"Retry-After": "soon"})) is None


def test_parse_retry_after_past_http_date_clamps_to_zero():
    past = "Wed, 21 Oct 2015 07:28:00 GMT"
    assert _retry._parse_retry_after(
        _resp(429, {"Retry-After": past})
    ) == pytest.approx(0.0)


# --- WaitRetryAfter: honor the header when present, else delegate ---


class _ConstWait(_retry.wait_base):
    """A fallback wait that ignores the retry state and returns a fixed value."""

    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self, retry_state) -> float:
        return self.value


class _Outcome:
    def __init__(self, exc: BaseException | None) -> None:
        self._exc = exc

    def exception(self) -> BaseException | None:
        return self._exc


class _State:
    def __init__(self, exc: BaseException | None) -> None:
        self.outcome = _Outcome(exc)


def test_wait_retry_after_honors_header():
    w = WaitRetryAfter(_ConstWait(99.0))
    assert w(_State(TransientHTTPError("x", retry_after=5.0))) == pytest.approx(5.0)


def test_wait_retry_after_caps_at_max():
    w = WaitRetryAfter(_ConstWait(99.0))
    capped = w(_State(TransientHTTPError("x", retry_after=9999.0)))
    assert capped == pytest.approx(float(_retry._MAX_RETRY_AFTER_S))


def test_wait_retry_after_falls_back_without_header():
    w = WaitRetryAfter(_ConstWait(3.5))
    assert w(_State(TransientHTTPError("x"))) == pytest.approx(3.5)


def test_wait_retry_after_falls_back_on_other_exception():
    w = WaitRetryAfter(_ConstWait(2.0))
    assert w(_State(ValueError("nope"))) == pytest.approx(2.0)


def test_wait_retry_after_falls_back_when_no_outcome():
    w = WaitRetryAfter(_ConstWait(1.0))
    assert w(_State(None)) == pytest.approx(1.0)
