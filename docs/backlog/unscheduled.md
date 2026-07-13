# Unscheduled

Unversioned ideas. Every new idea lands here first; promotion into a version series file is a
deliberate planning act.

- [ ] **Port the mixd decision ledger into munin**
    - Effort: M
    - What: Adopt the evidence-typed decision-record format from `mixd/docs/decisions/` (README
      conventions + PDR files) as a munin convention, wired to research-harness output.
    - Why: munin now produces evidence-graded research (claim certainties, citation checks) but has
      no durable record of the decisions that research feeds; mixd's ledger already solves the
      recording half (evidence typing per row, append-only corrections, `re-verify` markers on
      perishable facts, memo-as-detail with ledger-row-as-pointer).
    - Dependencies: None
    - Notes: Source spec is `mixd/docs/decisions/README.md`; port the format, not the entries.
      Decide placement per `.claude/rules/trackers.md` before shipping (authoring rule: anything
      that persists data declares its home and tier first). Two plausible homes: vault notes under
      `Meta/` for life/vault decisions (notes-as-record), or in-repo `docs/decisions/` for tooling
      decisions, mirroring mixd. Natural join points: a ledger row's evidence column can carry the
      claim certainty band from `vault-tool research score`, and the `run-pass` skill's
      "Land the vault note" step can offer to append a ledger row when the research decided something.

- [ ] **Make munin tooling usable from any project, not just vault-rooted sessions**
    - Effort: L
    - What: Let any Claude Code session (couplefins, mixd, pewpew, ad-hoc dirs) invoke munin's
      tools: `vault-tool` modules (`research`, `fm`, `docs`, `sheets`, ...) and the research skills.
    - Why: the research harness is a general research tool, but today it
      only loads in sessions rooted at the vault or munin: skills live in `munin/.claude/skills/`
      (project-scoped), and the `vault-tool` dispatcher derives `VAULT_DIR` from its own `pwd`, so
      cross-project use already requires absolute paths and luck.
    - Dependencies: None
    - Notes: Three coupled surfaces to untangle, roughly in order:
      1. Dispatcher: `scripts/vault-tool` exports `VAULT_DIR` from bash's symlink-preserving `pwd`
         and pins `UV_PROJECT_ENVIRONMENT`; make `VAULT_DIR` overridable by env/flag with the
         current derivation as fallback, and audit which modules actually need a vault at all
         (`research` does not, aside from the output-note step; `fm`/`daily`/`trip` do).
      2. Skill distribution: user-level skills in `~/.claude/skills/` load everywhere, or follow the
         `ops-plugin` precedent and ship a plugin exposing the research skills portfolio-wide; the
         vault-specific output-placement half (`run-pass`'s "Land the vault note" step) must stay
         vault-scoped either way (split: research mechanics global, trackers placement local).
      3. Paths: the research harness is now a self-contained `vault_scripts/research` subpackage with
         no vault dependency except the output-note step, so it is portable once callers can find the
         dispatcher; document a canonical absolute path or a `~/.local/bin` shim.

- [ ] **Adopt pewpew provenance conventions in the research harness**
    - Effort: M
    - What: Port the durable-provenance pieces of `pewpew/research/` (spec: `pewpew/research/README.md`)
      into the research harness: a per-run source registry with stable ids, archive-on-capture for
      load-bearing sources, preserved verbatim excerpts, and pinned commit SHAs for code sources.
    - Why: munin's citation checker verifies quotes against pages as they exist at check time; pewpew
      goes further and makes evidence survive the web changing under it (its excerpts outlive upstream
      deletion, its load-bearing sources carry required archive links, its code reads pin a SHA). The
      example.com smoke test already demonstrated the failure mode: a true quote went stale within
      months.
    - Dependencies: None
    - Notes: Concrete candidates, roughly by value:
      1. Archive-on-capture: when `vault-tool research verify` verifies a load-bearing quote on a live page,
         request a Wayback snapshot (`https://web.archive.org/save/<url>`) so the fallback that
         rescued nothing at check time exists by re-check time; record the snapshot URL on the
         `CitationRecord`.
      2. Excerpt preservation: for sources driving a `confident`/`established` verdict, keep the
         matched page fragment (not the whole page) alongside the record so the report's quotes stay
         auditable after link rot; placement decision per `.claude/rules/trackers.md` (the current
         `.http-cache/` is explicitly disposable, so this needs a new home or a report-note appendix).
      3. Source ids: stable per-run `[S###]`-style ids mapping to `source_url`, so reports and ledger
         rows can cite tersely and one source's records stay greppable across shards.
      4. Pinned code sources: an optional `pinned` column (`owner/repo@sha`) on the evidence CSV row
         for claims about code, per pewpew's code-reading convention.
