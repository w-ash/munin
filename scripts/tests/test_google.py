"""Unit tests for the shared Google auth + transport seam: JWT minting, the
scope-keyed token cache, service-vs-oauth dispatch, and Google error-body to
exit-code mapping. No network — the token exchange and HTTP layer are
monkeypatched."""

from __future__ import annotations

from collections.abc import Iterator
import io

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest
import requests

from vault_scripts import _google
from vault_scripts._types import (
    AccessTokenResponse,
    OAuthInstalledClient,
    OAuthToken,
    ServiceAccountKey,
)


@pytest.fixture(autouse=True)
def _clear_token_cache() -> Iterator[None]:
    """Each test starts with an empty process token cache."""
    _google._token_cache.clear()
    yield
    _google._token_cache.clear()


# --- JWT minting (the one crypto-touching test) ---


def test_build_jwt_roundtrips_multi_scope_claim():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        key
        .public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    sa = ServiceAccountKey(
        client_email="bot@proj.iam.gserviceaccount.com",
        private_key=pem,
    )
    token = _google._build_jwt(sa, ("scope.a", "scope.b"))
    claims = jwt.decode(
        token,
        pub_pem,
        algorithms=["RS256"],
        audience="https://oauth2.googleapis.com/token",
    )
    assert claims["iss"] == "bot@proj.iam.gserviceaccount.com"
    # Multiple scopes join with a space (Google's scope claim format).
    assert claims["scope"] == "scope.a scope.b"


# --- Service-account token: caching keyed by (mode, identity, scope-set) ---


def _stub_service(monkeypatch) -> list[str]:
    """Stub the SA load + JWT build; record each exchange. Returns the token each
    exchange minted (tok0, tok1, ...) so callers can assert how many ran."""
    monkeypatch.setattr(
        _google,
        "_load_service_account",
        lambda _sa_env: ServiceAccountKey(client_email="bot@x", private_key="k"),
    )
    monkeypatch.setattr(_google, "_build_jwt", lambda _sa, _scopes: "signed-jwt")
    minted: list[str] = []

    def fake_exchange(_assertion):
        tok = f"tok{len(minted)}"
        minted.append(tok)
        return AccessTokenResponse(access_token=tok, expires_in=3600)

    monkeypatch.setattr(_google, "_exchange_jwt", fake_exchange)
    return minted


def test_service_token_cached_within_scope(monkeypatch):
    minted = _stub_service(monkeypatch)
    first = _google.get_access_token(("scope.a",), auth="service")
    second = _google.get_access_token(("scope.a",), auth="service")
    assert first == second == "tok0"
    assert len(minted) == 1  # second call hit the cache


def test_service_token_separate_per_scope_set(monkeypatch):
    minted = _stub_service(monkeypatch)
    a = _google.get_access_token(("scope.a",), auth="service")
    b = _google.get_access_token(("scope.b", "scope.c"), auth="service")
    # Different scope sets must not share a cache entry, or Sheets and Docs
    # tokens would collide.
    assert a == "tok0"
    assert b == "tok1"
    assert len(minted) == 2


def test_service_scope_set_order_insensitive(monkeypatch):
    minted = _stub_service(monkeypatch)
    _ = _google.get_access_token(("documents", "drive"), auth="service")
    _ = _google.get_access_token(("drive", "documents"), auth="service")
    # frozenset key — reordering the same scopes reuses the token.
    assert len(minted) == 1


def test_service_exchange_failure_raises_auth_error(monkeypatch):
    monkeypatch.setattr(
        _google,
        "_load_service_account",
        lambda _sa_env: ServiceAccountKey(client_email="bot@x", private_key="k"),
    )
    monkeypatch.setattr(_google, "_build_jwt", lambda _sa, _scopes: "signed-jwt")

    def boom(_assertion):
        raise requests.ConnectionError("token endpoint down")

    monkeypatch.setattr(_google, "_exchange_jwt", boom)
    with pytest.raises(_google.GoogleAuthError):
        _ = _google.get_access_token(("scope.a",), auth="service")


def test_load_service_account_missing_env_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_SA_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_DOCS_SA_JSON", raising=False)
    with pytest.raises(_google.GoogleAuthError):
        _ = _google._load_service_account((
            "GOOGLE_DOCS_SA_JSON",
            "GOOGLE_SHEETS_SA_JSON",
        ))


# --- OAuth-user token ---


