"""Tests for mechanical citation verification and its scoring feedback."""

import json
from pathlib import Path

import pytest
import requests

from vault_scripts import evidence
from vault_scripts._types import CitationRecord, EvidenceItem


def item(
    quote: str = "the exact quoted words",
    source_url: str = "https://a.org/1",
    claim_id: str = "c1",
    strength: str = "strong",
    bearing: str = "supports",
) -> EvidenceItem:
    return EvidenceItem.model_validate(
        {
            "claim_id": claim_id,
            "source_url": source_url,
            "source_tier": "primary",
            "bearing": bearing,
            "strength": strength,
            "quote": quote,
        }
    )


# --- quote matching (pure) ---


def test_quote_present_exact_and_case_insensitive():
    assert evidence.quote_present("Hello World", "<p>hello,\n WORLD!</p>")


def test_quote_present_ignores_markup_and_entities():
    page = "<div>it&rsquo;s a <b>fine</b> day &amp; night</div>"
    assert evidence.quote_present("it's a fine day & night", page)


def test_quote_present_strips_script_bodies():
    page = "<script>var quoted = 'the secret words';</script><p>other text</p>"
    assert not evidence.quote_present("the secret words", page)


def test_quote_present_tolerates_partial_shingle_match():
    quote = "one two three four five six seven eight nine ten"
    page = "prefix one two three four five six seven eight END different tail"
    assert evidence.quote_present(quote, page)  # most shingles survive


def test_quote_present_rejects_absent_quote():
    assert not evidence.quote_present("completely absent words", "<p>unrelated page</p>")


def test_quote_present_short_quote_needs_exact_run():
    assert evidence.quote_present("just five", "<p>we said just five words</p>")
    assert not evidence.quote_present("just five", "<p>just about five</p>")


# --- check_citation (fetches monkeypatched) ---


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch, result: tuple[int, str, str] | Exception
):
    def fake(url: str, cache_dir: Path | None, timeout: int) -> tuple[int, str, str]:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(evidence, "_cached_fetch", fake)


def _patch_wayback(monkeypatch: pytest.MonkeyPatch, text: str | None):
    def fake(url: str, cache_dir: Path | None, timeout: int) -> str | None:
        return text

    monkeypatch.setattr(evidence, "_wayback_text", fake)


def check(url: str = "https://a.org/1", quote: str = "the words") -> CitationRecord:
    return evidence.check_citation(url, quote, cache_dir=None, timeout=5)


def test_no_quote_short_circuits(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, AssertionError("must not fetch"))
    assert check(quote="  ").status == "no_quote"


def test_verified_on_live_page(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (200, "text/html", "<p>the words</p>"))
    rec = check()
    assert rec.status == "verified"
    assert rec.archived is False
    assert rec.http_status == 200


def test_quote_missing_after_archive_miss(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (200, "text/html", "<p>changed content</p>"))
    _patch_wayback(monkeypatch, "<p>archive also lacks it</p>")
    assert check().status == "quote_missing"


def test_changed_page_rescued_by_archive(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (200, "text/html", "<p>changed content</p>"))
    _patch_wayback(monkeypatch, "<p>the words</p>")
    rec = check()
    assert rec.status == "verified"
    assert rec.archived is True


def test_non_text_content_is_unfetchable(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (200, "application/pdf", "%PDF-1.7 garbage"))
    assert check().status == "unfetchable"


def test_bot_block_is_unfetchable(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (403, "text/html", "denied"))
    assert check().status == "unfetchable"


def test_dead_link_without_archive(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (404, "text/html", "not found"))
    _patch_wayback(monkeypatch, None)
    assert check().status == "dead"


def test_dead_link_rescued_by_archive(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, (404, "text/html", "not found"))
    _patch_wayback(monkeypatch, "<p>the words</p>")
    rec = check()
    assert rec.status == "verified"
    assert rec.archived is True


def test_dead_link_with_archive_missing_quote_is_quote_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_fetch(monkeypatch, (404, "text/html", "not found"))
    _patch_wayback(monkeypatch, "<p>other content</p>")
    assert check().status == "quote_missing"


