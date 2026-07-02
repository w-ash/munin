"""REST wrappers for the Google Docs and Drive APIs.

Auth and the shared transport live in :mod:`vault_scripts._google`. This module
binds that helper to the Docs + Drive scopes and exposes one function per
operation, plus pure builders for the ``batchUpdate`` request objects.

A Google Doc is a tree of structural elements addressed by UTF-16 index, not a
grid. The read path leans on Drive's native Markdown export (one call, no index
math); in-place edits go through ``documents.batchUpdate``. Owned-file creation
(import, copy) needs OAuth-user auth; see :mod:`vault_scripts._google`.

Share each target doc with the service account's ``client_email`` (Editor to
write, Viewer to read), or service-account calls come back 403.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlencode

from pydantic import BaseModel

from vault_scripts._google import authed_request, current_auth, get_access_token
from vault_scripts._retry import (
    google_retry,
    request_image_bytes,
    request_validated_json,
)
from vault_scripts._types import (
    DocsBatchUpdateResponse,
    DocsRawDocument,
    DocumentModel,
    DriveFile,
    DriveFileList,
)

DOCS_BASE = "https://docs.googleapis.com/v1/documents"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_DRIVE_SCOPES: tuple[str, ...] = (DOCS_SCOPE, DRIVE_SCOPE)
# Docs may set its own SA env; fall back to the Sheets key (often the same file).
DOCS_SA_ENV: tuple[str, ...] = ("GOOGLE_DOCS_SA_JSON", "GOOGLE_SHEETS_SA_JSON")
DOC_MIMETYPE = "application/vnd.google-apps.document"
MARKDOWN_MIMETYPE = "text/markdown"
# Exports can be larger and slower than a JSON call (Drive caps export at 10 MB).
EXPORT_TIMEOUT_S = 60


def _docs_request[M: BaseModel](
    method: str,
    url: str,
    *,
    response_model: type[M],
    params: dict[str, str] | None = None,
    json: object | None = None,
    idempotent: bool = True,
) -> M:
    """Issue an authenticated Docs/Drive JSON call. Binds the shared transport to
    the Docs + Drive scopes, the Docs SA env lookup order, and the invocation's
    auth mode (:func:`current_auth`, matching the Sheets adapter). Pass
    ``idempotent=False`` for document batchUpdate and resource create/copy so a
    retried transport error can't apply the edit or create the file twice."""
    return authed_request(
        method,
        url,
        response_model=response_model,
        scopes=DOCS_DRIVE_SCOPES,
        auth=current_auth(),
        sa_env=DOCS_SA_ENV,
        params=params,
        json=json,
        idempotent=idempotent,
    )


# --- Read ---


def get_document(document_id: str) -> DocumentModel:
    """Read a document (``documents.get``). includeTabsContent is left unset so the
    legacy ``body`` is populated: the index space append/insert/delete address."""
    return _docs_request(
        "GET", f"{DOCS_BASE}/{document_id}", response_model=DocumentModel
    )


def get_document_raw(document_id: str) -> DocsRawDocument:
    """Read the full untyped ``documents.get`` response (the raw-json escape hatch)."""
    return _docs_request(
        "GET", f"{DOCS_BASE}/{document_id}", response_model=DocsRawDocument
    )


@google_retry
def _export_bytes(url: str, token: str) -> bytes:
    """GET the export payload with a Bearer header; retries transient 429/5xx."""
    return request_image_bytes(
        url, timeout=EXPORT_TIMEOUT_S, headers={"Authorization": f"Bearer {token}"}
    )


def export_markdown(document_id: str) -> str:
    """Export a doc to Markdown via Drive ``files.export``. One call, no index math,
    far more token-efficient than ``documents.get``. Drive caps export at 10 MB
    (a 403 ``exportSizeLimitExceeded`` above it)."""
    token = get_access_token(DOCS_DRIVE_SCOPES, auth=current_auth(), sa_env=DOCS_SA_ENV)
    url = f"{DRIVE_BASE}/files/{document_id}/export?{urlencode({'mimeType': MARKDOWN_MIMETYPE})}"
    return _export_bytes(url, token).decode("utf-8")


