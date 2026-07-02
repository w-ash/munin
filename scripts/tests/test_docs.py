"""Unit tests for the docs module: pure helpers, the batchUpdate request
builders, the REST wrapper boundary, and the dry-run contract. No network — the
token mint and HTTP layer are monkeypatched. Auth and error-code mapping are
tested in test_google."""

from __future__ import annotations

import pytest

from vault_scripts import _docs, docs
from vault_scripts._types import (
    DocsBatchUpdateReply,
    DocsBatchUpdateResponse,
    DocsBody,
    DocsNamedRange,
    DocsNamedRangeGroup,
    DocsParagraph,
    DocsParagraphElement,
    DocsRawDocument,
    DocsReplaceAllTextReply,
    DocsStructuralElement,
    DocsTextRun,
    DocumentModel,
    DriveFile,
    DriveFileList,
)

# --- parse_document_id ---


def test_parse_document_id_bare():
    assert docs.parse_document_id("1AbC-_dEf") == "1AbC-_dEf"


def test_parse_document_id_url():
    url = "https://docs.google.com/document/d/1AbC-_dEf/edit#heading=h.x"
    assert docs.parse_document_id(url) == "1AbC-_dEf"


def test_parse_document_id_multi_account_url():
    url = "https://docs.google.com/document/u/0/d/1AbC-_dEf/edit"
    assert docs.parse_document_id(url) == "1AbC-_dEf"


def test_parse_document_id_strips_whitespace():
    assert docs.parse_document_id("  1AbC-_dEf  ") == "1AbC-_dEf"


# --- envelope ---


def test_envelope_shape():
    env = docs.envelope("info", "doc1", {"title": "X"})
    assert env == {
        "ok": True,
        "cmd": "info",
        "documentId": "doc1",
        "result": {"title": "X"},
    }


# --- _parse_requests ---


def test_parse_requests_valid():
    assert docs._parse_requests('[{"insertText": {"text": "hi"}}]') == [
        {"insertText": {"text": "hi"}}
    ]


def test_parse_requests_empty_array_raises():
    with pytest.raises(docs.CliError):
        docs._parse_requests("[]")


def test_parse_requests_not_an_array_raises():
    with pytest.raises(docs.CliError):
        docs._parse_requests('{"insertText": {}}')


# --- batchUpdate request builders ---


def test_insert_text_request():
    assert _docs.insert_text_request(25, "Hi ") == {
        "insertText": {"location": {"index": 25}, "text": "Hi "}
    }


def test_append_text_request_uses_end_of_segment():
    # endOfSegmentLocation with an empty segment id targets the body end with no
    # index math — robust to shifts.
    assert _docs.append_text_request("More.") == {
        "insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": "More."}
    }


def test_delete_range_request():
    assert _docs.delete_range_request(25, 30) == {
        "deleteContentRange": {"range": {"startIndex": 25, "endIndex": 30}}
    }


def test_replace_all_text_request_match_case():
    assert _docs.replace_all_text_request("{{n}}", "Jordan", match_case=True) == {
        "replaceAllText": {
            "containsText": {"text": "{{n}}", "matchCase": True},
            "replaceText": "Jordan",
        }
    }


def test_style_text_request_only_passed_fields():
    # Only bold and link were set, so the fields mask names exactly those — italic
    # and underline are left untouched.
    assert _docs.style_text_request(1, 5, bold=True, link="https://x") == {
        "updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 5},
            "textStyle": {"bold": True, "link": {"url": "https://x"}},
            "fields": "bold,link",
        }
    }


def test_style_text_request_can_unset_bold():
    req = _docs.style_text_request(1, 5, bold=False)
    assert req["updateTextStyle"] == {
        "range": {"startIndex": 1, "endIndex": 5},
        "textStyle": {"bold": False},
        "fields": "bold",
    }


# --- body_end_index / text_index_map ---


