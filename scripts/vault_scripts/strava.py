"""Pull Strava activities into the Eir health-data layers and daily notes.

Implements Eir slice 1 of the trackers framework (canonical-files tier):

- raw layer: every activity as one JSON file under
  ``Health/data/raw/strava/<year>/<date>_<id>.json``, full-fidelity fields as
  received (re-serialized per activity), append-only, skipped when present.
- canonical layer: minimal vendor-neutral rows appended to
  ``Health/data/canonical/activities-<year>.jsonl``, deduped on the Strava
  activity id carried in ``sources[]``. The JSONL is the record; the DuckDB
  cache (``vault-tool db``) is the query layer.
- projection: a per-day training block between ``<!-- eir:start -->`` and
  ``<!-- eir:end -->`` in ``Daily/YYYY-MM-DD.md`` (created data-only when
  missing) plus ``ran_km``/``activity_min`` frontmatter properties. Whole-block
  idempotent rewrite below the divider; Ash's prose zones are never touched
  (daily.md Zone 3).

One-time setup: create an API application at https://www.strava.com/settings/api
with callback domain ``localhost``, put ``STRAVA_CLIENT_ID`` and
``STRAVA_CLIENT_SECRET`` in ``scripts/.env``, then run ``auth`` once.

Examples:

    scripts/vault-tool strava auth
    scripts/vault-tool strava sync                      # dry-run
    scripts/vault-tool strava sync --write
    scripts/vault-tool strava sync --write --project-days 30
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

from pydantic import ValidationError

from vault_scripts._cli import (
    CliError,
    emit_write,
    envelope,
    error_envelope,
    print_json,
)
from vault_scripts._retry import APIError, google_retry, request_validated_json
from vault_scripts._types import (
    CanonicalActivityRow,
    CanonicalSource,
    StravaActivity,
    StravaRawPage,
    StravaToken,
)
from vault_scripts._utils import VAULT, parse_typed_args, patch_field, require_env

_ID_KEY = "source"
_ID_VALUE = "strava"

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"  # noqa: S105 (endpoint URL, not a secret)
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
DEFAULT_TOKEN_PATH = "~/.config/strava/token.json"  # noqa: S105 (path, not a secret)
CALLBACK_PORT = 8723
PER_PAGE = 200
DEFAULT_PROJECT_DAYS = 14
_TOKEN_LEEWAY_S = 60
_HTTP_TIMEOUT_S = 30
_EXIT_API = 5

EIR_START = "<!-- eir:start -->"
EIR_END = "<!-- eir:end -->"
_EIR_BLOCK_RE = re.compile(r"<!-- eir:start -->.*?<!-- eir:end -->", re.DOTALL)
_FM_PARTS = 3

_RAW_DIR_PARTS = ("Health", "data", "raw", "strava")
_CANONICAL_DIR_PARTS = ("Health", "data", "canonical")

# Strava sport_type -> canonical activity type. Unlisted types fall back to
# snake_cased sport_type, so new Strava sports degrade gracefully.
_TYPE_MAP = {
    "Run": "run",
    "TrailRun": "trail_run",
    "VirtualRun": "run",
    "Ride": "ride",
    "VirtualRide": "ride",
    "MountainBikeRide": "ride",
    "GravelRide": "ride",
    "Walk": "walk",
    "Hike": "hike",
    "Swim": "swim",
    "WeightTraining": "strength",
    "Workout": "workout",
    "Yoga": "yoga",
}
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")
_RUN_TYPES = frozenset({"run", "trail_run"})


# --- Token storage + refresh (mirrors the _google OAuth-user pattern) ---


def _token_path() -> Path:
    return Path(os.environ.get("STRAVA_TOKEN_JSON", DEFAULT_TOKEN_PATH)).expanduser()


def _save_token(token: StravaToken) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.model_dump_json(indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _load_token() -> StravaToken:
    path = _token_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CliError(
            f"no Strava token at {path}; run `vault-tool strava auth` first"
        ) from e
    try:
        return StravaToken.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"malformed token file {path}: {e}") from e


@google_retry
def _token_request(data: dict[str, str]) -> StravaToken:
    return request_validated_json(
        "POST",
        TOKEN_URL,
        response_model=StravaToken,
        timeout=_HTTP_TIMEOUT_S,
        data=data,
    )


def _access_token() -> str:
    token = _load_token()
    if token.expires_at - _TOKEN_LEEWAY_S > time.time():
        return token.access_token
    refreshed = _token_request({
        "client_id": require_env("STRAVA_CLIENT_ID"),
        "client_secret": require_env("STRAVA_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
    })
    # Strava rotates the refresh token, but keep the prior one if a response ever
    # omits it: overwriting the stored file with "" would brick every later sync.
    refreshed = refreshed.model_copy(
        update={"refresh_token": refreshed.refresh_token or token.refresh_token}
    )
    _save_token(refreshed)
    return refreshed.access_token


# --- One-time OAuth bootstrap ---


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches Strava's OAuth redirect on the loopback port. A stray probe
    (favicon/preconnect) carries neither ``code`` nor ``error``; it is answered
    but leaves ``done`` False so the wait loop keeps going for the real redirect."""

    code: str | None = None
    error: str | None = None
    done: bool = False

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        codes = query.get("code", [])
        errors = query.get("error", [])
        if codes:
            _CallbackHandler.code = codes[0]
            _CallbackHandler.done = True
            msg = "Authorized. You can close this tab."
        elif errors:
            _CallbackHandler.error = errors[0]
            _CallbackHandler.done = True
            msg = "Authorization failed. You can close this tab."
        else:
            msg = "Waiting for Strava authorization..."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        _ = self.wfile.write(msg.encode())

    def log_message(self, format: str, *args: object) -> None:
        """Silence http.server's per-request stderr logging."""


