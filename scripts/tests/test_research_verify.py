"""Tests for mechanical citation verification. No live network: fetches are
monkeypatched, so the suite exercises the status logic, quote matching, Wayback
fallback, and the on-disk cache deterministically."""

import ast
from pathlib import Path

import pytest

from vault_scripts.research import verify
from vault_scripts.research.verify import FetchResult

HTML = "<html><body><p>The quick brown fox jumps over the lazy dog.</p></body></html>"


def test_module_uses_314_only_except_syntax() -> None:
    """The module's unparenthesized except-tuples (``except A, B:``) are PEP
    758 syntax, legal on 3.14+ and formatter-enforced here (ruff preview,
    py314). This pins that fact: the source must import on 3.14 but must NOT
    parse under the 3.13 grammar, so a reviewer "fixing" the syntax or a
    requires-python downgrade trips a failure that points at this note."""
    source = Path(verify.__file__).read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 14))
    with pytest.raises(SyntaxError, match="without parentheses"):
        ast.parse(source, feature_version=(3, 13))


def html_page(text: str) -> FetchResult:
    return FetchResult(200, "text/html", f"<html><body>{text}</body></html>")


def fake_fetch(pages: dict[str, FetchResult]):
    def _fetch(url: str, timeout: float) -> FetchResult:
        if url in pages:
            return pages[url]
        raise AssertionError(f"unexpected fetch: {url}")

    return _fetch


# --- quote_present ---


def test_short_quote_exact_match() -> None:
    assert verify.quote_present("brown fox", HTML)


def test_short_quote_absent() -> None:
    assert not verify.quote_present("purple elephant", HTML)


def test_short_quote_must_be_contiguous() -> None:
    # words present but not as a run
    assert not verify.quote_present("fox dog", HTML)


def test_long_quote_shingle_match() -> None:
    quote = "the quick brown fox jumps over the lazy dog"
    assert verify.quote_present(quote, HTML)


def test_long_quote_tolerates_truncation() -> None:
    # >60% of the shingles survive despite a mangled tail word
    page = html_page("the quick brown fox jumps over the lazy dog today in the park")
    quote = "the quick brown fox jumps over the lazy dog today in the end"
    assert verify.quote_present(quote, page.text)


def test_long_quote_below_threshold_fails() -> None:
    quote = "completely different words that share almost nothing with the page content"
    assert not verify.quote_present(quote, HTML)


def test_html_tags_are_stripped() -> None:
    page = "<p>brown <b>fox</b> jumps</p>"
    assert verify.quote_present("brown fox jumps", page)


# --- check_citation ---


def test_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify, "fetch_url", fake_fetch({"u": html_page("hello world")})
    )
    result = verify.check_citation("u", "hello world", cache_dir=None)
    assert result.status == verify.VERIFIED
    assert not result.archived


def test_quote_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify, "fetch_url", fake_fetch({"u": html_page("hello world")})
    )
    result = verify.check_citation("u", "not on the page", cache_dir=None)
    assert result.status == verify.QUOTE_MISSING


def test_no_quote_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    # empty quote must not even attempt a fetch
    monkeypatch.setattr(verify, "fetch_url", fake_fetch({}))
    result = verify.check_citation("u", "   ", cache_dir=None)
    assert result.status == verify.NO_QUOTE


def test_unfetchable_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "u": FetchResult(0, "", ""),
        verify._WAYBACK_API + "u": FetchResult(0, "", ""),
    }
    monkeypatch.setattr(verify, "fetch_url", fake_fetch(pages))
    result = verify.check_citation("u", "anything", cache_dir=None)
    assert result.status == verify.UNFETCHABLE


def test_non_textual_is_unfetchable(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "u": FetchResult(200, "application/pdf", "binary"),
        verify._WAYBACK_API + "u": FetchResult(200, "application/json", "{}"),
    }
    monkeypatch.setattr(verify, "fetch_url", fake_fetch(pages))
    result = verify.check_citation("u", "anything", cache_dir=None)
    assert result.status == verify.UNFETCHABLE


def test_dead_with_no_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "u": FetchResult(404, "text/html", ""),
        verify._WAYBACK_API + "u": FetchResult(
            200, "application/json", '{"archived_snapshots": {}}'
        ),
    }
    monkeypatch.setattr(verify, "fetch_url", fake_fetch(pages))
    result = verify.check_citation("u", "anything", cache_dir=None)
    assert result.status == verify.DEAD
    assert result.http_status == 404


def test_wayback_fallback_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = "https://web.archive.org/snap"
    wayback = (
        '{"archived_snapshots": {"closest": '
        f'{{"available": true, "url": "{snapshot}"}}}}}}'
    )
    pages = {
        "u": FetchResult(404, "text/html", ""),
        verify._WAYBACK_API + "u": FetchResult(200, "application/json", wayback),
        snapshot: html_page("archived hello world"),
    }
    monkeypatch.setattr(verify, "fetch_url", fake_fetch(pages))
    result = verify.check_citation("u", "archived hello world", cache_dir=None)
    assert result.status == verify.VERIFIED
    assert result.archived
    assert result.http_status == 404


# --- cache ---


def test_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    url = "https://example.com/x"
    # seed the cache, then make any real fetch explode
    monkeypatch.setattr(
        verify, "fetch_url", fake_fetch({url: html_page("cached body")})
    )
    first = verify.cached_fetch(url, tmp_path, timeout=1.0)
    assert first.text == html_page("cached body").text

    def boom(u: str, t: float) -> FetchResult:
        raise AssertionError("should have hit the cache")

    monkeypatch.setattr(verify, "fetch_url", boom)
    second = verify.cached_fetch(url, tmp_path, timeout=1.0)
    assert second.text == first.text


def test_connection_failure_not_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    url = "https://example.com/y"
    monkeypatch.setattr(verify, "fetch_url", fake_fetch({url: FetchResult(0, "", "")}))
    verify.cached_fetch(url, tmp_path, timeout=1.0)
    assert not verify._cache_path(tmp_path, url).exists()
