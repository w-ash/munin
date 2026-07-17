# pyright: reportAny=false, reportExplicitAny=false
# Vendored research harness: this module reads argparse Namespace attributes, boundaries where the
# stdlib hands back `Any`. reportAny/reportExplicitAny are above
# basedpyright's standard strict (which this file passes); every other
# strict check still applies.
"""The `research` CLI: scaffold, validate, score, and share a research topic.

Subcommands:
    research new <slug> "Title" [--dest DIR] [--mode MODE]   scaffold a topic
    research check [--dir DIR]                 validate the CSV store
    research score [--dir DIR]                 computed scores for the topic's mode
    research status [--dir DIR]                alias of score
    research calibrate [--dir DIR]             check scores against data/gold.csv
    research verify [--dir DIR] [--timeout N] [--no-cache]   check cited quotes
    research render [--dir DIR] [--dry-run] [--verify]   store -> gated vault note
    research sync [--dir DIR] [--dry-run] [--force]   push to the Google Sheet

`score` dispatches on the topic's recorded mode (score.MODE_SCORERS); for a
`map` topic it is the familiar per-category confidence table. One JSON
envelope on stdout per run; human-readable tables go to stderr.
"""

import argparse
from pathlib import Path

from vault_scripts.research import (
    render as render_mod,
    scaffold,
    score as score_mod,
    store as store_mod,
    verify,
)
from vault_scripts.research._output import emit_error, emit_result, log, run_cli


def _load_checked(root: Path) -> store_mod.Topic:
    """Load a topic and abort with the issue list if validation fails."""
    topic = store_mod.load_topic(root)
    errors, warnings = store_mod.check(topic)
    if errors:
        emit_error(
            f"{len(errors)} validation error(s); fix them before continuing",
            errors=[e.as_dict() for e in errors],
            warnings=[w.as_dict() for w in warnings],
        )
    return topic


def cmd_check(args: argparse.Namespace) -> None:
    topic = store_mod.load_topic(Path(args.dir))
    errors, warnings = store_mod.check(topic)
    for issue in warnings:
        log(f"warning: {issue.file}:{issue.row or '-'}: {issue.message}")
    if errors:
        emit_error(
            f"{len(errors)} validation error(s)",
            errors=[e.as_dict() for e in errors],
            warnings=[w.as_dict() for w in warnings],
        )
    emit_result(
        status="clean",
        warnings=[w.as_dict() for w in warnings],
        counts=store_mod.counts(topic),
    )


def cmd_score(args: argparse.Namespace) -> None:
    """Dispatch to the topic mode's scorer; `status` is an alias of `score`."""
    topic = _load_checked(Path(args.dir))
    report = score_mod.MODE_SCORERS[topic.config.mode](topic)
    for line in report.table:
        log(line)
    emit_result(**report.envelope, counts=store_mod.counts(topic))


def cmd_calibrate(args: argparse.Namespace) -> None:
    """Check the mode's computed scores against the human labels in gold.csv."""
    topic = _load_checked(Path(args.dir))
    mode = topic.config.mode
    calibrator = score_mod.MODE_CALIBRATORS.get(mode)
    if calibrator is None:
        emit_error(
            f"research calibrate does not support {mode!r} topics: the {mode} "
            "scorer reports no per-item probability a gold label could check."
        )
    if store_mod.GOLD_CSV not in topic.tables:
        if mode == "estimate":
            emit_error(
                f"No data/{store_mod.GOLD_CSV}. Create it with columns "
                "item_id,actual,notes — item_id is a factor_id, actual its "
                "realized positive value; omit factors with no known outcome."
            )
        emit_error(
            f"No data/{store_mod.GOLD_CSV}. Create it with columns "
            "item_id,label,notes — item_id names a scored item (map: "
            "category_id; verify: claim_id; rank: <candidate>--<criterion>), "
            "label is true or false; omit items you haven't judged."
        )
    report = calibrator(topic)
    for line in report.table:
        log(line)
    emit_result(**report.envelope, counts=store_mod.counts(topic))