def test_network_failure_is_unfetchable(monkeypatch: pytest.MonkeyPatch):
    _patch_fetch(monkeypatch, requests.ConnectionError("boom"))
    assert check().status == "unfetchable"


# --- response cache ---


def test_cached_fetch_hits_disk_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake_page(url: str, *, timeout: int, headers: dict[str, str] | None = None):
        calls.append(url)
        return 200, "text/html", "<p>body</p>"

    monkeypatch.setattr(evidence, "_fetch_page", fake_page)
    first = evidence._cached_fetch("https://a.org/x", tmp_path, 5)
    second = evidence._cached_fetch("https://a.org/x", tmp_path, 5)
    assert first == second == (200, "text/html", "<p>body</p>")
    assert calls == ["https://a.org/x"]  # second hit served from disk


# --- apply_citations (scoring feedback) ---


def test_apply_citations_statuses():
    items = [
        item(quote="verified words", source_url="https://v.org/1"),
        item(quote="fabricated words", source_url="https://f.org/1"),
        item(quote="dead-link words", source_url="https://d.org/1", strength="strong"),
        item(quote="unchecked words", source_url="https://u.org/1", strength="weak"),
    ]
    records = [
        CitationRecord(source_url="https://v.org/1", quote="verified words", status="verified"),
        CitationRecord(source_url="https://f.org/1", quote="fabricated words", status="quote_missing"),
        CitationRecord(source_url="https://d.org/1", quote="dead-link words", status="dead"),
    ]
    kept, stats = evidence.apply_citations(items, records)
    assert stats == {"verified": 1, "excluded_quote_missing": 1, "downgraded": 2}
    by_url = {it.source_url: it for it in kept}
    assert "https://f.org/1" not in by_url  # fabricated-looking: inadmissible
    assert by_url["https://v.org/1"].strength == "strong"
    assert by_url["https://d.org/1"].strength == "moderate"  # one level down
    assert by_url["https://u.org/1"].strength == "weak"  # floor holds


def test_quote_missing_excludes_refuting_items_too():
    items = [item(bearing="refutes", quote="fake counter-quote")]
    records = [
        CitationRecord(
            source_url="https://a.org/1", quote="fake counter-quote", status="quote_missing"
        )
    ]
    kept, _ = evidence.apply_citations(items, records)
    assert kept == []


# --- CLI integration ---


def _run(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr("sys.argv", ["evidence", *argv])
    evidence.main()
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, dict)
    return out


def test_verify_citations_cli_writes_records_and_score_consumes_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    shard = tmp_path / "finder-1.jsonl"
    shard.write_text(
        item(quote="real words", source_url="https://ok.org/1").model_dump_json()
        + "\n"
        + item(quote="fake words", source_url="https://bad.org/1").model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    def fake_check(url: str, quote: str, *, cache_dir: Path | None, timeout: int):
        status = "verified" if url == "https://ok.org/1" else "quote_missing"
        return CitationRecord(source_url=url, quote=quote, status=status)

    monkeypatch.setattr(evidence, "check_citation", fake_check)
    out = _run(["verify-citations", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    result = out["result"]
    assert isinstance(result, dict)
    assert result["checked"] == 2
    assert result["counts"] == {"verified": 1, "quote_missing": 1}
    assert (tmp_path / "citations.jsonl").is_file()

    # score auto-detects citations.jsonl: the fabricated item no longer counts
    scored = _run(["score", "--run-dir", str(tmp_path)], capsys, monkeypatch)
    sresult = scored["result"]
    assert isinstance(sresult, dict)
    citations = sresult["citations"]
    assert isinstance(citations, dict)
    assert citations["excluded_quote_missing"] == 1
    claims = sresult["claims"]
    assert isinstance(claims, list)
    verdict = claims[0]
    assert isinstance(verdict, dict)
    assert verdict["n_sources"] == 1  # only the verified source scores
