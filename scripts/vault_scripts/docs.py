"""Read and write Google Docs over the Docs and Drive REST APIs.

Reads run as-is; mutating commands default to a dry-run and need ``--write`` to
apply (same convention as ``sheets``). Every command prints a JSON envelope
``{ok, cmd, documentId, result}`` to stdout; errors print ``{ok: false, ...,
error}`` and exit with a code (2 validation, 3 auth, 4 permission, 5 API).

Auth runs through the shared seam in ``_google``. ``--auth oauth`` (the default)
acts as the user: reads, in-place edits, and owned-file creation, after a one-time
``docs auth-login``. ``--auth service`` acts as the service account: reads and
in-place edits of docs explicitly shared with it.

Usage:
    scripts/vault-tool docs export <id|url>
    scripts/vault-tool docs export <id> --out "Work/Notes/spec.md"
    scripts/vault-tool docs get <id> --raw-json
    scripts/vault-tool docs info <id>
    scripts/vault-tool docs find --query "Spec"
    scripts/vault-tool docs list-named-ranges <id>
    scripts/vault-tool docs append-text <id> --text "More." --write
    scripts/vault-tool docs insert-text <id> --index 25 --text "Hi " --write
    scripts/vault-tool docs delete-range <id> --start 25 --end 30 --write
    scripts/vault-tool docs style-text <id> --start 1 --end 10 --bold --write
    scripts/vault-tool docs replace-all <id> --find "{{name}}" --replace "Jordan" --write
    scripts/vault-tool docs batch <id> --requests '[{"insertText": {...}}]' --write

The document argument accepts a bare ID or a full Docs URL. Index-based commands
(insert-text, delete-range, style-text, batch) take an optional --revision-id
(from get/info); the write is rejected if the doc changed since that revision.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from itertools import starmap
from pathlib import Path

from pydantic import ValidationError

from vault_scripts import _cli, _docs
from vault_scripts._cli import (
    CliError,
    parse_drive_id as parse_document_id,
    print_json as _print,
    require_flag as _require,
)
from vault_scripts._google import AuthMode
from vault_scripts._types import BatchRequests, DocsBatchUpdateResponse
from vault_scripts._utils import VAULT, find_vault_file, parse_typed_args

# A Google Docs URL, used to build the result link for newly created docs.
_DOC_URL = "https://docs.google.com/document/d/{}/edit"

# The id key this CLI stamps into every JSON envelope.
_ID_KEY = "documentId"


# --- Pure helpers (no network; unit-tested) ---


# The success envelope and dry-run-or-apply tail, with this CLI's id key bound.
envelope = _cli.make_envelope(_ID_KEY)
_emit_write = _cli.make_emit_write(_ID_KEY)


def _parse_requests(raw: str) -> list[dict[str, object]]:
    try:
        reqs = BatchRequests.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(
            f"--requests must be a JSON array of request objects: {e}"
        ) from e
    if not reqs.root:
        raise CliError("--requests must contain at least one request")
    return reqs.root


def _resolve_note(path_arg: str) -> Path:
    """Resolve a --from note path: vault-relative first, then as given."""
    path = find_vault_file(path_arg)
    if path is None:
        raise CliError(f"file not found: {path_arg}")
    return path


def _parse_replacements(items: list[str]) -> dict[str, str]:
    """Parse ``key=value`` --replace args into a find -> replace map. The key is
    the literal text to find (include any ``{{ }}`` braces yourself)."""
    out: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise CliError(f"--replace must be key=value, got {item!r}")
        out[key] = value
    return out


# --- Commands ---


class _Args(argparse.Namespace):
    command: str
    document: str
    out: str | None
    raw_json: bool
    query: str | None
    text: str | None
    index: int | None
    start: int | None
    end: int | None
    find: str | None
    replace: str | None
    match_case: bool
    bold: bool | None
    italic: bool | None
    underline: bool | None
    link: str | None
    requests: str | None
    from_file: str | None
    template_id: str | None
    title: str | None
    replacements: list[str] | None
    write: bool
    revision_id: str | None
    auth: AuthMode


def cmd_export(args: _Args, doc_id: str) -> None:
    md = _docs.export_markdown(doc_id)
    result: dict[str, object] = {"length": len(md)}
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = VAULT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _ = out_path.write_text(md, encoding="utf-8")
        result["out"] = str(out_path)
    else:
        result["markdown"] = md
    _print(envelope("export", doc_id, result))


def cmd_get(args: _Args, doc_id: str) -> None:
    if args.raw_json:
        raw = _docs.get_document_raw(doc_id)
        _print(envelope("get", doc_id, {"document": raw.root}))
        return
    doc = _docs.get_document(doc_id)
    runs = _docs.text_index_map(doc)
    _print(
        envelope(
            "get",
            doc_id,
            {
                "title": doc.title,
                "revisionId": doc.revisionId,
                "endIndex": _docs.body_end_index(doc),
                "runCount": len(runs),
                "runs": runs,
            },
        )
    )


def cmd_info(_args: _Args, doc_id: str) -> None:
    doc = _docs.get_document(doc_id)
    _print(
        envelope(
            "info",
            doc_id,
            {
                "title": doc.title,
                "revisionId": doc.revisionId,
                "endIndex": _docs.body_end_index(doc),
                "namedRangeCount": len(doc.namedRanges),
            },
        )
    )


def cmd_find(args: _Args, _doc_id: str) -> None:
    documents: list[dict[str, str]] = []
    page_token: str | None = None
    while True:
        resp = _docs.list_docs(args.query, page_token=page_token)
        documents.extend({"id": f.id, "name": f.name} for f in resp.files)
        page_token = resp.nextPageToken or None
        if page_token is None:
            break
    _print(
        envelope(
            "find",
            "",
            {
                "query": args.query or "",
                "count": len(documents),
                "documents": documents,
            },
        )
    )


def cmd_list_named_ranges(_args: _Args, doc_id: str) -> None:
    doc = _docs.get_document(doc_id)
    ranges = [
        {"name": group.name or name, "namedRangeId": nr.namedRangeId}
        for name, group in doc.namedRanges.items()
        for nr in group.namedRanges
    ]
    _print(
        envelope(
            "list-named-ranges", doc_id, {"count": len(ranges), "namedRanges": ranges}
        )
    )


def _batch(
    doc_id: str, request: dict[str, object], args: _Args
) -> DocsBatchUpdateResponse:
    return _docs.batch_update(
        doc_id, [request], required_revision_id=args.revision_id
    )


def cmd_append_text(args: _Args, doc_id: str) -> None:
    text = _require(args.text, "--text")

    def apply() -> dict[str, object]:
        _ = _batch(doc_id, _docs.append_text_request(text), args)
        return {"appended": text}

    _emit_write(
        "append-text", doc_id, write=args.write, dry={"wouldAppend": text}, apply=apply
    )


def cmd_insert_text(args: _Args, doc_id: str) -> None:
    index = _require(args.index, "--index")
    text = _require(args.text, "--text")

    def apply() -> dict[str, object]:
        _ = _batch(doc_id, _docs.insert_text_request(index, text), args)
        return {"index": index, "inserted": text}

    _emit_write(
        "insert-text",
        doc_id,
        write=args.write,
        dry={"index": index, "wouldInsert": text},
        apply=apply,
    )


def cmd_delete_range(args: _Args, doc_id: str) -> None:
    start = _require(args.start, "--start")
    end = _require(args.end, "--end")
    if end <= start:
        raise CliError(f"--end ({end}) must be greater than --start ({start})")

    def apply() -> dict[str, object]:
        _ = _batch(doc_id, _docs.delete_range_request(start, end), args)
        return {"deleted": {"start": start, "end": end}}

    _emit_write(
        "delete-range",
        doc_id,
        write=args.write,
        dry={"wouldDelete": {"start": start, "end": end}},
        apply=apply,
    )


def cmd_style_text(args: _Args, doc_id: str) -> None:
    start = _require(args.start, "--start")
    end = _require(args.end, "--end")
    if end <= start:
        raise CliError(f"--end ({end}) must be greater than --start ({start})")
    if (
        args.bold is None
        and args.italic is None
        and args.underline is None
        and args.link is None
    ):
        raise CliError(
            "pass at least one style: --bold/--italic/--underline (or --no-*) or --link"
        )
    request = _docs.style_text_request(
        start,
        end,
        bold=args.bold,
        italic=args.italic,
        underline=args.underline,
        link=args.link,
    )

    def apply() -> dict[str, object]:
        _ = _batch(doc_id, request, args)
        return {"styled": {"start": start, "end": end}}

    _emit_write(
        "style-text",
        doc_id,
        write=args.write,
        dry={"range": {"start": start, "end": end}, "wouldApply": request},
        apply=apply,
    )


def cmd_replace_all(args: _Args, doc_id: str) -> None:
    find = _require(args.find, "--find")
    replace = _require(args.replace, "--replace")
    request = _docs.replace_all_text_request(find, replace, match_case=args.match_case)

    def apply() -> dict[str, object]:
        resp = _batch(doc_id, request, args)
        reply = resp.replies[0].replaceAllText if resp.replies else None
        return {"occurrencesChanged": reply.occurrencesChanged if reply else 0}

    _emit_write(
        "replace-all",
        doc_id,
        write=args.write,
        dry={"wouldReplace": {"find": find, "replace": replace}},
        apply=apply,
    )


def cmd_batch(args: _Args, doc_id: str) -> None:
    requests = _parse_requests(_require(args.requests, "--requests"))

    def apply() -> dict[str, object]:
        resp = _docs.batch_update(
            doc_id, requests, required_revision_id=args.revision_id
        )
        return {"requestCount": len(requests), "replyCount": len(resp.replies)}

    _emit_write(
        "batch",
        doc_id,
        write=args.write,
        dry={"requestCount": len(requests), "requests": requests},
        apply=apply,
    )


def _require_oauth(args: _Args, command: str) -> None:
    """Owned-file creation needs an identity that can own files; the service
    account can't. Fail fast with a clear message instead of a doomed 403."""
    if args.auth != "oauth":
        raise CliError(
            f"{command} needs --auth oauth (the service account can't own files; "
            "run `docs auth-login` once first)"
        )