def _doc_with_runs() -> DocumentModel:
    return DocumentModel(
        title="Spec",
        revisionId="rev1",
        body=DocsBody(
            content=[
                DocsStructuralElement(startIndex=0, endIndex=1),  # no paragraph
                DocsStructuralElement(
                    startIndex=1,
                    endIndex=12,
                    paragraph=DocsParagraph(
                        elements=[
                            DocsParagraphElement(
                                startIndex=1,
                                endIndex=12,
                                textRun=DocsTextRun(content="Hello world"),
                            )
                        ]
                    ),
                ),
            ]
        ),
    )


def test_body_end_index_uses_last_element():
    assert _docs.body_end_index(_doc_with_runs()) == 12


def test_body_end_index_empty_doc_is_one():
    assert _docs.body_end_index(DocumentModel()) == 1
    assert _docs.body_end_index(DocumentModel(body=DocsBody(content=[]))) == 1


def test_text_index_map_flattens_runs():
    assert _docs.text_index_map(_doc_with_runs()) == [
        {"start": 1, "end": 12, "text": "Hello world"}
    ]


def test_text_index_map_empty_body():
    assert _docs.text_index_map(DocumentModel()) == []


# --- REST wrapper boundary ---


def test_get_document_parses_response(monkeypatch):
    payload = '{"documentId": "d1", "title": "Spec", "revisionId": "r9"}'

    def fake_request(method, url, *, response_model, **_):
        assert method == "GET"
        assert url.endswith("/documents/d1")
        return response_model.model_validate_json(payload)

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    doc = _docs.get_document("d1")
    assert isinstance(doc, DocumentModel)
    assert doc.title == "Spec"
    assert doc.revisionId == "r9"


