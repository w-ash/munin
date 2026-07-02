"""Shared Google auth and transport for the vault toolchain.

Two auth modes sit behind one seam so Sheets and Docs can share everything but
their scopes and base URLs:

- **service account** (JWT-bearer): unattended. Mint a signed JWT (RS256) from a
  service-account key, exchange it for a short-lived bearer token, cache it.
  Reads and in-place edits of resources shared with the account. The current
  Sheets model. Cannot own files.
- **oauth user**: acts as the user. A one-time installed-app consent (run by
  ``docs auth-login``) yields a stored refresh token, refreshed silently after.
  Can own files (creation, copy, whole Drive).

Both modes yield an opaque bearer token consumed by the same REST helper, retry
policy, and Pydantic models; only :func:`get_access_token` knows the difference.
The token cache is keyed by ``(mode, identity, scope-set)`` so a Sheets token
(``spreadsheets``) and a Docs token (``documents`` + ``drive``) never collide.

Share each target resource with the service account's ``client_email`` (Editor
to write, Viewer to read), or service-account calls come back 403.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import sys
import time
from typing import Literal, cast
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import jwt
from pydantic import BaseModel, ValidationError
import requests

from vault_scripts._retry import APIError, google_retry, request_validated_json
from vault_scripts._types import (
    AccessTokenResponse,
    GoogleApiError,
    GoogleApiErrorEnvelope,
    OAuthClientConfig,
    OAuthInstalledClient,
    OAuthToken,
    ServiceAccountKey,
)

# OAuth2 token endpoint, identical across all Google service accounts, so we
# use it directly instead of the per-key token_uri.
OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
GOOGLE_TIMEOUT_S = 15

# Service-account key env var(s). Docs may set its own pointing at the same key;
# callers pass the lookup order they want (see DOCS_SA_ENV in _docs).
DEFAULT_SA_ENV: tuple[str, ...] = ("GOOGLE_SHEETS_SA_JSON",)
# OAuth client-secrets path and stored-token path. The S105 noqas mark these as
# an env-var name and a file path, not the secrets themselves.
OAUTH_CLIENT_ENV = "GOOGLE_OAUTH_CLIENT_JSON"
OAUTH_TOKEN_ENV = "GOOGLE_OAUTH_TOKEN_JSON"  # noqa: S105
DEFAULT_OAUTH_TOKEN = "~/.config/gcp/docs-oauth.json"  # noqa: S105

_TOKEN_TTL_S = 3600
# Treat the token as expired this many seconds early, so a long batch can't
# straddle the boundary and 401 mid-run.
_TOKEN_LEEWAY_S = 60
# Backdate the JWT iat slightly so a client clock running a few seconds ahead of
# Google's doesn't trip "token used too early"; exp stays iat+TTL so the assertion
# window stays <= 3600s (Google's max).
_CLOCK_SKEW_S = 10

AuthMode = Literal["service", "oauth"]

# Scopes the one-time OAuth-user consent requests: the union of every Google API
# the toolchain drives (Docs, Drive, Sheets), so a single `auth-login` grants all
# of them. Each API call still requests only its own scope subset for the token
# cache key; the granted token is a superset, which Google accepts.
OAUTH_USER_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)

# The auth mode for the current invocation. OAuth-user is the default mode of
# interacting (acts as the user, owns the files it creates); `--auth service` opts into
# the sandboxed service account. Set once per run by the CLI (see _cli.run_cli);
# read by the per-API request wrappers that don't thread an explicit auth argument.
_auth_mode: ContextVar[AuthMode] = ContextVar("auth_mode", default="oauth")


def current_auth() -> AuthMode:
    """The auth mode for the current invocation (oauth unless set otherwise)."""
    return _auth_mode.get()


@contextmanager
def using_auth(mode: AuthMode) -> Generator[None]:
    """Bind the active auth mode for the duration of the block, then restore it."""
    token = _auth_mode.set(mode)
    try:
        yield
    finally:
        _auth_mode.reset(token)


class GoogleAuthError(Exception):
    """The credential is missing, unreadable, or malformed, or a token exchange
    failed. Distinct from an API 401/403 (those arrive as ``requests.HTTPError``
    inside :data:`APIError`); this fires before any data call, so the CLI maps
    it to the auth exit code without inspecting an HTTP response."""


# (mode, identity, scope-set) -> (access_token, monotonic_expiry). Mint once per
# process run so a batch of calls shares one token instead of re-minting. Keying
# on the scope-set keeps Sheets and Docs tokens from colliding.
_token_cache: dict[tuple[str, str, frozenset[str]], tuple[str, float]] = {}


# --- Service-account auth ---


def _load_service_account(sa_env: tuple[str, ...]) -> ServiceAccountKey:
    """Load and validate the key referenced by the first set env var in ``sa_env``.

    Raises :class:`GoogleAuthError` on no set env var, an unreadable file, or JSON
    missing ``client_email`` / ``private_key``.
    """
    chosen_env = ""
    path_str = ""
    for env in sa_env:
        value = os.environ.get(env)
        if value:
            chosen_env, path_str = env, value
            break
    if not path_str:
        raise GoogleAuthError(f"Missing env var: {' or '.join(sa_env)}")
    path = Path(path_str).expanduser()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise GoogleAuthError(f"Cannot read {chosen_env} file {path}: {e}") from e
    try:
        return ServiceAccountKey.model_validate_json(raw)
    except ValidationError as e:
        raise GoogleAuthError(f"Malformed service-account key {path}: {e}") from e


def _build_jwt(sa: ServiceAccountKey, scopes: Sequence[str]) -> str:
    """Build a JWT asserting the SA's identity and the requested scopes, signed
    with the account's RSA private key (RS256, as Google requires)."""
    iat = int(time.time()) - _CLOCK_SKEW_S
    claims: dict[str, object] = {
        "iss": sa.client_email,
        "scope": " ".join(scopes),
        "aud": OAUTH_ENDPOINT,
        "iat": iat,
        "exp": iat + _TOKEN_TTL_S,
    }
    return jwt.encode(claims, sa.private_key, algorithm="RS256")


