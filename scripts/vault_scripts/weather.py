"""Fetch and format per-day weather forecast lines via Open-Meteo.

The deterministic half of the weather skill lives here: geocoding, the
forecast fetch, WMO code to emoji/label mapping, temperature rounding, the
percent-rain figure, and the inline threshold notes. The skill only
orchestrates vault edits and writes the Conditions prose.

Usage:
    scripts/vault-tool weather --place "Rome" --days 3
    scripts/vault-tool weather --place "Rome" --start 2026-07-10 --end 2026-07-14
    scripts/vault-tool weather --lat 41.9028 --lon 12.4964 --label "Rome" --days 5
    scripts/vault-tool weather --place "Rome" --days 3 --json

Text output prints one finished italic ``Forecast:`` line per day, ready to
paste under a day heading. ``--json`` adds the raw per-day values (high/low,
rain %, precip, wind, code) that ground the Conditions prose.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys

from pydantic import BaseModel

from vault_scripts._retry import APIError, google_retry, request_validated_json
from vault_scripts._types import (
    OpenMeteoForecastResponse,
    OpenMeteoGeocodingResponse,
    OpenMeteoPlace,
    WeatherDay,
)
from vault_scripts._utils import parse_typed_args

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT_S = 15
# Open-Meteo's forecast endpoint serves at most 16 days ahead.
MAX_FORECAST_DAYS = 16
DEFAULT_FORECAST_DAYS = 7

# The daily variables the skill's Forecast/Conditions lines are built from.
DAILY_FIELDS: tuple[str, ...] = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)

# Inline-note thresholds, mirrored from the weather skill's rules: enough rain
# to shape the day's plan, wind worth flagging for open-air activities, and
# the hot-plus-muggy combination (both bounds must hold).
PRECIP_NOTE_IN = 0.5
WIND_NOTE_MPH = 15
HOT_MAX_F = 88
HOT_MIN_F = 70

# WMO weather code -> (emoji, label), matching the skill's table.
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "clear"),
    1: ("🌤", "mainly clear"),
    2: ("⛅", "partly cloudy"),
    3: ("☁️", "overcast"),
    45: ("🌫", "fog"),
    48: ("🌫", "fog"),
    51: ("🌦", "light drizzle"),
    53: ("🌦", "moderate drizzle"),
    55: ("🌦", "dense drizzle"),
    56: ("🌧", "freezing drizzle"),
    57: ("🌧", "freezing drizzle"),
    61: ("🌧", "light rain"),
    63: ("🌧", "moderate rain"),
    65: ("🌧", "heavy rain"),
    66: ("🌧", "freezing rain"),
    67: ("🌧", "freezing rain"),
    71: ("❄️", "snow"),
    73: ("❄️", "snow"),
    75: ("❄️", "snow"),
    77: ("❄️", "snow"),
    80: ("🌧", "rain showers"),
    81: ("🌧", "rain showers"),
    82: ("🌧", "rain showers"),
    85: ("❄️", "snow showers"),
    86: ("❄️", "snow showers"),
    95: ("⛈", "thunderstorm"),
    96: ("⛈", "thunderstorm w/ hail"),
    99: ("⛈", "thunderstorm w/ hail"),
}
# Fallback for a code outside the table (new/rare WMO codes).
UNKNOWN_CODE: tuple[str, str] = ("🌡", "unknown conditions")


# --- HTTP ---


@google_retry
def _get[M: BaseModel](
    url: str, params: dict[str, str], *, response_model: type[M]
) -> M:
    """GET an Open-Meteo endpoint with the shared retry policy."""
    return request_validated_json(
        "GET",
        url,
        response_model=response_model,
        params=params,
        timeout=OPEN_METEO_TIMEOUT_S,
    )


def geocode_place(place: str) -> OpenMeteoPlace | None:
    """Resolve a free-text place name to coordinates (top match or None)."""
    resp = _get(
        GEOCODING_URL,
        {"name": place, "count": "1", "language": "en", "format": "json"},
        response_model=OpenMeteoGeocodingResponse,
    )
    return resp.results[0] if resp.results else None


def fetch_daily(
    lat: float,
    lon: float,
    *,
    start: date | None = None,
    end: date | None = None,
    days: int = DEFAULT_FORECAST_DAYS,
) -> OpenMeteoForecastResponse:
    """Fetch the daily forecast in the skill's units (F, inch, mph).

    ``start``/``end`` select an explicit date window; otherwise ``days``
    from today. ``timezone=auto`` makes the returned dates local to the
    location.
    """
    params: dict[str, str] = {
        "latitude": str(lat),
        "longitude": str(lon),
        "daily": ",".join(DAILY_FIELDS),
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "wind_speed_unit": "mph",
        "timezone": "auto",
    }
    if start is not None and end is not None:
        params["start_date"] = start.isoformat()
        params["end_date"] = end.isoformat()
    else:
        params["forecast_days"] = str(days)
    return _get(FORECAST_URL, params, response_model=OpenMeteoForecastResponse)


# --- Formatting (pure; unit-tested) ---


def wmo_for(code: int) -> tuple[str, str]:
    """(emoji, label) for a WMO weather code, with an explicit fallback."""
    return WMO_CODES.get(code, UNKNOWN_CODE)


def day_notes(
    high_f: int, low_f: int, precip_in: float | None, wind_mph: float | None
) -> list[str]:
    """Inline notes appended to the Forecast line when thresholds are met."""
    notes: list[str] = []
    if precip_in is not None and precip_in >= PRECIP_NOTE_IN:
        notes.append(f'~{precip_in:.1f}" expected.')
    if wind_mph is not None and wind_mph >= WIND_NOTE_MPH:
        notes.append(f"{round(wind_mph)} mph gusts.")
    if high_f >= HOT_MAX_F and low_f >= HOT_MIN_F:
        notes.append("Hot and muggy day.")
    return notes


def forecast_line(
    label: str,
    emoji: str,
    sky: str,
    high_f: int,
    low_f: int,
    rain_pct: int | None,
    notes: list[str],
) -> str:
    """The finished italic Forecast line in the skill's exact format."""
    rain = f"{rain_pct}% rain" if rain_pct is not None else "rain n/a"
    line = f"*{label} Forecast: {emoji} {sky}, {high_f}° / {low_f}°, {rain}."
    if notes:
        line += " " + " ".join(notes)
    return line + "*"