def cmd_verify(args: argparse.Namespace) -> None:
    topic = _load_checked(Path(args.dir))
    cache_dir = None if args.no_cache else verify.default_cache_dir(topic)
    records, counts = verify.verify_topic(
        topic, cache_dir=cache_dir, timeout=args.timeout
    )

    header = f"{'evidence':<10} {'category':<10} {'status':<14} url"
    log(header)
    log("-" * len(header))
    for record in records:
        archived = " (archived)" if record.archived else ""
        log(
            f"{record.evidence_id:<10} {record.category_id:<10} "
            f"{record.status:<14} {record.source_url}{archived}"
        )

    needs_attention = [
        {
            "evidence_id": r.evidence_id,
            "category_id": r.category_id,
            "status": r.status,
            "source_url": r.source_url,
        }
        for r in records
        if r.status in {verify.QUOTE_MISSING, verify.DEAD}
    ]
    citations_path = None
    if not args.no_write and records:
        citations_path = str(verify.write_citations(topic, records))
    emit_result(
        topic=topic.config.title,
        checked=len(records),
        counts=counts,
        needs_attention=needs_attention,
        citations=citations_path,
    )


def cmd_render(args: argparse.Namespace) -> None:
    """Project the verified store into its vault note, gated resolve-or-waive.

    The note is a projection of the store, never hand-authored: render refuses
    unless there is cited evidence and every cited row is verified or waived.
    ``--dry-run`` reports the gate verdict without writing; ``--verify`` runs a
    fresh citation check first so the gate sees current verdicts."""
    topic = _load_checked(Path(args.dir))
    mode = topic.config.mode
    if mode not in render_mod.MODE_RENDERERS:
        emit_error(
            f"research render does not support {mode!r} topics yet "
            f"(supported: {', '.join(sorted(render_mod.MODE_RENDERERS))})"
        )
    if args.verify:
        cache_dir = None if args.no_cache else verify.default_cache_dir(topic)
        records, _counts = verify.verify_topic(
            topic, cache_dir=cache_dir, timeout=args.timeout
        )
        if records:
            verify.write_citations(topic, records)
        topic = store_mod.load_topic(Path(args.dir))  # reload the fresh citations

    gate = render_mod.evaluate_gate(topic)
    if args.dry_run:
        verdict = "would render" if gate.ok else "would block"
        log(
            f"{verdict}: {gate.n_verified} verified, {gate.n_waived} waived, "
            f"{len(gate.blocking)} blocking of {gate.n_citable} cited row(s)"
        )
        for b in gate.blocking:
            log(f"  blocking {b.evidence_id} [{b.bucket}] {b.source_url}")
        emit_result(
            status="dry-run",
            topic=topic.config.title,
            would_pass=gate.ok,
            gate=gate.as_dict(),
            counts=store_mod.counts(topic),
        )
        return

    if not gate.ok:
        reason = (
            "the store has no cited evidence to render"
            if gate.n_citable == 0
            else f"{len(gate.blocking)} cited row(s) are neither verified nor waived"
        )
        emit_error(
            f"render blocked: {reason}. Run `research verify`, then fix each quote "
            "or record an exception in data/waivers.csv (evidence_id,reason,date).",
            blocking=[b.as_dict() for b in gate.blocking],
            gate=gate.as_dict(),
        )

    block = render_mod.build_evidence_block(topic, gate)
    root = render_mod.vault_root(args.vault_root)
    path, action = render_mod.write_note(topic, root, block)
    log(f"{action}: {path}")
    emit_result(
        status="rendered",
        topic=topic.config.title,
        note=str(path),
        action=action,
        gate=gate.as_dict(),
        counts=store_mod.counts(topic),
    )


def cmd_new(args: argparse.Namespace) -> None:
    created = scaffold.create_topic(
        args.slug, args.title, Path(args.dest), mode=args.mode
    )
    # Name the created mode's actual core CSVs so the guidance can't drift as
    # modes are added (the schema is the single source of truth).
    core_csvs = ", ".join(sorted(store_mod.MODE_SCHEMAS[args.mode].core_columns))
    emit_result(
        status="created",
        path=str(created.root),
        files=created.files,
        next_step=(
            "Seed the topic: fill the {{...}} placeholders in CLAUDE.md, "
            f"HANDOFF.md, and FINDER-PROMPT.md, seed the core CSVs ({core_csvs}), "
            "and set research.toml (the new-research skill walks through this)."
        ),
    )