def cmd_create(args: _Args, _doc_id: str) -> None:
    _require_oauth(args, "create")
    src = _resolve_note(_require(args.from_file, "--from"))
    md_bytes = src.read_bytes()
    title = args.title or src.stem

    def apply() -> dict[str, object]:
        created = _docs.import_markdown(title, md_bytes)
        return {
            "documentId": created.id,
            "title": created.name,
            "url": _DOC_URL.format(created.id),
        }

    _emit_write(
        "create",
        "",
        write=args.write,
        dry={"wouldCreate": title, "from": str(src)},
        apply=apply,
    )


def cmd_template(args: _Args, _doc_id: str) -> None:
    _require_oauth(args, "template")
    template_id = parse_document_id(_require(args.template_id, "--template-id"))
    replacements = _parse_replacements(args.replacements or [])
    title = args.title or "Copy"

    def apply() -> dict[str, object]:
        copy = _docs.copy_file(template_id, title)
        requests = list(starmap(_docs.replace_all_text_request, replacements.items()))
        if requests:
            _ = _docs.batch_update(copy.id, requests)
        return {
            "documentId": copy.id,
            "title": copy.name,
            "replaced": len(replacements),
            "url": _DOC_URL.format(copy.id),
        }

    _emit_write(
        "template",
        "",
        write=args.write,
        dry={"wouldCopy": template_id, "to": title, "replacements": replacements},
        apply=apply,
    )