@google_retry
def _exchange_jwt(assertion: str) -> AccessTokenResponse:
    """Exchange a signed JWT for an OAuth2 access token. Retries transient 5xx."""
    return request_validated_json(
        "POST",
        OAUTH_ENDPOINT,
        response_model=AccessTokenResponse,
        data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion},
        timeout=GOOGLE_TIMEOUT_S,
    )


# --- OAuth-user auth ---


def _load_oauth_client() -> OAuthInstalledClient:
    """Load the Desktop OAuth client-secrets file named by ``GOOGLE_OAUTH_CLIENT_JSON``."""
    path_str = os.environ.get(OAUTH_CLIENT_ENV)
    if not path_str:
        raise GoogleAuthError(f"Missing env var: {OAUTH_CLIENT_ENV}")
    path = Path(path_str).expanduser()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise GoogleAuthError(f"Cannot read {OAUTH_CLIENT_ENV} file {path}: {e}") from e
    try:
        cfg = OAuthClientConfig.model_validate_json(raw)
    except ValidationError as e:
        raise GoogleAuthError(f"Malformed OAuth client file {path}: {e}") from e
    client = cfg.installed or cfg.web
    if client is None:
        raise GoogleAuthError(
            f"OAuth client file {path} has neither an 'installed' nor 'web' block"
        )
    return client


def oauth_token_path() -> Path:
    """The stored-token path (``GOOGLE_OAUTH_TOKEN_JSON`` or the default)."""
    return Path(os.environ.get(OAUTH_TOKEN_ENV, DEFAULT_OAUTH_TOKEN)).expanduser()


def _load_oauth_token() -> OAuthToken | None:
    """Read the stored OAuth token, or None when it does not exist yet."""
    path = oauth_token_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return OAuthToken.model_validate_json(raw)
    except ValidationError as e:
        raise GoogleAuthError(f"Malformed OAuth token {path}: {e}") from e


@google_retry
def _refresh_oauth_token(
    client: OAuthInstalledClient, refresh_token: str
) -> AccessTokenResponse:
    """Exchange a stored refresh token for a fresh access token."""
    return request_validated_json(
        "POST",
        client.token_uri,
        response_model=AccessTokenResponse,
        data={
            "grant_type": "refresh_token",
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "refresh_token": refresh_token,
        },
        timeout=GOOGLE_TIMEOUT_S,
    )


# --- OAuth-user login (one-time installed-app consent) ---


def _build_auth_url(
    client: OAuthInstalledClient, redirect_uri: str, scopes: Sequence[str]
) -> str:
    """Build the consent URL for the installed-app loopback flow. ``access_type
    offline`` plus ``prompt consent`` ensure Google returns a refresh token."""
    params = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{client.auth_uri}?{urlencode(params)}"