class _DualStackServer(HTTPServer):
    """Bind the callback on both IPv4 and IPv6 so a ``localhost`` redirect reaches
    it whether the browser resolves ``127.0.0.1`` or ``::1``. Strava validates the
    redirect host against the app's callback domain (``localhost``), so the
    redirect_uri must stay ``localhost`` rather than a bare IP; dual-stack is what
    makes that reachable on IPv6-first hosts."""

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def cmd_auth() -> dict[str, object]:
    client_id = require_env("STRAVA_CLIENT_ID")
    client_secret = require_env("STRAVA_CLIENT_SECRET")
    redirect_uri = f"http://localhost:{CALLBACK_PORT}/exchange_token"
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all",
    })
    print(
        f"Open this URL to authorize (waiting on port {CALLBACK_PORT}):",
        file=sys.stderr,
    )
    print(f"  {AUTH_URL}?{params}", file=sys.stderr)
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    _CallbackHandler.done = False
    server = _DualStackServer(("::", CALLBACK_PORT), _CallbackHandler)
    try:
        while not _CallbackHandler.done:
            server.handle_request()
    finally:
        server.server_close()
    if _CallbackHandler.error:
        raise CliError(f"Strava authorization failed: {_CallbackHandler.error}")
    code = _CallbackHandler.code
    if not code:
        raise CliError("no authorization code received on the callback")
    token = _token_request({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
    })
    _save_token(token)
    return {"stored": str(_token_path()), "scope": "activity:read_all"}


# --- Fetch ---


@google_retry
def _fetch_page(access_token: str, page: int, after: int | None) -> StravaRawPage:
    params = {"per_page": str(PER_PAGE), "page": str(page)}
    if after is not None:
        params["after"] = str(after)
    return request_validated_json(
        "GET",
        ACTIVITIES_URL,
        response_model=StravaRawPage,
        timeout=_HTTP_TIMEOUT_S,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
    )


def _fetch_all(access_token: str, after: int | None) -> list[dict[str, object]]:
    """Page through /athlete/activities. With ``after`` Strava returns
    oldest-first, so pagination stays stable while appending."""
    out: list[dict[str, object]] = []
    page = 1
    while True:
        batch = _fetch_page(access_token, page, after).root
        out.extend(batch)
        if len(batch) < PER_PAGE:
            return out
        page += 1


# --- Canonical mapping + IO ---


def _snake(sport_type: str) -> str:
    return _TYPE_MAP.get(sport_type, _CAMEL_RE.sub("_", sport_type).lower())


def map_activity(a: StravaActivity) -> CanonicalActivityRow:
    return CanonicalActivityRow(
        id=f"act_strava_{a.id}",
        date=a.start_date_local[:10],
        start=a.start_date,
        type=_snake(a.sport_type),
        name=a.name,
        duration_s=a.moving_time,
        distance_m=a.distance,
        elevation_gain_m=a.total_elevation_gain,
        avg_hr=a.average_heartrate,
        max_hr=a.max_heartrate,
        sources=[CanonicalSource(name="strava", source_id=str(a.id))],
    )


def _canonical_dir() -> Path:
    return VAULT.joinpath(*_CANONICAL_DIR_PARTS)