def test_oauth_without_stored_token_raises(monkeypatch):
    monkeypatch.setattr(
        _google,
        "_load_oauth_client",
        lambda: OAuthInstalledClient(client_id="cid", client_secret="sec"),
    )
    monkeypatch.setattr(_google, "_load_oauth_token", lambda: None)
    with pytest.raises(_google.GoogleAuthError, match="auth-login"):
        _ = _google.get_access_token(("documents",), auth="oauth")


def test_oauth_refreshes_and_caches(monkeypatch):
    monkeypatch.setattr(
        _google,
        "_load_oauth_client",
        lambda: OAuthInstalledClient(client_id="cid", client_secret="sec"),
    )
    monkeypatch.setattr(
        _google, "_load_oauth_token", lambda: OAuthToken(refresh_token="rt")
    )
    calls: list[str] = []

    def fake_refresh(_client, refresh_token):
        calls.append(refresh_token)
        return AccessTokenResponse(access_token="otok", expires_in=3600)

    monkeypatch.setattr(_google, "_refresh_oauth_token", fake_refresh)
    first = _google.get_access_token(("documents", "drive"), auth="oauth")
    second = _google.get_access_token(("documents", "drive"), auth="oauth")
    assert first == second == "otok"
    assert calls == ["rt"]  # second call hit the cache, no second refresh


def test_service_and_oauth_tokens_do_not_collide(monkeypatch):
    minted = _stub_service(monkeypatch)
    monkeypatch.setattr(
        _google,
        "_load_oauth_client",
        lambda: OAuthInstalledClient(client_id="bot@x", client_secret="sec"),
    )
    monkeypatch.setattr(
        _google, "_load_oauth_token", lambda: OAuthToken(refresh_token="rt")
    )
    monkeypatch.setattr(
        _google,
        "_refresh_oauth_token",
        lambda _c, _rt: AccessTokenResponse(access_token="otok", expires_in=3600),
    )
    svc = _google.get_access_token(("scope.a",), auth="service")
    usr = _google.get_access_token(("scope.a",), auth="oauth")
    # Same identity string and scope, different mode -> different cache entries.
    assert svc == "tok0"
    assert usr == "otok"
    assert len(minted) == 1


# --- Google error-body parsing -> message / exit code ---


def _http_error(status: int, body: str) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    return requests.HTTPError("boom", response=resp)


_PERMISSION_BODY = (
    '{"error":{"code":403,"status":"PERMISSION_DENIED",'
    '"message":"The caller does not have permission"}}'
)
_QUOTA_BODY = (
    '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","message":"Quota exceeded"}}'
)
_AUTH_BODY = (
    '{"error":{"code":401,"status":"UNAUTHENTICATED","message":"Login required"}}'
)


def test_google_error_parses_structured_body():
    err = _google.google_error(_http_error(403, _PERMISSION_BODY))
    assert err is not None
    assert err.status == "PERMISSION_DENIED"
    assert err.code == 403
    assert err.message == "The caller does not have permission"


def test_google_error_none_on_non_json_body():
    assert _google.google_error(_http_error(403, "Forbidden")) is None


def test_google_error_none_on_non_http_error():
    assert _google.google_error(ValueError("nope")) is None


def test_format_api_error_uses_status_and_message():
    msg = _google.format_api_error(_http_error(403, _PERMISSION_BODY))
    assert msg == "PERMISSION_DENIED: The caller does not have permission"


def test_format_api_error_falls_back_to_str():
    e = _http_error(403, "Forbidden")
    assert _google.format_api_error(e) == str(e)


def test_exit_code_permission_from_status():
    assert _google.exit_code_for_api_error(_http_error(403, _PERMISSION_BODY)) == (
        _google.EXIT_PERMISSION
    )


def test_exit_code_auth_from_status():
    assert _google.exit_code_for_api_error(_http_error(401, _AUTH_BODY)) == (
        _google.EXIT_AUTH
    )


def test_exit_code_quota_403_is_api_not_permission():
    # A rate-limit error (RESOURCE_EXHAUSTED) must not be mistaken for a 403 share
    # problem, even if it arrives with a 403 code.
    body = '{"error":{"code":403,"status":"RESOURCE_EXHAUSTED","message":"slow down"}}'
    assert _google.exit_code_for_api_error(_http_error(403, body)) == _google.EXIT_API


def test_exit_code_quota_429_is_api():
    assert _google.exit_code_for_api_error(_http_error(429, _QUOTA_BODY)) == (
        _google.EXIT_API
    )


