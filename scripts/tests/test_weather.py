"""Tests for the weather module: WMO mapping, formatting, thresholds, CLI."""

from __future__ import annotations

import json

import pytest

from vault_scripts import weather
from vault_scripts._types import (
    OpenMeteoDaily,
    OpenMeteoForecastResponse,
    OpenMeteoGeocodingResponse,
    OpenMeteoPlace,
)

# --- WMO mapping ---


def test_wmo_known_codes():
    assert weather.wmo_for(0) == ("☀️", "clear")
    assert weather.wmo_for(45) == ("🌫", "fog")
    assert weather.wmo_for(82) == ("🌧", "rain showers")
    assert weather.wmo_for(99) == ("⛈", "thunderstorm w/ hail")


def test_wmo_unknown_code_falls_back():
    assert weather.wmo_for(42) == weather.UNKNOWN_CODE


# --- Threshold notes ---


def test_no_notes_below_thresholds():
    assert weather.day_notes(75, 60, 0.2, 10.0) == []


def test_precip_note_at_threshold():
    assert weather.day_notes(75, 60, 0.5, 5.0) == ['~0.5" expected.']


def test_wind_note_rounds():
    assert weather.day_notes(75, 60, 0.0, 17.6) == ["18 mph gusts."]


def test_hot_muggy_needs_both_bounds():
    assert weather.day_notes(90, 72, 0.0, 5.0) == ["Hot and muggy day."]
    assert weather.day_notes(90, 65, 0.0, 5.0) == []  # cool night: not muggy
    assert weather.day_notes(85, 72, 0.0, 5.0) == []  # high below the bar


def test_notes_missing_values_do_not_fire():
    assert weather.day_notes(75, 60, None, None) == []


# --- Forecast line ---


def test_forecast_line_plain():
    line = weather.forecast_line("Rome", "🌤", "mainly clear", 74, 57, 27, [])
    assert line == "*Rome Forecast: 🌤 mainly clear, 74° / 57°, 27% rain.*"


def test_forecast_line_with_notes():
    line = weather.forecast_line(
        "Rome", "🌧", "rain showers", 68, 55, 80, ['~0.8" expected.']
    )
    assert line == '*Rome Forecast: 🌧 rain showers, 68° / 55°, 80% rain. ~0.8" expected.*'


def test_forecast_line_rain_unavailable():
    line = weather.forecast_line("Rome", "☀️", "clear", 74, 57, None, [])
    assert "rain n/a" in line


# --- build_days ---


def _resp(**overrides: object) -> OpenMeteoForecastResponse:
    daily = {
        "time": ["2026-07-03", "2026-07-04"],
        "weather_code": [1, 61],
        "temperature_2m_max": [74.4, 67.8],
        "temperature_2m_min": [56.6, 55.2],
        "precipitation_sum": [0.0, 0.62],
        "precipitation_probability_max": [27, 80],
        "wind_speed_10m_max": [8.0, 16.2],
    }
    daily.update(overrides)
    return OpenMeteoForecastResponse(
        timezone="Europe/Rome", daily=OpenMeteoDaily.model_validate(daily)
    )


def test_build_days_formats_and_rounds():
    days = weather.build_days(_resp(), "Rome")
    assert len(days) == 2
    first, second = days
    assert first["date"] == "2026-07-03"
    assert first["high_f"] == 74  # 74.4 rounded
    assert first["low_f"] == 57  # 56.6 rounded
    assert first["line"] == "*Rome Forecast: 🌤 mainly clear, 74° / 57°, 27% rain.*"
    assert second["notes"] == ['~0.6" expected.', "16 mph gusts."]
    assert second["line"].endswith('80% rain. ~0.6" expected. 16 mph gusts.*')


def test_build_days_skips_null_core_values():
    days = weather.build_days(_resp(weather_code=[None, 61]), "Rome")
    assert [d["date"] for d in days] == ["2026-07-04"]


def test_build_days_tolerates_short_optional_arrays():
    days = weather.build_days(
        _resp(precipitation_probability_max=[], wind_speed_10m_max=[]), "Rome"
    )
    assert len(days) == 2
    assert days[0]["rain_pct"] is None
    assert "rain n/a" in days[0]["line"]


# --- CLI ---


def _fake_get(geo: OpenMeteoGeocodingResponse, fc: OpenMeteoForecastResponse):
    def fake(url: str, params: dict[str, str], *, response_model: type):
        if response_model is OpenMeteoGeocodingResponse:
            return geo
        return fc

    return fake


def _run_cli(monkeypatch, capsys, argv: list[str]) -> str:
    monkeypatch.setattr("sys.argv", ["weather", *argv])
    weather.main()
    return capsys.readouterr().out


def test_cli_place_text_output(monkeypatch, capsys):
    geo = OpenMeteoGeocodingResponse(
        results=[
            OpenMeteoPlace(
                name="Rome", latitude=41.9, longitude=12.5, timezone="Europe/Rome"
            )
        ]
    )
    monkeypatch.setattr(weather, "_get", _fake_get(geo, _resp()))
    out = _run_cli(monkeypatch, capsys, ["--place", "Rome", "--days", "2"])
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("2026-07-03  *Rome Forecast:")


def test_cli_latlon_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        weather, "_get", _fake_get(OpenMeteoGeocodingResponse(), _resp())
    )
    out = _run_cli(
        monkeypatch,
        capsys,
        ["--lat", "41.9", "--lon", "12.5", "--label", "Rome", "--json"],
    )
    data = json.loads(out)
    assert data["location"]["label"] == "Rome"
    assert data["location"]["timezone"] == "Europe/Rome"
    assert len(data["days"]) == 2
    assert data["days"][1]["notes"] == ['~0.6" expected.', "16 mph gusts."]


def test_cli_place_not_found_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(
        weather, "_get", _fake_get(OpenMeteoGeocodingResponse(), _resp())
    )
    monkeypatch.setattr("sys.argv", ["weather", "--place", "Nowhereville"])
    with pytest.raises(SystemExit) as exc:
        weather.main()
    assert exc.value.code == 1
    assert "No geocoding match" in capsys.readouterr().err


def test_cli_rejects_place_plus_latlon(monkeypatch):
    monkeypatch.setattr("sys.argv", ["weather", "--place", "Rome", "--lat", "1"])
    with pytest.raises(SystemExit) as exc:
        weather.main()
    assert exc.value.code == 2


def test_cli_rejects_bad_window(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["weather", "--place", "Rome", "--start", "2026-07-10", "--end", "2026-07-01"],
    )
    with pytest.raises(SystemExit) as exc:
        weather.main()
    assert exc.value.code == 2


def test_cli_rejects_oversized_span(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["weather", "--place", "Rome", "--start", "2026-07-01", "--end", "2026-07-30"],
    )
    with pytest.raises(SystemExit) as exc:
        weather.main()
    assert exc.value.code == 2
