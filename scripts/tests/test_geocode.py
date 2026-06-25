"""Unit tests for pure geocode helpers. No network — ``_google_post`` is stubbed
with a constructed Routes response."""

from __future__ import annotations

from vault_scripts import geocode
from vault_scripts._types import RoutesResponse, RoutesRoute


def _stub_route(monkeypatch, duration: str) -> None:
    monkeypatch.setattr(
        geocode,
        "_google_post",
        lambda *_a, **_k: RoutesResponse(routes=[RoutesRoute(duration=duration)]),
    )


def test_walk_duration_accepts_fractional_seconds(monkeypatch):
    # Routes' protobuf Duration may carry fractional seconds; the parse must not
    # drop the route. ceil(512.5 / 60) == 9.
    _stub_route(monkeypatch, "512.5s")
    assert geocode.walk_duration_minutes(0.0, 0.0, 1.0, 1.0) == 9


def test_walk_duration_integer_seconds(monkeypatch):
    _stub_route(monkeypatch, "120s")
    assert geocode.walk_duration_minutes(0.0, 0.0, 1.0, 1.0) == 2


def test_walk_duration_unparseable_returns_none(monkeypatch):
    _stub_route(monkeypatch, "not-a-duration")
    assert geocode.walk_duration_minutes(0.0, 0.0, 1.0, 1.0) is None