@google_retry
def _exchange_auth_code(
    client: OAuthInstalledClient, code: str, redirect_uri: str
) -> AccessTokenResponse:
    """Exchange a one-time authorization code for access + refresh tokens."""
    return request_validated_json(
        "POST",
        client.token_uri,
        response_model=AccessTokenResponse,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=GOOGLE_TIMEOUT_S,
    )


def _store_oauth_token(token: OAuthToken) -> Path:
    """Write the token to the stored-token path, owner-readable only."""
    path = oauth_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(token.model_dump_json(indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


class _CodeHandler(BaseHTTPRequestHandler):
    """One-shot loopback handler that captures the ``code`` (or ``error``) from
    the consent redirect. Requests carrying neither (a browser favicon or
    preconnect probe to the loopback port) are answered but left ``done=False``
    so they don't abort the wait."""

    code: str | None = None
    error: str | None = None
    done: bool = False

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        codes = query.get("code", [])
        errors = query.get("error", [])
        if codes:
            _CodeHandler.code = codes[0]
            _CodeHandler.done = True
            message = b"Authorization complete. You can close this tab."
        elif errors:
            _CodeHandler.error = errors[0]
            _CodeHandler.done = True
            message = b"Authorization failed. You can close this tab."
        else:
            message = b"Waiting for Google authorization..."
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        _ = self.wfile.write(b"<html><body>" + message + b"</body></html>")

    def log_message(self, format: str, *args: object) -> None:
        """Silence default request logging; it would print the code to stderr."""


def oauth_login(scopes: Sequence[str]) -> OAuthToken:
    """Run the one-time installed-app consent flow and store the refresh token.

    Opens the browser to Google's consent screen, captures the redirect on a
    loopback port, exchanges the code, and writes the token to disk. Interactive;
    invoked by ``docs auth-login``.
    """
    client = _load_oauth_client()
    server = HTTPServer(("127.0.0.1", 0), _CodeHandler)
    port = cast(tuple[str, int], server.server_address)[1]
    # Match the IPv4 bind: on hosts where ``localhost`` resolves to ``::1`` first,
    # a ``localhost`` redirect would hit IPv6 and never reach this listener.
    redirect_uri = f"http://127.0.0.1:{port}"
    auth_url = _build_auth_url(client, redirect_uri, scopes)
    print(
        f"Opening browser for Google consent. If it doesn't open, visit:\n{auth_url}",
        file=sys.stderr,
    )
    _ = webbrowser.open(auth_url)
    _CodeHandler.code = None
    _CodeHandler.error = None
    _CodeHandler.done = False
    while not _CodeHandler.done:
        server.handle_request()
    code = _CodeHandler.code
    error = _CodeHandler.error
    server.server_close()
    if error:
        raise GoogleAuthError(f"consent flow failed: {error}")
    if not code:
        raise GoogleAuthError("consent flow returned no authorization code")
    tokens = _exchange_auth_code(client, code, redirect_uri)
    if not tokens.refresh_token:
        raise GoogleAuthError(
            "consent returned no refresh token; revoke the prior grant and retry"
        )
    token = OAuthToken(
        refresh_token=tokens.refresh_token,
        access_token=tokens.access_token,
        scopes=list(scopes),
    )
    _ = _store_oauth_token(token)
    return token


# --- Token seam ---


def get_access_token(
    scopes: Sequence[str],
    *,
    auth: AuthMode,
    sa_env: tuple[str, ...] = DEFAULT_SA_ENV,
) -> str:
    """Return a cached or freshly minted bearer token for ``scopes`` under ``auth``.

    The only function that distinguishes service-account from OAuth-user auth;
    everything downstream consumes an opaque token.
    """
    scope_key = frozenset(scopes)
    if auth == "service":
        # Key on the env-var lookup (stable within a process) and check the cache
        # before touching disk, so a cached token doesn't re-read and re-parse the
        # service-account JSON on every call.
        cache_key = ("service", ",".join(sa_env), scope_key)
        cached = _token_cache.get(cache_key)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]
        sa = _load_service_account(sa_env)
        # A token-exchange failure (Google returns HTTP 400 invalid_grant for a
        # bad/expired/clock-skewed key or missing scope) is an auth problem.
        # GoogleAuthError both maps it to the auth exit code and stops the outer
        # retry from re-amplifying _exchange_jwt's retries.
        try:
            token = _exchange_jwt(_build_jwt(sa, scopes))
        except APIError as e:
            raise GoogleAuthError(f"token exchange failed: {e}") from e
    else:
        # Key on the env-var-derived client/token paths (stable within a process)
        # and check the cache before touching disk, mirroring the service branch:
        # a cached token must not re-read and re-parse both credential JSONs on
        # every call.
        identity = f"{os.environ.get(OAUTH_CLIENT_ENV, '')}|{oauth_token_path()}"
        cache_key = ("oauth", identity, scope_key)
        cached = _token_cache.get(cache_key)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]
        client = _load_oauth_client()
        stored = _load_oauth_token()
        if stored is None or not stored.refresh_token:
            raise GoogleAuthError(
                "no stored OAuth token; run `vault-tool docs auth-login` first"
            )
        try:
            token = _refresh_oauth_token(client, stored.refresh_token)
        except APIError as e:
            raise GoogleAuthError(f"OAuth token refresh failed: {e}") from e
    expiry = time.monotonic() + token.expires_in - _TOKEN_LEEWAY_S
    _token_cache[cache_key] = (token.access_token, expiry)
    return token.access_token