def cmd_sync(args: argparse.Namespace) -> None:
    # Lazy: the Google auth/transport stack only loads when sync runs.
    from vault_scripts.research import mirror, sheets  # noqa: PLC0415

    topic = _load_checked(Path(args.dir))
    if not topic.config.sheet_id:
        emit_error(
            "No sheet_id in research.toml. Create a Google Sheet, copy the id "
            "from its URL (/spreadsheets/d/<id>/), and set [sheets] sheet_id."
        )
    extras = mirror.MODE_MIRRORS[topic.config.mode](topic)
    result = sheets.sync(topic, extras, dry_run=args.dry_run, force=args.force)
    emit_result(**result)


def main() -> None:
    def _main() -> None:
        parser = argparse.ArgumentParser(
            prog="research", description="Evidence-based research harness."
        )
        sub = parser.add_subparsers(dest="command", required=True)

        p_new = sub.add_parser("new", help="scaffold a new topic directory")
        p_new.add_argument("slug", help="kebab-case directory name")
        p_new.add_argument("title", help="human-readable topic title")
        p_new.add_argument(
            "--dest",
            default=str(scaffold.default_data_home()),
            help="parent directory (default: the research data home, outside any repo)",
        )
        p_new.add_argument(
            "--mode",
            default="map",
            choices=sorted(store_mod.MODE_NAMES),
            help="research shape; picks the store schema and scorer (default: map)",
        )
        p_new.set_defaults(func=cmd_new)

        for name, func, help_text in (
            ("check", cmd_check, "validate the CSV store"),
            ("score", cmd_score, "computed scores for the topic's mode"),
            ("status", cmd_score, "alias of score"),
            ("calibrate", cmd_calibrate, "check scores against data/gold.csv"),
        ):
            p = sub.add_parser(name, help=help_text)
            p.add_argument("--dir", default=".", help="topic directory (default: cwd)")
            p.set_defaults(func=func)

        p_verify = sub.add_parser(
            "verify", help="fetch cited URLs and check the quotes appear"
        )
        p_verify.add_argument(
            "--dir", default=".", help="topic directory (default: cwd)"
        )
        p_verify.add_argument(
            "--timeout", type=float, default=20.0, help="per-request timeout, seconds"
        )
        p_verify.add_argument(
            "--no-cache", action="store_true", help="ignore the HTTP cache and refetch"
        )
        p_verify.add_argument(
            "--no-write",
            action="store_true",
            help="don't persist verdicts to data/citations.csv (advisory only)",
        )
        p_verify.set_defaults(func=cmd_verify)

        p_render = sub.add_parser(
            "render", help="project the verified store into its vault note (gated)"
        )
        p_render.add_argument(
            "--dir", default=".", help="topic directory (default: cwd)"
        )
        p_render.add_argument(
            "--dry-run",
            action="store_true",
            help="report the gate verdict without writing the note",
        )
        p_render.add_argument(
            "--verify",
            action="store_true",
            help="run a fresh citation check first so the gate sees current verdicts",
        )
        p_render.add_argument(
            "--timeout", type=float, default=20.0, help="per-request timeout, seconds"
        )
        p_render.add_argument(
            "--no-cache", action="store_true", help="ignore the HTTP cache and refetch"
        )
        p_render.add_argument(
            "--vault-root",
            default=None,
            help="vault root for a relative vault_note (default: $VAULT_DIR)",
        )
        p_render.set_defaults(func=cmd_render)

        p_sync = sub.add_parser("sync", help="push the store to its Google Sheet")
        p_sync.add_argument("--dir", default=".", help="topic directory (default: cwd)")
        p_sync.add_argument(
            "--dry-run", action="store_true", help="report without writing"
        )
        p_sync.add_argument(
            "--force", action="store_true", help="push even if unchanged"
        )
        p_sync.set_defaults(func=cmd_sync)

        args = parser.parse_args()
        args.func(args)

    run_cli(_main)