def _escape_query_literal(value: str) -> str:
    """Escape a Drive query string literal (backslash, then single quote)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def list_docs(
    query: str | None,
    *,
    page_token: str | None = None,
) -> DriveFileList:
    """One page of Google Docs from Drive ``files.list`` (the Docs API can't list).
    ``query`` filters by name substring; the caller loops ``nextPageToken``."""
    q = f"mimeType='{DOC_MIMETYPE}' and trashed=false"
    if query:
        q += f" and name contains '{_escape_query_literal(query)}'"
    params: dict[str, str] = {
        "q": q,
        "fields": "files(id,name,mimeType),nextPageToken",
        "pageSize": "100",
        "orderBy": "modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token
    return _docs_request(
        "GET",
        f"{DRIVE_BASE}/files",
        response_model=DriveFileList,
        params=params,
    )


def body_end_index(doc: DocumentModel) -> int:
    """The body's end index (exclusive), one past the last insertable position;
    an empty doc starts at 1.

    Not itself a valid insert index: the Docs API rejects an ``insertText`` at
    ``endIndex`` ("the index must be less than the end index of the referenced
    segment"). To add to the end use the append path (``append_text_request`` /
    ``endOfSegmentLocation``); to insert near the end use ``endIndex - 1``.
    """
    if doc.body is None or not doc.body.content:
        return 1
    return doc.body.content[-1].endIndex


def text_index_map(doc: DocumentModel) -> list[dict[str, object]]:
    """Flatten the body to ``{start, end, text}`` per text run: a practical index
    map for deciding where to insert, delete, or style."""
    if doc.body is None:
        return []
    return [
        {"start": pe.startIndex, "end": pe.endIndex, "text": pe.textRun.content}
        for element in doc.body.content
        if element.paragraph is not None
        for pe in element.paragraph.elements
        if pe.textRun is not None
    ]


# --- In-place write ---


def batch_update(
    document_id: str,
    requests: list[dict[str, object]],
    *,
    required_revision_id: str | None = None,
) -> DocsBatchUpdateResponse:
    """Apply an ordered list of requests atomically (``documents.batchUpdate``).

    When ``required_revision_id`` is set, the write is rejected (400
    INVALID_ARGUMENT) if the doc changed since that revision, so index-based
    edits computed from a ``get`` can't land on shifted content.
    """
    body: dict[str, object] = {"requests": requests}
    if required_revision_id:
        body["writeControl"] = {"requiredRevisionId": required_revision_id}
    return _docs_request(
        "POST",
        f"{DOCS_BASE}/{document_id}:batchUpdate",
        response_model=DocsBatchUpdateResponse,
        json=body,
        idempotent=False,
    )


# --- batchUpdate request builders (pure; unit-tested) ---


def insert_text_request(index: int, text: str) -> dict[str, object]:
    """Insert ``text`` at a specific index in the body."""
    return {"insertText": {"location": {"index": index}, "text": text}}


def append_text_request(text: str) -> dict[str, object]:
    """Append ``text`` to the end of the body. ``endOfSegmentLocation`` with an
    empty segment id targets the body end with no index math, robust to shifts."""
    return {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": text}}


def delete_range_request(start: int, end: int) -> dict[str, object]:
    """Delete everything in ``[start, end)`` (``DeleteContentRange``)."""
    return {"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}


def replace_all_text_request(
    find: str, replace: str, *, match_case: bool = False
) -> dict[str, object]:
    """Replace every occurrence of ``find`` with ``replace`` (the templating
    primitive; no indexes involved)."""
    return {
        "replaceAllText": {
            "containsText": {"text": find, "matchCase": match_case},
            "replaceText": replace,
        }
    }


def style_text_request(
    start: int,
    end: int,
    *,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    link: str | None = None,
) -> dict[str, object]:
    """Set character styling over ``[start, end)`` (``UpdateTextStyle``). Only the
    passed attributes are written; the ``fields`` mask names exactly those."""
    text_style: dict[str, object] = {}
    fields: list[str] = []
    if bold is not None:
        text_style["bold"] = bold
        fields.append("bold")
    if italic is not None:
        text_style["italic"] = italic
        fields.append("italic")
    if underline is not None:
        text_style["underline"] = underline
        fields.append("underline")
    if link is not None:
        text_style["link"] = {"url": link}
        fields.append("link")
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": text_style,
            "fields": ",".join(fields),
        }
    }


# --- Owned-file creation (needs OAuth-user auth; the service account can't own files) ---


def create_document(title: str) -> DocumentModel:
    """Create an empty document (``documents.create``); body content is added via
    batch_update afterward. Needs an identity that can own files (OAuth user)."""
    return _docs_request(
        "POST",
        DOCS_BASE,
        response_model=DocumentModel,
        json={"title": title},
        idempotent=False,
    )


def copy_file(file_id: str, name: str) -> DriveFile:
    """Copy a Drive file (``files.copy``): the template primitive. Needs OAuth user."""
    return _docs_request(
        "POST",
        f"{DRIVE_BASE}/files/{file_id}/copy",
        response_model=DriveFile,
        json={"name": name},
        idempotent=False,
    )


def _multipart_boundary(media: bytes) -> str:
    """A boundary derived from the media digest, guaranteed not to occur in it."""
    boundary = "munin" + hashlib.sha256(media).hexdigest()[:24]
    while f"--{boundary}".encode() in media:
        boundary = "x" + boundary
    return boundary


def _multipart_related_body(
    metadata: dict[str, object], media: bytes, media_mime: str, boundary: str
) -> bytes:
    """Build a Drive ``multipart/related`` upload body: a JSON metadata part then
    the media part."""
    meta_part = json.dumps(metadata).encode("utf-8")
    return b"".join([
        f"--{boundary}\r\n".encode(),
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
        meta_part,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f"Content-Type: {media_mime}\r\n\r\n".encode(),
        media,
        f"\r\n--{boundary}--\r\n".encode(),
    ])


def _upload_multipart(
    metadata: dict[str, object], media: bytes, media_mime: str, token: str
) -> DriveFile:
    """POST a ``multipart/related`` upload to Drive and validate the file reply.

    Not retried: this creates a new owned file, so a timeout/reset after Drive
    accepted the upload must not be retried into a duplicate Doc.
    """
    boundary = _multipart_boundary(media)
    body = _multipart_related_body(metadata, media, media_mime, boundary)
    return request_validated_json(
        "POST",
        f"{DRIVE_UPLOAD_BASE}?uploadType=multipart",
        response_model=DriveFile,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        timeout=EXPORT_TIMEOUT_S,
    )


def import_markdown(
    name: str,
    md_bytes: bytes,
    *,
    folder: str | None = None,
) -> DriveFile:
    """Create a Google Doc from Markdown via Drive's native importer (upload the
    ``.md`` with a Docs target mimeType). Creates an owned file; needs OAuth user.
    Drive's importer brings images through as base64; rewrite those separately."""
    token = get_access_token(DOCS_DRIVE_SCOPES, auth=current_auth(), sa_env=DOCS_SA_ENV)
    metadata: dict[str, object] = {"name": name, "mimeType": DOC_MIMETYPE}
    if folder:
        metadata["parents"] = [folder]
    return _upload_multipart(metadata, md_bytes, MARKDOWN_MIMETYPE, token)
