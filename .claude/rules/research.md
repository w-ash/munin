---
description: The evidence-based research harness — subpackage layout, the five modes, the vault-tool research CLI, where topic data lives, and its trackers tier
paths:
  - "scripts/vault_scripts/research/**"
  - ".claude/skills/new-research/**"
  - ".claude/skills/run-pass/**"
  - ".claude/skills/share-research/**"
---

# Research harness

Evidence-based research run as a persistent, multi-pass study. `vault-tool
research` scaffolds a topic, then each pass runs finders plus a critic, applies
rows centrally, mechanically verifies citations, and recomputes falsifiable
confidence from the CSV store. The operational entry is three skills:
`new-research` (spin up and seed), `run-pass` (one pass), `share-research` (Sheet
mirror). All research goes through this harness.

## Modes

Chosen at scaffold time (`--mode`, recorded in `research.toml`); each picks the
store schema (`store.MODE_SCHEMAS`) and scorer (`score.MODE_SCORERS`):

- `map` — how does a space break down? Breadth confidence per category.
- `verify` — are these claims true? Source-weighted certainty in decibans.
- `rank` — which candidate is best? Weighted rubric fit, blocker-gated, plus a pairwise check.
- `find` — enumerate a bounded frame with attributes. Recall plus per-field verification.
- `estimate` — how big or how much? Lognormal factor decomposition with a propagated interval.

Confidence is computed from the evidence on every run (never stored), so it can't
drift; a category or claim stays below "High" until a primary source backs it.

## Package layout

`scripts/vault_scripts/research/`, invoked via `vault-tool research` (a package
module with an `__main__.py`, which the dispatcher runs with `python -m`):

- `cli.py` — the argparse surface (`new|check|score|status|calibrate|verify|render|sync`).
- `store.py` — per-mode CSV schemas, topic load, and the `check` integrity gate.
- `confidence` / `certainty` / `coverage` / `magnitude` — the per-mode scoring engines.
- `score.py` — the mode-dispatched scorer and calibrator registry.
- `calibration.py` — checks scores against a hand-authored `data/gold.csv`.
- `verify.py` — mechanical citation check (quote shingles, on-disk cache, Wayback).
- `render.py` — the store-to-note projection and the resolve-or-waive render gate (one `MODE_RENDERERS` entry per mode).
- `mirror.py` + `sheets.py` — the one-way Google Sheet mirror.
- `scaffold.py` + `templates/` — the topic scaffold (packaged data).
- `_output.py` — the JSON-envelope CLI plumbing (`emit_result`/`emit_error`/`log`/`run_cli`).

## Where data lives (trackers tier)

A topic directory is a **working store**, not a vault note: append-only
`data/*.csv` (canonical-files tier), a regenerated `SYNTHESIS.md`, and a
hand-authored `narrative/`. It lives **outside iCloud** (default
`~/.local/share/vault-research/`) because the CSVs are appended frequently and would
hit the iCloud write race, and it is never copied into the vault. This placement is
enforced, not just conventional: `vault-tool research new` defaults `--dest` to the
data home and refuses a destination inside any git working tree or the iCloud vault,
so a store can never be scaffolded into the munin repo or the vault.

The durable, notes-as-record deliverable is a **projection** of the verified store,
produced by `vault-tool research render` into the path set in
`research.toml` `[topic] vault_note`, per `.claude/rules/trackers.md` (Ideas/, a
project folder, `Meta/`, or a trip's `References/`), wikilinked both ways. The vault
note is never hand-transcribed: render gates on resolve-or-waive (every cited row is
`verified` or recorded in `data/waivers.csv` with a reason), writes a managed evidence
block with per-claim verification marks, and preserves the hand-authored narrative
outside the markers. The HTTP fetch cache (`.http-cache/`) and the sync-state
(`.research-sync-state.json`) are disposable dot-files inside the topic.

## Google Sheets mirror

`sheets.py` and `mirror.py` push one-way to the Sheet in `research.toml`
`[sheets]` through the vault's own Google stack (`_google` / `_sheets`), not a
separate auth path: `[sheets] auth` selects oauth-user (default, acts as you) or the
service account, the same two modes as `vault-tool sheets` and `docs`.

## Conventions this harness keeps, and where it deviates

- The subpackage is **self-contained**: its schemas live in `store.MODE_SCHEMAS` and
  per-module dataclasses, not the `_types.py` hub, so the vendored harness stays one
  unit. This is a deliberate deviation from the "models go in `_types.py`" guidance
  in `.claude/rules/scripts.md`.
- `store.py`, `cli.py`, `verify.py`, and `score.py` carry a file-level
  `# pyright: reportAny=false, reportExplicitAny=false`. They read CSV/TOML/JSON,
  fetch HTML, and read argparse Namespaces at boundaries where the stdlib returns
  `Any`. Those two flags sit above basedpyright's standard strict (which the files
  pass); every other strict check still applies.
- `verify.py` fetches pages with `urllib` (HTML scraping, not a JSON API), so it does
  not route through `_retry.request_json`; only the Wayback availability check is a
  JSON call.