def test_exit_code_falls_back_to_http_status_without_body():
    assert _google.exit_code_for_api_error(_http_error(403, "Forbidden")) == (
        _google.EXIT_PERMISSION
    )


# --- OAuth-user login flow ---


def test_build_auth_url_includes_offline_consent():
    client = OAuthInstalledClient(client_id="cid", client_secret="sec")
    url = _google._build_auth_url(
        client, "http://localhost:9999", ("documents", "drive")
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/auth?")
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A9999" in url
    assert "scope=documents+drive" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "response_type=code" in url


def test_exchange_auth_code_posts_authorization_code(monkeypatch):
    client = OAuthInstalledClient(client_id="cid", client_secret="sec")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, data=None, **_):
        seen["url"], seen["data"] = url, data
        return AccessTokenResponse(
            access_token="at", refresh_token="rt", expires_in=3600
        )

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    tokens = _google._exchange_auth_code(client, "thecode", "http://localhost:9999")
    assert tokens.refresh_token == "rt"
    assert seen["url"] == client.token_uri
    data = seen["data"]
    assert isinstance(data, dict)
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "thecode"
    assert data["redirect_uri"] == "http://localhost:9999"


def test_store_oauth_token_writes_owner_only(monkeypatch, tmp_path):
    token_path = tmp_path / "oauth.json"
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_JSON", str(token_path))
    stored = _google._store_oauth_token(
        OAuthToken(refresh_token="rt", access_token="at", scopes=["documents"])
    )
    assert stored == token_path
    reloaded = OAuthToken.model_validate_json(token_path.read_text(encoding="utf-8"))
    assert reloaded.refresh_token == "rt"
    # Owner-only permissions (0o600) — the file holds a long-lived refresh token.
    assert (token_path.stat().st_mode & 0o777) == 0o600


# --- OAuth loopback handler: capture code/error, ignore code-less probes ---


class _FakeHandler(_google._CodeHandler):
    """Drive do_GET without the socket machinery: stub the response writes and
    feed a request path directly."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.wfile = io.BytesIO()

    def send_response(self, *_a, **_k) -> None:
        pass

    def send_header(self, *_a, **_k) -> None:
        pass

    def end_headers(self) -> None:
        pass


def _reset_handler() -> None:
    _google._CodeHandler.code = None
    _google._CodeHandler.error = None
    _google._CodeHandler.done = False


def test_code_handler_captures_code():
    _reset_handler()
    _FakeHandler("/?code=abc123&scope=x").do_GET()
    assert _google._CodeHandler.code == "abc123"
    assert _google._CodeHandler.done is True


def test_code_handler_ignores_codeless_probe():
    # A favicon / preconnect hit before the redirect must not end the wait loop.
    _reset_handler()
    _FakeHandler("/favicon.ico").do_GET()
    assert _google._CodeHandler.done is False
    assert _google._CodeHandler.code is None


def test_code_handler_surfaces_consent_error():
    _reset_handler()
    _FakeHandler("/?error=access_denied").do_GET()
    assert _google._CodeHandler.done is True
    assert _google._CodeHandler.error == "access_denied"
    assert _google._CodeHandler.code is None


# --- auth-mode seam (current_auth / using_auth / OAUTH_USER_SCOPES) ---


def test_current_auth_defaults_to_oauth():
    # OAuth-user is the default mode of interacting; service is opt-in.
    assert _google.current_auth() == "oauth"


def test_using_auth_binds_and_restores():
    before = _google.current_auth()
    with _google.using_auth("service"):
        assert _google.current_auth() == "service"
        with _google.using_auth("oauth"):
            assert _google.current_auth() == "oauth"
        assert _google.current_auth() == "service"
    assert _google.current_auth() == before


def test_using_auth_restores_on_exception():
    before = _google.current_auth()
    with pytest.raises(RuntimeError), _google.using_auth("service"):
        raise RuntimeError("boom")
    assert _google.current_auth() == before


def test_oauth_user_scopes_cover_docs_drive_and_sheets():
    # One consent must grant every API the toolchain drives, so a single
    # auth-login (from docs or sheets) is enough.
    assert "https://www.googleapis.com/auth/documents" in _google.OAUTH_USER_SCOPES
    assert "https://www.googleapis.com/auth/spreadsheets" in _google.OAUTH_USER_SCOPES
    assert "https://www.googleapis.com/auth/drive" in _google.OAUTH_USER_SCOPES