def test_export_markdown_builds_export_url(monkeypatch):
    monkeypatch.setattr(_docs, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_bytes(url, *, timeout, headers=None):
        seen["url"], seen["headers"] = url, headers
        return b"# Spec\n"

    monkeypatch.setattr(_docs, "request_image_bytes", fake_bytes)
    md = _docs.export_markdown("d1")
    assert md == "# Spec\n"
    assert "/files/d1/export?" in str(seen["url"])
    assert "mimeType=text%2Fmarkdown" in str(seen["url"])
    assert seen["headers"] == {"Authorization": "Bearer tok"}


def test_list_docs_builds_name_query(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, params=None, **_):
        seen["params"] = params
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.list_docs("Quarterly Spec")
    params = seen["params"]
    assert isinstance(params, dict)
    assert "mimeType='application/vnd.google-apps.document'" in params["q"]
    assert "name contains 'Quarterly Spec'" in params["q"]


def test_list_docs_escapes_query_quote(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, params=None, **_):
        seen["params"] = params
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.list_docs("O'Brien")
    params = seen["params"]
    assert isinstance(params, dict)
    assert "name contains 'O\\'Brien'" in params["q"]


def test_batch_update_includes_write_control_when_set(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["url"], seen["json"] = url, json
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.batch_update(
        "d1", [{"insertText": {"text": "x"}}], required_revision_id="rev7"
    )
    assert str(seen["url"]).endswith("/documents/d1:batchUpdate")
    assert seen["json"] == {
        "requests": [{"insertText": {"text": "x"}}],
        "writeControl": {"requiredRevisionId": "rev7"},
    }


def test_batch_update_omits_write_control_without_revision(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["json"] = json
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.batch_update("d1", [{"insertText": {"text": "x"}}])
    assert seen["json"] == {"requests": [{"insertText": {"text": "x"}}]}


# --- dry-run contract (command level) ---


def _args(command: str, **kw: object) -> docs._Args:
    args = docs._Args()
    args.command = command
    args.auth = "service"
    args.write = False
    args.revision_id = None
    for key, value in kw.items():
        setattr(args, key, value)
    return args


def _record_batch(monkeypatch) -> list[tuple[str, list[dict[str, object]], str | None]]:
    """Record every batch_update call; return an empty reply."""
    calls: list[tuple[str, list[dict[str, object]], str | None]] = []

    def fake_batch(doc_id, requests, *, required_revision_id=None, auth="service"):
        calls.append((doc_id, requests, required_revision_id))
        return DocsBatchUpdateResponse(documentId=doc_id)

    monkeypatch.setattr(_docs, "batch_update", fake_batch)
    return calls


def test_append_text_dry_run_makes_no_write(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    docs.cmd_append_text(_args("append-text", text="More.", write=False), "d1")
    assert calls == []
    out = capsys.readouterr().out
    assert '"dryRun": true' in out
    assert '"wouldAppend": "More."' in out


def test_append_text_write_calls_batch(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    docs.cmd_append_text(_args("append-text", text="More.", write=True), "d1")
    assert len(calls) == 1
    _doc, requests, _rev = calls[0]
    assert requests == [_docs.append_text_request("More.")]
    capsys.readouterr()


def test_insert_text_write_passes_revision(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    docs.cmd_insert_text(
        _args("insert-text", index=5, text="Hi", write=True, revision_id="r3"), "d1"
    )
    assert len(calls) == 1
    _doc, requests, rev = calls[0]
    assert requests == [_docs.insert_text_request(5, "Hi")]
    assert rev == "r3"
    capsys.readouterr()


def test_delete_range_rejects_inverted_range(monkeypatch):
    _record_batch(monkeypatch)
    with pytest.raises(docs.CliError):
        docs.cmd_delete_range(_args("delete-range", start=30, end=25, write=True), "d1")


def test_style_text_requires_a_style(monkeypatch):
    _record_batch(monkeypatch)
    args = _args(
        "style-text",
        start=1,
        end=5,
        bold=None,
        italic=None,
        underline=None,
        link=None,
        write=True,
    )
    with pytest.raises(docs.CliError):
        docs.cmd_style_text(args, "d1")


def test_style_text_write_builds_request(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    args = _args(
        "style-text",
        start=1,
        end=5,
        bold=True,
        italic=None,
        underline=None,
        link=None,
        write=True,
    )
    docs.cmd_style_text(args, "d1")
    assert len(calls) == 1
    _doc, requests, _rev = calls[0]
    assert requests == [_docs.style_text_request(1, 5, bold=True)]
    capsys.readouterr()


def test_replace_all_dry_run_no_write(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    docs.cmd_replace_all(
        _args(
            "replace-all", find="{{n}}", replace="Jordan", match_case=False, write=False
        ),
        "d1",
    )
    assert calls == []
    out = capsys.readouterr().out
    assert '"dryRun": true' in out
    assert '"find": "{{n}}"' in out


def test_replace_all_write_reports_count(monkeypatch, capsys):
    def fake_batch(doc_id, requests, *, required_revision_id=None, auth="service"):
        return DocsBatchUpdateResponse(
            documentId=doc_id,
            replies=[
                DocsBatchUpdateReply(
                    replaceAllText=DocsReplaceAllTextReply(occurrencesChanged=3)
                )
            ],
        )

    monkeypatch.setattr(_docs, "batch_update", fake_batch)
    docs.cmd_replace_all(
        _args("replace-all", find="{{n}}", replace="Jordan", match_case=False, write=True),
        "d1",
    )
    assert '"occurrencesChanged": 3' in capsys.readouterr().out


def test_batch_dry_run_lists_requests(monkeypatch, capsys):
    calls = _record_batch(monkeypatch)
    docs.cmd_batch(
        _args("batch", requests='[{"insertText": {"text": "x"}}]', write=False), "d1"
    )
    assert calls == []
    out = capsys.readouterr().out
    assert '"dryRun": true' in out
    assert '"requestCount": 1' in out


# --- read commands ---


def test_cmd_get_raw_json_dumps_document(monkeypatch, capsys):
    monkeypatch.setattr(
        _docs,
        "get_document_raw",
        lambda _doc_id, **_k: DocsRawDocument({"documentId": "d1", "title": "Spec"}),
    )
    docs.cmd_get(_args("get", raw_json=True), "d1")
    out = capsys.readouterr().out
    assert '"document"' in out
    assert '"title": "Spec"' in out


def test_cmd_get_index_map(monkeypatch, capsys):
    monkeypatch.setattr(_docs, "get_document", lambda _doc_id, **_k: _doc_with_runs())
    docs.cmd_get(_args("get", raw_json=False), "d1")
    out = capsys.readouterr().out
    assert '"runCount": 1' in out
    assert '"Hello world"' in out
    assert '"endIndex": 12' in out


def test_cmd_info_reports_metadata(monkeypatch, capsys):
    monkeypatch.setattr(_docs, "get_document", lambda _doc_id, **_k: _doc_with_runs())
    docs.cmd_info(_args("info"), "d1")
    out = capsys.readouterr().out
    assert '"title": "Spec"' in out
    assert '"revisionId": "rev1"' in out


def test_cmd_list_named_ranges_flattens(monkeypatch, capsys):
    doc = DocumentModel(
        namedRanges={
            "anchor": DocsNamedRangeGroup(
                name="anchor",
                namedRanges=[DocsNamedRange(namedRangeId="nr1", name="anchor")],
            )
        }
    )
    monkeypatch.setattr(_docs, "get_document", lambda _doc_id, **_k: doc)
    docs.cmd_list_named_ranges(_args("list-named-ranges"), "d1")
    out = capsys.readouterr().out
    assert '"count": 1' in out
    assert '"namedRangeId": "nr1"' in out


def test_cmd_find_paginates(monkeypatch, capsys):
    pages = [
        DriveFileList(files=[DriveFile(id="a", name="Spec A")], nextPageToken="tok2"),
        DriveFileList(files=[DriveFile(id="b", name="Spec B")], nextPageToken=""),
    ]

    def fake_list(_query, *, page_token=None, auth="service"):
        return pages[1] if page_token == "tok2" else pages[0]

    monkeypatch.setattr(_docs, "list_docs", fake_list)
    docs.cmd_find(_args("find", query="Spec"), "")
    out = capsys.readouterr().out
    # Both pages are collected — the second page is reached via nextPageToken.
    assert '"count": 2' in out
    assert '"id": "a"' in out
    assert '"id": "b"' in out


def test_cmd_export_writes_out_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(_docs, "export_markdown", lambda _doc_id, **_k: "# Spec\n")
    out_file = tmp_path / "spec.md"
    docs.cmd_export(_args("export", out=str(out_file)), "d1")
    assert out_file.read_text(encoding="utf-8") == "# Spec\n"
    assert str(out_file) in capsys.readouterr().out


def test_cmd_export_stdout_when_no_out(monkeypatch, capsys):
    monkeypatch.setattr(_docs, "export_markdown", lambda _doc_id, **_k: "# Spec\n")
    docs.cmd_export(_args("export", out=None), "d1")
    out = capsys.readouterr().out
    assert '"markdown": "# Spec\\n"' in out
    assert '"length": 7' in out


# --- creation wrappers ---


def test_create_document_request_shape(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["method"], seen["url"], seen["json"] = method, url, json
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.create_document("New Spec")
    assert seen["method"] == "POST"
    assert str(seen["url"]).endswith("/documents")
    assert seen["json"] == {"title": "New Spec"}


def test_copy_file_request_shape(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["url"], seen["json"] = url, json
        return response_model()

    monkeypatch.setattr(_docs, "authed_request", fake_request)
    _ = _docs.copy_file("tmpl1", "Filled")
    assert str(seen["url"]).endswith("/files/tmpl1/copy")
    assert seen["json"] == {"name": "Filled"}


def test_multipart_boundary_absent_from_media():
    media = b"# Heading\n\nsome body text"
    boundary = _docs._multipart_boundary(media)
    assert boundary.startswith("munin")
    assert f"--{boundary}".encode() not in media


def test_multipart_related_body_has_both_parts():
    body = _docs._multipart_related_body(
        {"name": "Spec", "mimeType": "application/vnd.google-apps.document"},
        b"# Hi",
        "text/markdown",
        "BOUND",
    )
    assert b"--BOUND\r\n" in body
    assert b"application/json" in body
    assert b'"name": "Spec"' in body
    assert b"Content-Type: text/markdown" in body
    assert b"# Hi" in body
    assert body.endswith(b"--BOUND--\r\n")


def test_import_markdown_uploads_multipart(monkeypatch):
    monkeypatch.setattr(_docs, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, data=None, headers=None, **_):
        seen["url"], seen["data"], seen["headers"] = url, data, headers
        return DriveFile(id="newdoc", name="Spec")

    monkeypatch.setattr(_docs, "request_validated_json", fake_request)
    created = _docs.import_markdown("Spec", b"# Hi")
    assert created.id == "newdoc"
    assert "uploadType=multipart" in str(seen["url"])
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"].startswith("multipart/related; boundary=")
    assert isinstance(seen["data"], bytes)


# --- _parse_replacements / _resolve_note ---


def test_parse_replacements_valid():
    assert docs._parse_replacements(["{{n}}=Jordan", "{{c}}=City"]) == {
        "{{n}}": "Jordan",
        "{{c}}": "City",
    }


def test_parse_replacements_requires_equals():
    with pytest.raises(docs.CliError):
        docs._parse_replacements(["noequals"])


def test_resolve_note_missing_raises():
    with pytest.raises(docs.CliError):
        docs._resolve_note("nonexistent/path/xyz-not-real.md")


# --- create / template commands ---


def test_cmd_create_requires_oauth():
    with pytest.raises(docs.CliError):
        docs.cmd_create(
            _args("create", auth="service", from_file="x.md", write=True), ""
        )


def test_cmd_create_write_imports(monkeypatch, capsys, tmp_path):
    src = tmp_path / "spec.md"
    _ = src.write_text("# Spec\n", encoding="utf-8")
    monkeypatch.setattr(
        _docs, "import_markdown", lambda *_a, **_k: DriveFile(id="newdoc", name="spec")
    )
    args = _args("create", auth="oauth", from_file=str(src), title=None, write=True)
    docs.cmd_create(args, "")
    out = capsys.readouterr().out
    assert '"documentId": "newdoc"' in out
    assert "newdoc/edit" in out


def test_cmd_create_dry_run(monkeypatch, capsys, tmp_path):
    src = tmp_path / "spec.md"
    _ = src.write_text("# Spec\n", encoding="utf-8")
    calls: list[int] = []
    monkeypatch.setattr(_docs, "import_markdown", lambda *_a, **_k: calls.append(1))
    args = _args(
        "create", auth="oauth", from_file=str(src), title="My Spec", write=False
    )
    docs.cmd_create(args, "")
    out = capsys.readouterr().out
    assert calls == []
    assert '"dryRun": true' in out
    assert '"wouldCreate": "My Spec"' in out


def test_cmd_template_requires_oauth():
    with pytest.raises(docs.CliError):
        docs.cmd_template(
            _args(
                "template",
                auth="service",
                template_id="t",
                replacements=None,
                write=True,
            ),
            "",
        )


def test_cmd_template_write_copies_and_replaces(monkeypatch, capsys):
    monkeypatch.setattr(
        _docs, "copy_file", lambda *_a, **_k: DriveFile(id="copy1", name="Filled")
    )
    batch_calls: list[tuple[str, list[dict[str, object]]]] = []

    def fake_batch(doc_id, requests, *, required_revision_id=None, auth="service"):
        batch_calls.append((doc_id, requests))
        return DocsBatchUpdateResponse(documentId=doc_id)

    monkeypatch.setattr(_docs, "batch_update", fake_batch)
    args = _args(
        "template",
        auth="oauth",
        template_id="tmpl",
        title="Filled",
        replacements=["{{n}}=Jordan"],
        write=True,
    )
    docs.cmd_template(args, "")
    out = capsys.readouterr().out
    assert '"documentId": "copy1"' in out
    assert '"replaced": 1' in out
    assert len(batch_calls) == 1
    _doc, requests = batch_calls[0]
    assert requests == [_docs.replace_all_text_request("{{n}}", "Jordan")]