def _raw_dir() -> Path:
    return VAULT.joinpath(*_RAW_DIR_PARTS)


def _read_canonical_rows() -> list[CanonicalActivityRow]:
    rows: list[CanonicalActivityRow] = []
    directory = _canonical_dir()
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("activities-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(CanonicalActivityRow.model_validate_json(line))
            except ValidationError:
                continue  # tolerate a mangled line; the raw layer can re-derive
    return rows


def _known_source_ids(rows: list[CanonicalActivityRow]) -> set[str]:
    return {s.source_id for row in rows for s in row.sources if s.name == "strava"}


def _epoch(iso: str) -> int | None:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return None


def _max_start_epoch(rows: list[CanonicalActivityRow]) -> int | None:
    epochs = [e for row in rows if row.start and (e := _epoch(row.start)) is not None]
    return max(epochs) if epochs else None


def _write_raw(new: list[tuple[dict[str, object], StravaActivity]]) -> int:
    written = 0
    for raw, act in new:
        date_str = act.start_date_local[:10] or "unknown"
        path = _raw_dir() / date_str[:4] / f"{date_str}_{act.id}.json"
        if path.exists():
            continue  # append-only: never rewrite a raw file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written += 1
    return written


def _append_canonical(rows: list[CanonicalActivityRow]) -> dict[str, int]:
    by_year: dict[str, list[CanonicalActivityRow]] = {}
    for row in rows:
        by_year.setdefault(row.date[:4], []).append(row)
    counts: dict[str, int] = {}
    directory = _canonical_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for year, year_rows in sorted(by_year.items()):
        path = directory / f"activities-{year}.jsonl"
        lines = "".join(r.model_dump_json() + "\n" for r in year_rows)
        with path.open("a", encoding="utf-8") as fh:
            _ = fh.write(lines)
        counts[year] = len(year_rows)
    return counts


# --- Daily-note projection (pure string transforms + one writer) ---


def format_duration(seconds: int) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(seconds_per_km: float) -> str:
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d}"


def activity_line(row: CanonicalActivityRow) -> str:
    dur = format_duration(row.duration_s)
    hr = f", avg HR {round(row.avg_hr)}" if row.avg_hr else ""
    km = row.distance_m / 1000
    if row.type in _RUN_TYPES and row.distance_m > 0 and row.duration_s > 0:
        pace = format_pace(row.duration_s / km)
        return f"Ran {km:.1f} km in {dur} ({pace}/km){hr}"
    label = row.type.replace("_", " ").capitalize()
    if row.distance_m > 0:
        return f"{label}: {km:.1f} km in {dur}{hr}"
    return f"{label}: {dur}{hr}"


def render_block(rows: list[CanonicalActivityRow]) -> str:
    lines = "\n".join(
        f"- {activity_line(r)}" for r in sorted(rows, key=lambda r: r.start)
    )
    return f"{EIR_START}\n**Training**\n{lines}\n{EIR_END}"


def upsert_block(text: str, block: str) -> str:
    """Whole-block idempotent rewrite per daily.md Zone 3: replace an existing
    eir block in place; otherwise insert right after the ``---`` divider that
    separates Ash's prose from the synthesis/machine zones. A note without a
    divider gets one appended, then the block."""
    if _EIR_BLOCK_RE.search(text):
        return _EIR_BLOCK_RE.sub(lambda _: block, text, count=1)
    parts = text.split("---", 2)
    if len(parts) == _FM_PARTS:
        prefix = f"{parts[0]}---{parts[1]}---"
        body = parts[2]
    else:
        prefix, body = "", text
    divider = re.search(r"^---$", body, flags=re.MULTILINE)
    if divider:
        at = divider.end()
        return f"{prefix}{body[:at]}\n\n{block}\n{body[at:]}"
    return f"{prefix}{body.rstrip()}\n\n---\n\n{block}\n"


def apply_daily_props(text: str, rows: list[CanonicalActivityRow]) -> str:
    """Upsert the v1 telemetry properties. Frontmatter is machine-writable per
    daily.md Zone 3; prose zones are untouched by construction."""
    run_km = sum(r.distance_m for r in rows if r.type in _RUN_TYPES) / 1000
    active_min = round(sum(r.duration_s for r in rows) / 60)
    out = patch_field(text, "activity_min", active_min)
    if run_km > 0:
        out = patch_field(out, "ran_km", round(run_km, 1))
    return out