# --- Authenticated REST helper ---


def authed_request[M: BaseModel](
    method: str,
    url: str,
    *,
    response_model: type[M],
    scopes: Sequence[str],
    auth: AuthMode,
    sa_env: tuple[str, ...] = DEFAULT_SA_ENV,
    params: dict[str, str] | None = None,
    json: object | None = None,
    idempotent: bool = True,
) -> M:
    """Issue an authenticated JSON REST call, validated against ``response_model``.

    The shared transport for every Sheets and Docs JSON call: a Bearer header for
    the right token, with transient classification and JSON validation delegated
    to ``request_validated_json``. Non-JSON paths (Drive export bytes, Markdown
    multipart import) build their own requests on :func:`get_access_token`.

    ``idempotent`` defaults to True (reads and fixed-range overwrites retry on
    transient transport errors). Pass ``idempotent=False`` for non-idempotent
    writes (row append, resource create/copy, document batchUpdate): the call runs
    once, so a timeout/reset *after* the server applied the change can't be retried
    into a duplicate row or document.
    """

    def call() -> M:
        return request_validated_json(
            method,
            url,
            response_model=response_model,
            params=params,
            json=json,
            headers={
                "Authorization": f"Bearer {get_access_token(scopes, auth=auth, sa_env=sa_env)}",
                "Content-Type": "application/json",
            },
            timeout=GOOGLE_TIMEOUT_S,
        )

    if idempotent:
        return google_retry(call)()
    return call()


# --- Google error body -> message / exit code ---

EXIT_VALIDATION = 2
EXIT_AUTH = 3
EXIT_PERMISSION = 4
EXIT_API = 5

_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403


def google_error(e: BaseException) -> GoogleApiError | None:
    """Parse Google's structured error body, ``{"error": {code, status, message}}``,
    from a failed request. Returns None when the failure isn't an HTTPError with a
    JSON body (callers fall back to the raw exception text)."""
    if not (isinstance(e, requests.HTTPError) and e.response is not None):
        return None
    try:
        return GoogleApiErrorEnvelope.model_validate_json(e.response.content).error
    except ValidationError:
        return None


def format_api_error(e: BaseException) -> str:
    """A human error string: ``"<STATUS>: <message>"`` when Google's body parsed,
    else the exception's own text."""
    err = google_error(e)
    if err is not None and err.message:
        return f"{err.status}: {err.message}" if err.status else err.message
    return str(e)


def exit_code_for_api_error(e: BaseException) -> int:
    """Map an API error to an exit code, preferring Google's machine ``status`` when
    the body parsed: auth (401 / UNAUTHENTICATED), permission (403 / PERMISSION_DENIED),
    else generic API. A 403 that's really a rate limit (RESOURCE_EXHAUSTED) is API, not
    permission. Falls back to the HTTP status code when no body parses."""
    err = google_error(e)
    if err is not None:
        if err.status == "RESOURCE_EXHAUSTED":
            return EXIT_API
        if err.code == _HTTP_UNAUTHORIZED or err.status == "UNAUTHENTICATED":
            return EXIT_AUTH
        if err.code == _HTTP_FORBIDDEN or err.status == "PERMISSION_DENIED":
            return EXIT_PERMISSION
    if isinstance(e, requests.HTTPError) and e.response is not None:
        status = e.response.status_code
        if status == _HTTP_UNAUTHORIZED:
            return EXIT_AUTH
        if status == _HTTP_FORBIDDEN:
            return EXIT_PERMISSION
    return EXIT_API