def build_days(resp: OpenMeteoForecastResponse, label: str) -> list[WeatherDay]:
    """Turn the parallel daily arrays into one formatted record per day.

    Days whose core values (code, high, low) are null are skipped: they are
    dates the model has no data for, and a partial line would be misleading.
    """
    d = resp.daily
    days: list[WeatherDay] = []
    for i, day_iso in enumerate(d.time):
        code = d.weather_code[i] if i < len(d.weather_code) else None
        high = d.temperature_2m_max[i] if i < len(d.temperature_2m_max) else None
        low = d.temperature_2m_min[i] if i < len(d.temperature_2m_min) else None
        if code is None or high is None or low is None:
            continue
        precip = d.precipitation_sum[i] if i < len(d.precipitation_sum) else None
        rain = (
            d.precipitation_probability_max[i]
            if i < len(d.precipitation_probability_max)
            else None
        )
        wind = d.wind_speed_10m_max[i] if i < len(d.wind_speed_10m_max) else None
        emoji, sky = wmo_for(code)
        high_f, low_f = round(high), round(low)
        notes = day_notes(high_f, low_f, precip, wind)
        days.append(
            WeatherDay(
                date=day_iso,
                code=code,
                emoji=emoji,
                label=sky,
                high_f=high_f,
                low_f=low_f,
                rain_pct=rain,
                precip_in=precip,
                wind_mph=wind,
                notes=notes,
                line=forecast_line(label, emoji, sky, high_f, low_f, rain, notes),
            )
        )
    return days


# --- CLI ---


class _Args(argparse.Namespace):
    place: str | None
    lat: float | None
    lon: float | None
    label: str | None
    days: int
    start: str | None
    end: str | None
    json: bool


def _parse_iso(parser: argparse.ArgumentParser, value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        parser.error(f"{flag} must be YYYY-MM-DD, got {value!r}")


def _validate_window(
    parser: argparse.ArgumentParser, args: _Args
) -> tuple[date | None, date | None]:
    """Resolve --start/--end/--days into a fetch window, rejecting bad combos."""
    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be given together")
    if not 1 <= args.days <= MAX_FORECAST_DAYS:
        parser.error(f"--days must be 1..{MAX_FORECAST_DAYS}")
    if args.start is None or args.end is None:
        return None, None
    start = _parse_iso(parser, args.start, "--start")
    end = _parse_iso(parser, args.end, "--end")
    if end < start:
        parser.error("--end is before --start")
    if (end - start).days + 1 > MAX_FORECAST_DAYS:
        parser.error(f"--start/--end span exceeds {MAX_FORECAST_DAYS} days")
    return start, end


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-day weather forecast lines via Open-Meteo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _ = parser.add_argument("--place", help="Free-text place to geocode")
    _ = parser.add_argument("--lat", type=float, help="Latitude (with --lon)")
    _ = parser.add_argument("--lon", type=float, help="Longitude (with --lat)")
    _ = parser.add_argument(
        "--label", help="Location label in the Forecast lines (default: place name)"
    )
    _ = parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_FORECAST_DAYS,
        help=f"Days from today, 1..{MAX_FORECAST_DAYS} (default"
        f" {DEFAULT_FORECAST_DAYS}); ignored when --start/--end given",
    )
    _ = parser.add_argument("--start", help="Window start, YYYY-MM-DD")
    _ = parser.add_argument("--end", help="Window end, YYYY-MM-DD")
    _ = parser.add_argument(
        "--json", action="store_true", help="Structured output for prose grounding"
    )
    args = parse_typed_args(parser, _Args)

    if args.place is not None and (args.lat is not None or args.lon is not None):
        parser.error("give --place or --lat/--lon, not both")
    if args.place is None and (args.lat is None or args.lon is None):
        parser.error("give --place, or both --lat and --lon")
    start, end = _validate_window(parser, args)

    try:
        if args.place is not None:
            found = geocode_place(args.place)
            if found is None:
                print(f"No geocoding match for {args.place!r}", file=sys.stderr)
                sys.exit(1)
            lat, lon = found.latitude, found.longitude
            label = args.label or found.name or args.place
            where = {
                "name": found.name,
                "admin1": found.admin1,
                "country_code": found.country_code,
                "latitude": lat,
                "longitude": lon,
            }
        else:
            assert args.lat is not None  # validated above  # noqa: S101
            assert args.lon is not None  # validated above  # noqa: S101
            lat, lon = args.lat, args.lon
            label = args.label or f"{lat}, {lon}"
            where = {"latitude": lat, "longitude": lon}
        resp = fetch_daily(lat, lon, start=start, end=end, days=args.days)
    except APIError as e:
        print(f"Open-Meteo request failed: {e}", file=sys.stderr)
        sys.exit(1)

    days = build_days(resp, label)
    if not days:
        print("Open-Meteo returned no usable days for that window", file=sys.stderr)
        sys.exit(1)

    if args.json:
        out: dict[str, object] = {
            "location": {**where, "label": label, "timezone": resp.timezone},
            "days": days,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    for day in days:
        print(f"{day['date']}  {day['line']}")


if __name__ == "__main__":
    main()