def build_daily_note(date_str: str, created: str) -> str:
    """A data-only daily note: template frontmatter and section headings, empty
    prose zones, ready to receive the eir block below the divider."""
    title = date.fromisoformat(date_str).strftime("%A, %B %-d, %Y")
    return (
        "---\n"
        f'created: "{created}"\n'
        f'date: "{date_str}"\n'
        "tags:\n"
        "  - daily\n"
        "---\n\n"
        f"# {title}\n\n"
        "## What happened today\n\n"
        "## How I'm feeling\n\n"
        "## What I want\n\n"
        "---\n\n"
        "## Links & Connections\n"
        "<!-- Added by Claude — wikilinks, backlinks, related notes -->\n"
    )


def _project_daily(by_date: dict[str, list[CanonicalActivityRow]]) -> list[str]:
    written: list[str] = []
    today_str = datetime.now(UTC).astimezone().date().isoformat()
    for date_str, rows in sorted(by_date.items()):
        path = VAULT / "Daily" / f"{date_str}.md"
        original = path.read_text(encoding="utf-8") if path.exists() else None
        base = original if original is not None else build_daily_note(date_str, today_str)
        new_text = apply_daily_props(upsert_block(base, render_block(rows)), rows)
        if new_text != original:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
            written.append(date_str)
    return written


# --- Sync ---


def cmd_sync(project_days: int, *, write: bool) -> None:
    existing = _read_canonical_rows()
    known = _known_source_ids(existing)
    after = _max_start_epoch(existing)
    if after is not None:
        after -= 1  # small overlap; the source_id dedup absorbs it
    raw_activities = _fetch_all(_access_token(), after)
    parsed = [(d, StravaActivity.model_validate(d)) for d in raw_activities]
    # Dedup against known canonical ids AND within this batch: a page-boundary
    # repeat (an activity recorded mid-sync shifts the boundary) would otherwise
    # write a permanent duplicate row and double-count the day's totals.
    seen = set(known)
    new: list[tuple[dict[str, object], StravaActivity]] = []
    for d, a in parsed:
        sid = str(a.id)
        if sid in seen:
            continue
        seen.add(sid)
        new.append((d, a))
    new_rows = [map_activity(a) for _, a in new]

    cutoff = datetime.now(UTC).astimezone().date() - timedelta(days=project_days)
    by_date: dict[str, list[CanonicalActivityRow]] = {}
    for row in existing + new_rows:
        if row.date and date.fromisoformat(row.date) >= cutoff:
            by_date.setdefault(row.date, []).append(row)

    notes_create: list[str] = []
    notes_update: list[str] = []
    for date_str in sorted(by_date):
        target = notes_update if (VAULT / "Daily" / f"{date_str}.md").exists() else notes_create
        target.append(date_str)

    plan: dict[str, object] = {
        "fetched": len(raw_activities),
        "newActivities": len(new_rows),
        "projectionWindowDays": project_days,
        "dailyNotesToUpdate": notes_update,
        "dailyNotesToCreate": notes_create,
    }

    def apply() -> dict[str, object]:
        return {
            **plan,
            "rawFilesWritten": _write_raw(new),
            "canonicalAppended": _append_canonical(new_rows),
            "dailyNotesWritten": _project_daily(by_date),
        }

    emit_write("sync", _ID_KEY, _ID_VALUE, write=write, dry=plan, apply=apply)


class _Args(argparse.Namespace):
    command: str
    write: bool
    project_days: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strava -> Eir raw/canonical layers + daily-note projection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _ = sub.add_parser("auth", help="one-time OAuth bootstrap (writes the token file)")
    sync_p = sub.add_parser(
        "sync", help="pull activities into raw/canonical + daily notes"
    )
    _ = sync_p.add_argument(
        "--write", action="store_true", help="apply (default: dry-run plan)"
    )
    _ = sync_p.add_argument(
        "--project-days",
        type=int,
        default=DEFAULT_PROJECT_DAYS,
        dest="project_days",
        help=f"daily-note projection window (default {DEFAULT_PROJECT_DAYS} days)",
    )
    args = parse_typed_args(parser, _Args)
    try:
        if args.command == "auth":
            print_json(envelope("auth", _ID_KEY, _ID_VALUE, cmd_auth()))
        else:
            cmd_sync(args.project_days, write=args.write)
    except CliError as e:
        print_json(error_envelope(args.command, _ID_KEY, _ID_VALUE, str(e)))
        sys.exit(e.code)
    except APIError as e:
        print_json(error_envelope(args.command, _ID_KEY, _ID_VALUE, f"strava api: {e}"))
        sys.exit(_EXIT_API)


if __name__ == "__main__":
    main()
