"""Unit tests for the comps store and RentCast fetcher (``_comps``). The store
round-trips through CSV and dedupes on ``(subject, source, source_id)``; the
fetcher maps RentCast's listing-shaped comparables into store rows (listed
``price`` → ``sale_price``, ``removedDate`` → ``sale_date``). The HTTP call is
monkeypatched so no network or API key is needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from vault_scripts import _comps
from vault_scripts._comps import (
    append_comps,
    fetch_comps,
    load_comps,
    subject_slug,
)
from vault_scripts._types import Comp, RentCastComparable, RentCastValueResponse


def _mk_comp(**over):
    base = {
        "subject": "home1",
        "address": "1 A St",
        "sale_price": 1_000_000.0,
        "sale_date": "2026-01-01",
        "beds": 3.0,
        "baths": 2.0,
        "sqft": 1800.0,
        "lot_sqft": 4000.0,
        "year_built": 1920,
        "dist_mi": 0.1,
        "garage": None,
        "adu": None,
        "condition": None,
        "source": "manual",
        "source_id": "m1",
    }
    base.update(over)
    return Comp(**base)


def test_subject_slug():
    assert subject_slug(Path("Projects/Home Search/Homes/entries/2117 Grant St.md")) == "2117-grant-st"
    assert subject_slug(Path("Projects/Home Search/Homes/entries/1631 Grant St.md")) == "1631-grant-st"


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "comps.csv"
    added, skipped = append_comps([_mk_comp()], path)
    assert (added, skipped) == (1, 0)

    loaded = load_comps("home1", path)
    assert len(loaded) == 1
    got = loaded[0]
    assert got.sale_price == pytest.approx(1_000_000)
    assert got.year_built == 1920
    assert got.baths == pytest.approx(2.0)
    assert got.dist_mi == pytest.approx(0.1)
    assert got.garage is None  # blank cell parses back to None
    assert got.source_id == "m1"


def test_append_dedupes_on_provenance(tmp_path):
    path = tmp_path / "comps.csv"
    _ = append_comps([_mk_comp()], path)
    # Same (subject, source, source_id) is a no-op even if other fields differ.
    added, skipped = append_comps([_mk_comp(sale_price=999.0)], path)
    assert (added, skipped) == (0, 1)
    assert len(load_comps("home1", path)) == 1


def test_load_comps_filters_by_subject(tmp_path):
    path = tmp_path / "comps.csv"
    _ = append_comps(
        [_mk_comp(source_id="a"), _mk_comp(subject="home2", source_id="b")], path
    )
    assert len(load_comps("home1", path)) == 1
    assert len(load_comps("home2", path)) == 1
    assert load_comps("missing", path) == []


def test_load_comps_missing_file_is_empty(tmp_path):
    assert load_comps("home1", tmp_path / "nope.csv") == []


def test_fetch_comps_maps_rentcast_listing(monkeypatch):
    resp = RentCastValueResponse(
        price=1_200_000,
        comparables=[
            RentCastComparable(
                id="r1",
                formattedAddress="9 X St, Berkeley, CA",
                price=1_150_000,
                bedrooms=3,
                bathrooms=2,
                squareFootage=1800,
                lotSize=4000,
                yearBuilt=1910,
                distance=0.2534,
                removedDate="2026-05-02T00:00:00.000Z",
                listedDate="2026-03-01T00:00:00.000Z",
            )
        ],
    )
    monkeypatch.setattr(
        _comps, "_fetch_value", lambda *_a: resp
    )
    comps = fetch_comps("500 Test St", "fake-key", "home1", 15)
    assert len(comps) == 1
    c = comps[0]
    assert c.subject == "home1"
    assert c.source == "rentcast"
    assert c.source_id == "r1"
    assert c.address == "9 X St, Berkeley, CA"
    assert c.sale_price == pytest.approx(1_150_000)  # listed price → sale_price
    assert c.sale_date == "2026-05-02"  # removedDate wins, ISO time trimmed
    assert c.dist_mi == pytest.approx(0.253)  # rounded to 3 dp
    # RentCast comparables carry no garage/adu/condition; left blank for rating.
    assert c.garage is None
    assert c.adu is None
    assert c.condition is None


def test_fetch_comps_prefers_last_seen_when_no_removed_date(monkeypatch):
    resp = RentCastValueResponse(
        comparables=[
            RentCastComparable(
                id="r2",
                formattedAddress="7 Y St",
                price=900_000,
                lastSeenDate="2026-06-10T12:00:00.000Z",
            )
        ],
    )
    monkeypatch.setattr(
        _comps, "_fetch_value", lambda *_a: resp
    )
    c = fetch_comps("addr", "key", "home1", 5)[0]
    assert c.sale_date == "2026-06-10"