def cmd_auth_login(_args: _Args, _doc_id: str) -> None:
    _print(envelope("auth-login", "", _cli.auth_login()))


# --- CLI plumbing ---


# Subcommand dispatch. argparse declares the same names with required=True, so
# an unknown command never reaches the lookup.
_COMMANDS: dict[str, Callable[[_Args, str], None]] = {
    "export": cmd_export,
    "get": cmd_get,
    "info": cmd_info,
    "find": cmd_find,
    "list-named-ranges": cmd_list_named_ranges,
    "append-text": cmd_append_text,
    "insert-text": cmd_insert_text,
    "delete-range": cmd_delete_range,
    "style-text": cmd_style_text,
    "replace-all": cmd_replace_all,
    "batch": cmd_batch,
    "create": cmd_create,
    "template": cmd_template,
    "auth-login": cmd_auth_login,
}


def _run(args: _Args, doc_id: str) -> None:
    _COMMANDS[args.command](args, doc_id)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and write Google Docs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --auth applies to every command (oauth user by default; --auth service for
    # the sandboxed service account). Shared with the sheets CLI via _cli.
    auth_opts = _cli.auth_parent()

    # The document positional, for every command except find.
    doc_opts = argparse.ArgumentParser(add_help=False)
    _ = doc_opts.add_argument("document", help="Document ID or full Docs URL")

    # The --write gate plus optional --revision-id, for mutations.
    write_opts = argparse.ArgumentParser(add_help=False)
    _ = write_opts.add_argument(
        "--write", action="store_true", help="Apply changes (default is dry-run)"
    )
    _ = write_opts.add_argument(
        "--revision-id",
        default=None,
        help="Require this revisionId (from get/info); the write fails if the doc changed",
    )

    ex = subparsers.add_parser(
        "export", parents=[doc_opts, auth_opts], help="Export the doc as Markdown"
    )
    _ = ex.add_argument(
        "--out",
        help="Write the Markdown to this (vault-relative) path instead of stdout",
    )

    ge = subparsers.add_parser(
        "get",
        parents=[doc_opts, auth_opts],
        help="Read the body as a text/index map (or the raw API JSON)",
    )
    _ = ge.add_argument(
        "--raw-json",
        action="store_true",
        help="Print the full documents.get response instead of the index map",
    )

    _ = subparsers.add_parser(
        "info", parents=[doc_opts, auth_opts], help="Title, revisionId, end index"
    )

    fi = subparsers.add_parser(
        "find", parents=[auth_opts], help="Find Google Docs in Drive by name"
    )
    _ = fi.add_argument("--query", help="Name substring to match (omit for all docs)")

    _ = subparsers.add_parser(
        "list-named-ranges",
        parents=[doc_opts, auth_opts],
        help="List the named ranges in a doc",
    )

    at = subparsers.add_parser(
        "append-text",
        parents=[doc_opts, write_opts, auth_opts],
        help="Append text to the end of the body",
    )
    _ = at.add_argument("--text", required=True, help="Text to append")

    it = subparsers.add_parser(
        "insert-text",
        parents=[doc_opts, write_opts, auth_opts],
        help="Insert text at an index",
    )
    _ = it.add_argument(
        "--index", type=int, required=True, help="UTF-16 index to insert at"
    )
    _ = it.add_argument("--text", required=True, help="Text to insert")

    dr = subparsers.add_parser(
        "delete-range",
        parents=[doc_opts, write_opts, auth_opts],
        help="Delete the content in [start, end)",
    )
    _ = dr.add_argument(
        "--start", type=int, required=True, help="Start index (inclusive)"
    )
    _ = dr.add_argument("--end", type=int, required=True, help="End index (exclusive)")

    st = subparsers.add_parser(
        "style-text",
        parents=[doc_opts, write_opts, auth_opts],
        help="Set character styling over [start, end)",
    )
    _ = st.add_argument(
        "--start", type=int, required=True, help="Start index (inclusive)"
    )
    _ = st.add_argument("--end", type=int, required=True, help="End index (exclusive)")
    _ = st.add_argument(
        "--bold", action=argparse.BooleanOptionalAction, default=None, help="Set bold"
    )
    _ = st.add_argument(
        "--italic",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Set italic",
    )
    _ = st.add_argument(
        "--underline",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Set underline",
    )
    _ = st.add_argument("--link", help="Set a link URL over the range")

    ra = subparsers.add_parser(
        "replace-all",
        parents=[doc_opts, write_opts, auth_opts],
        help="Replace every occurrence of a string (templating)",
    )
    _ = ra.add_argument("--find", required=True, help="Text to find")
    _ = ra.add_argument("--replace", required=True, help="Replacement text")
    _ = ra.add_argument(
        "--match-case", action="store_true", help="Case-sensitive match"
    )

    ba = subparsers.add_parser(
        "batch",
        parents=[doc_opts, write_opts, auth_opts],
        help="Apply a raw list of batchUpdate requests (the long tail)",
    )
    _ = ba.add_argument(
        "--requests",
        required=True,
        help="JSON array of Docs request objects, e.g. '[{\"insertText\": {...}}]'",
    )

    cr = subparsers.add_parser(
        "create",
        parents=[write_opts, auth_opts],
        help="Create a new Doc from a Markdown note (needs --auth oauth)",
    )
    _ = cr.add_argument(
        "--from", dest="from_file", required=True, help="Markdown note path to import"
    )
    _ = cr.add_argument(
        "--title", help="Title for the new doc (default: the file stem)"
    )

    tp = subparsers.add_parser(
        "template",
        parents=[write_opts, auth_opts],
        help="Copy a template doc and fill placeholders (needs --auth oauth)",
    )
    _ = tp.add_argument(
        "--template-id", required=True, help="Template document ID or URL"
    )
    _ = tp.add_argument("--title", help="Title for the copy (default: 'Copy')")
    _ = tp.add_argument(
        "--replace",
        dest="replacements",
        action="append",
        metavar="FIND=VALUE",
        help="A find=value replacement (repeatable); FIND is the literal text",
    )

    _ = subparsers.add_parser(
        "auth-login",
        parents=[auth_opts],
        help="Run the one-time OAuth consent flow and store the token",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parse_typed_args(parser, _Args)
    # find/create/template/auth-login take no document; the rest resolve the
    # id/URL up front.
    no_document = {"find", "create", "template", "auth-login"}
    doc_id = "" if args.command in no_document else parse_document_id(args.document)
    _cli.run_cli(args.command, _ID_KEY, doc_id, args.auth, lambda: _run(args, doc_id))


if __name__ == "__main__":
    main()
