// Scored / durable mode for the deep-research skill (v2).
//
// Shape: deterministic orchestrator (this script) + ephemeral schema-bound
// subagents + a deterministic Python scoring core (`vault-tool evidence`).
// The orchestrator never trusts an agent with arithmetic or citation diligence:
// certainty comes from the weight-of-evidence engine, quotes are checked
// mechanically against their URLs before anything scores, and shard/manifest
// reconciliation catches claim-id drift between agents. Spec:
// .claude/rules/evidence.md. Workflow scripts have no filesystem access; the
// agents do all file I/O and CLI calls.
//
// Args (paths absolute):
//   question   required
//   runDir     required; tmp dir for shards (disposable run artifacts, never vault)
//   vaultTool  required; .../scripts/vault-tool
//   rubric     optional -> ranking mode. {criteria: [{id, text, weight, tier:
//              blocker|must|should|nice}], candidates: [{id, name}],
//              blocker_threshold}. Elicit and confirm it with the user BEFORE
//              launching (SKILL.md); the workflow itself never pauses for input.
//   maxFacets  optional, default 5
//   recency    optional; e.g. "claims about current practice need 2025+ sources"
//
// Durability: finders record each item the moment it is confirmed (validated CLI
// append), so a crash costs one in-flight item. Resume with
// Workflow({ scriptPath, resumeFromRunId }) and the SAME runDir: completed
// agents replay from cache; shard dedup makes replayed appends harmless.

export const meta = {
  name: 'scored-research',
  description: 'Durable research with mechanical citation checks and deterministic claim scoring / candidate ranking',
  phases: [
    { title: 'Scope', detail: 'facets, diversified query pool, claim registry -> manifest' },
    { title: 'Find', detail: 'one finder per facet, validated append-as-you-go, coverage rounds' },
    { title: 'Citations', detail: 'mechanically check every (url, quote); reconcile shards vs manifest' },
    { title: 'Verify', detail: 'fresh-context refuters on the load-bearing claims' },
    { title: 'Score', detail: 'deterministic scoring (and ranking) via vault-tool evidence' },
    { title: 'Refine', detail: 're-research load-bearing low-confidence claims, recheck, rescore' },
    { title: 'Synthesize', detail: 'cited report; ranking adds swap-order pairwise sanity check' },
  ],
}

// --- config ---
let cfg = args
if (typeof cfg === 'string') {
  try { cfg = JSON.parse(cfg) } catch (_) { cfg = { question: cfg } }
}
cfg = cfg || {}
const QUESTION = cfg.question
const RUN_DIR = cfg.runDir
const VAULT_TOOL = cfg.vaultTool
const RUBRIC = cfg.rubric || null
const MAX_FACETS = cfg.maxFacets || 5
const RECENCY = cfg.recency ? `Recency rule: ${cfg.recency}\n` : ''
if (!QUESTION || !RUN_DIR || !VAULT_TOOL) {
  throw new Error('scored-research requires args.question, args.runDir (absolute tmp path), and args.vaultTool')
}
const EV = `"${VAULT_TOOL}" evidence`

// Budget posture: with a "+500k"-style target set, coverage scales to it; with
// none, defaults keep a run in the same cost class as the built-in workflow.
const MAX_FIND_ROUNDS = 3
const ROUND_RESERVE = 120_000   // don't start another find round below this
const REFINE_RESERVE = 80_000   // don't start the refine pass below this
const VERIFY_CAP = 8
const REFINE_CAP = 4
const hasBudgetFor = (n) => !budget.total || budget.remaining() > n

// --- schemas ---
const SCOPE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    facets: { type: 'array', items: { type: 'string' }, description: 'independent sub-questions, researched in parallel' },
    queries: {
      type: 'array', items: { type: 'array', items: { type: 'string' } },
      description: 'parallel to facets: 6-10 search queries per facet, diversified across modalities',
    },
    claims: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: { id: { type: 'string' }, text: { type: 'string' } },
        required: ['id', 'text'],
      },
    },
  },
  required: ['facets', 'queries', 'claims'],
}
const FIND_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    shard: { type: 'string' },
    items_appended: { type: 'number' },
    claim_ids: { type: 'array', items: { type: 'string' } },
    saturated: { type: 'boolean', description: 'true when further searching stopped yielding new admissible evidence' },
    dropped_leads: { type: 'string', description: 'promising directions not pursued (empty if none)' },
  },
  required: ['shard', 'items_appended', 'saturated'],
}
const CITATION_COUNTS = {
  type: 'object', additionalProperties: false,
  properties: {
    verified: { type: 'number' }, quote_missing: { type: 'number' }, dead: { type: 'number' },
    unfetchable: { type: 'number' }, no_quote: { type: 'number' },
  },
}
const CITATIONS_RESULT = {
  type: 'object', additionalProperties: false,
  properties: { checked: { type: 'number' }, counts: CITATION_COUNTS },
  required: ['checked', 'counts'],
}
const MECH_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    citations: CITATIONS_RESULT,
    check: {
      type: 'object', additionalProperties: false,
      properties: {
        problems: { type: 'array', items: { type: 'string' } },
        coined: { type: 'array', items: { type: 'string' } },
        no_evidence: { type: 'array', items: { type: 'string' } },
      },
      required: ['problems', 'coined', 'no_evidence'],
    },
  },
  required: ['citations', 'check'],
}
const DRIVER = {
  type: 'object', additionalProperties: false,
  properties: {
    source_url: { type: 'string' }, source_tier: { type: 'string' },
    bearing: { type: 'string' }, decibans: { type: 'number' },
  },
  required: ['source_url', 'source_tier', 'bearing', 'decibans'],
}
const CLAIM_VERDICT = {
  type: 'object', additionalProperties: false,
  properties: {
    claim_id: { type: 'string' }, claim: { type: 'string' },
    certainty: { type: 'number' }, band: { type: 'string' },
    net_decibans: { type: 'number' }, n_sources: { type: 'number' },
    capped: { type: 'boolean' }, drivers: { type: 'array', items: DRIVER },
  },
  required: ['claim_id', 'certainty', 'band', 'n_sources'],
}
const CANDIDATE_VERDICT = {
  type: 'object', additionalProperties: false,
  properties: {
    candidate_id: { type: 'string' }, candidate: { type: 'string' },
    score: { type: 'number' }, blocked: { type: 'boolean' },
    blocked_by: { type: 'array', items: { type: 'string' } },
    least_resolved: { type: 'string' },
    evidence_gaps: { type: 'array', items: { type: 'string' } },
    criteria: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          criterion_id: { type: 'string' }, tier: { type: 'string' }, weight: { type: 'number' },
          certainty: { type: 'number' }, band: { type: 'string' },
          n_sources: { type: 'number' }, capped: { type: 'boolean' },
        },
        required: ['criterion_id', 'tier', 'certainty', 'band', 'n_sources'],
      },
    },
  },
  required: ['candidate_id', 'candidate', 'score', 'blocked'],
}
const SCORE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    claims: { type: 'array', items: CLAIM_VERDICT },
    candidates: { type: 'array', items: CANDIDATE_VERDICT },
    scorecard: { type: 'string', description: 'markdown from rank, when ranking' },
  },
  required: ['claims'],
}
const PAIRWISE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    winner: { type: 'string', description: 'candidate_id of the better fit' },
    margin: { type: 'string', enum: ['clear', 'slight'] },
    reason: { type: 'string' },
  },
  required: ['winner', 'margin', 'reason'],
}

// --- prompt fragments (contract style: objective, output contract, tool guidance, boundaries) ---
const TIER_GUIDE = `- source_tier: primary (own authorship, peer-reviewed, official record) | community (named human recommendation) | secondary (self-authored profile or site copy) | weak (aggregator, listicle, SEO or AI-generated roundup, inference).
- bearing: supports | refutes. strength: weak | moderate | strong.`

const appendRule = (shard) => `RECORDING (validated, write-as-you-go): the moment you confirm EACH finding, record it BEFORE moving on:
  ${EV} append --shard "${shard}" --json '<EvidenceItem as compact JSON>'
A non-ok response means the item did NOT record: fix it and retry; never continue past a failed append. If the JSON contains single quotes, write it to a temp file first and pass --json "$(cat <file>)".
EvidenceItem: {"claim_id","claim","source_url","source_tier","bearing","strength","quote"}
- claim_id: use a registered id from the list you were given; coin a new kebab-case slug only for a genuinely new claim.${RUBRIC ? ' NEVER invent rubric-cell ids: an unregistered "<candidate>--<criterion>" id is drift and gets flagged, not scored.' : ''}
${TIER_GUIDE}
- quote: copy the supporting text VERBATIM from the page; it is later checked mechanically against the URL, and a paraphrased or reconstructed quote gets the item excluded. Cite only URLs you actually opened.`

const runCli = (cmds) => `Run these exact commands in order and report their JSON outputs in the response schema. Do not recompute, summarize, or editorialize; if a command errors, report the error text.\n${cmds.map((c) => `  ${c}`).join('\n')}`

// --- Scope ---
phase('Scope')
// Ranking mode: the claim grid is deterministic (candidates x criteria), built
// here rather than trusted to an agent's slug discipline.
const gridClaims = RUBRIC
  ? RUBRIC.candidates.flatMap((cand) => RUBRIC.criteria.map((crit) => ({
      id: `${cand.id}--${crit.id}`,
      text: `${cand.name || cand.id} satisfies: ${crit.text || crit.id}`,
    })))
  : []
const rubricBrief = RUBRIC
  ? `\nThis is a RANKING question. Candidates: ${RUBRIC.candidates.map((c) => c.name || c.id).join(', ')}. Criteria: ${RUBRIC.criteria.map((c) => `${c.id} (${c.tier})`).join(', ')}. The claim grid is already registered; your facets should partition the evidence-gathering (per candidate, or per criterion cluster), not redefine it. Register extra claims ONLY for questions outside the grid (e.g. a deal-breaker the rubric missed); a claim restating a candidate-vs-criterion question splits that cell's evidence across two ids.`
  : ''

const scope = await agent(
  `Objective: plan the research for: "${QUESTION}"${rubricBrief}
${RECENCY}Decompose into at most ${MAX_FACETS} INDEPENDENT facets researchable in parallel without overlap${RUBRIC ? '' : ', and list the concrete claims the answer depends on, each with a short kebab-case slug id'}.
For EACH facet, generate 6-10 search queries as a set: queries are assigned to parallel finders centrally so they do not all open with the same obvious search and retrieve the same pages. Diversify across modalities: terminology variants, entity-specific, comparison-shaped, community/forum-targeted, primary-source-targeted${RECENCY ? ', recency-scoped' : ''}.
Boundaries: planning only; do not research the question itself.`,
  { label: 'scope', phase: 'Scope', schema: SCOPE_SCHEMA }
)
if (!scope) throw new Error('scope agent failed')
const facets = scope.facets.slice(0, MAX_FACETS)
const queries = scope.queries || []
const claims = [...gridClaims, ...(scope.claims || [])]
const claimList = claims.map((c) => `  - ${c.id}: ${c.text}`).join('\n')

const manifest = JSON.stringify({
  question: QUESTION,
  facets,
  claims,
  rubric: RUBRIC,
  queries,
  v: 2,
})
await agent(
  `Write this exact JSON to ${RUN_DIR}/manifest.source.json (create the directory if needed), then validate and register it with:\n  ${EV} manifest --run-dir "${RUN_DIR}" --json "$(cat '${RUN_DIR}/manifest.source.json')"\nReport the command output. Do not modify the JSON.\n\n${manifest}`,
  { label: 'manifest', phase: 'Scope', agentType: 'general-purpose', effort: 'low' }
)
log(`Scope: ${facets.length} facets, ${claims.length} registered claims${RUBRIC ? ` (${gridClaims.length} rubric cells)` : ''}`)

// --- Find: assigned diversified queries; coverage rounds until saturated or budget-bound ---
const finderPrompt = (facet, i, round) => `Objective: gather evidence on one facet of: "${QUESTION}"
Facet: ${facet}
${RECENCY}${round > 1 ? `This is follow-up round ${round}: read your shard first and pursue what is still uncovered; do not re-record sources already in it.\n` : `Assigned starting queries (centrally diversified; adapt freely once exhausted):\n${(queries[i] || []).map((q) => `  - ${q}`).join('\n')}\n`}Method: web search first; open the actual pages behind anything you cite and prefer primary sources. Treat SEO-shaped secondary content (listicles, affiliate roundups, AI-generated aggregators) adversarially: tier it weak and try to trace its claims to a primary source.
Registered claims (share these ids so evidence composes):
${claimList}
${appendRule(`${RUN_DIR}/finder-${i + 1}.jsonl`)}
Boundaries: evidence gathering only; no verdicts, no scoring.
Return the summary: saturated=true when your last few searches stopped yielding new admissible evidence; note promising leads you did not pursue in dropped_leads.`

let active = facets.map((facet, i) => ({ facet, i }))
let round = 0
while (active.length && round < MAX_FIND_ROUNDS) {
  round++
  if (round > 1 && !hasBudgetFor(ROUND_RESERVE)) {
    log(`Find: budget floor reached; dropping round ${round} for ${active.length} unsaturated facet(s): ${active.map((a) => a.facet).join(' | ')}`)
    break
  }
  const results = await parallel(active.map(({ facet, i }) => () =>
    agent(finderPrompt(facet, i, round), {
      label: `find:${i + 1}${round > 1 ? `.r${round}` : ''}`, phase: 'Find',
      schema: FIND_SCHEMA, agentType: 'general-purpose', effort: 'high',
    }).then((s) => ({ i, facet, summary: s }))
  ))
  const done = results.filter(Boolean)
  active = done.filter((r) => r.summary && r.summary.saturated === false).map(({ facet, i }) => ({ facet, i }))
  log(`Find round ${round}: ${done.length} finder(s) done, ${active.length} facet(s) still unsaturated`)
}

// --- Citations: mechanical quote/liveness check + shard-vs-manifest reconciliation ---
phase('Citations')
const mechCmds = [
  `${EV} verify-citations --run-dir "${RUN_DIR}"`,
  `${EV} check --run-dir "${RUN_DIR}"`,
]
const mech = await agent(
  `${runCli(mechCmds)}\ncheck exits nonzero when it found problems; capture its JSON either way.`,
  { label: 'citations+check', phase: 'Citations', schema: MECH_SCHEMA, agentType: 'general-purpose', effort: 'low' }
)
const reconciliation = mech ? mech.check : { problems: [], coined: [], no_evidence: [] }
if (mech) log(`Citations: ${mech.citations.checked} pairs checked ${JSON.stringify(mech.citations.counts)}; ${reconciliation.problems.length} reconciliation problem(s)`)

// --- Score (interim): deterministic numbers to pick verification targets from ---
const scoreCmds = RUBRIC
  ? [`${EV} score --run-dir "${RUN_DIR}"`, `${EV} rank --run-dir "${RUN_DIR}" --markdown`]
  : [`${EV} score --run-dir "${RUN_DIR}" --markdown`]
const scoreAgent = (label) => agent(
  `${runCli(scoreCmds)}\nMap score's "claims" to claims${RUBRIC ? ', rank\'s "candidates" to candidates, and rank\'s "markdown" to scorecard' : ''}.`,
  { label, phase: 'Score', schema: SCORE_SCHEMA, agentType: 'general-purpose', effort: 'low' }
)
const interim = await scoreAgent('score:interim')
if (!interim) throw new Error('interim scoring failed')

// Load-bearing selection: what actually drives the verdict. Ranking: every cell
// of the top unblocked candidates plus every blocker cell anywhere. Claims mode:
// the strongest supported claims (they carry the report's assertions).
function loadBearing(scored) {
  const verdicts = scored.claims || []
  if (RUBRIC && scored.candidates) {
    const top = scored.candidates.filter((c) => !c.blocked).slice(0, 3).map((c) => c.candidate_id)
    const wanted = new Set()
    for (const cand of RUBRIC.candidates) {
      for (const crit of RUBRIC.criteria) {
        if (top.includes(cand.id) || crit.tier === 'blocker') wanted.add(`${cand.id}--${crit.id}`)
      }
    }
    return verdicts.filter((v) => wanted.has(v.claim_id))
  }
  return verdicts.filter((v) => v.certainty >= 55).sort((a, b) => b.certainty - a.certainty)
}

// --- Verify: fresh-context refuters, capped and budget-scaled ---
phase('Verify')
const verifiable = loadBearing(interim)
const verifyBudgetCap = budget.total ? Math.max(2, Math.floor(budget.remaining() / 40_000)) : VERIFY_CAP
const targets = verifiable.slice(0, Math.min(VERIFY_CAP, verifyBudgetCap))
if (verifiable.length > targets.length) {
  log(`Verify: capped at ${targets.length}; ${verifiable.length - targets.length} load-bearing claim(s) not adversarially verified`)
}
await parallel(targets.map((v, k) => () =>
  agent(
    `Objective: try to REFUTE this claim: "${v.claim || v.claim_id}" (claim_id ${v.claim_id}; current certainty ${v.certainty}, ${v.n_sources} source(s)).
You are a fresh-context skeptic with no stake in the finding. Search for disconfirming evidence, contradicting primary sources, and newer information that supersedes it.${RECENCY ? `\n${RECENCY.trim()}` : ''}
${appendRule(`${RUN_DIR}/verify-${k + 1}.jsonl`)}
Append refutes items for every genuine counter-finding; append supports only when you independently confirm from a source that is NOT already cited for this claim. Default to skepticism; finding nothing is a valid outcome (return items_appended 0).
Return the summary.`,
    { label: `verify:${v.claim_id}`, phase: 'Verify', schema: FIND_SCHEMA, agentType: 'general-purpose' }
  )
))

// --- Score (post-verify) ---
let scored = await scoreAgent('score:final')
if (!scored) scored = interim

// --- Refine: one targeted re-research round for load-bearing low-confidence spots ---
phase('Refine')
function refineTargets(s) {
  if (RUBRIC && s.candidates) {
    const top = s.candidates.filter((c) => !c.blocked).slice(0, 3)
    const cells = new Set()
    for (const c of top) {
      for (const gap of c.evidence_gaps || []) cells.add(`${c.candidate_id}--${gap}`)
      if (c.least_resolved) cells.add(`${c.candidate_id}--${c.least_resolved}`)
    }
    return (s.claims || []).filter((v) => cells.has(v.claim_id))
  }
  return (s.claims || []).filter((v) => v.band === 'tentative' && v.n_sources > 0)
}
const refinable = refineTargets(scored).slice(0, REFINE_CAP)
if (refinable.length && hasBudgetFor(REFINE_RESERVE)) {
  await parallel(refinable.map((v, k) => () =>
    agent(
      `Objective: resolve a low-confidence claim that the verdict depends on: "${v.claim || v.claim_id}" (claim_id ${v.claim_id}; certainty ${v.certainty}, band ${v.band}, ${v.n_sources} source(s)).
${RECENCY}Hunt specifically for PRIMARY sources (official records, own authorship, peer-reviewed work) bearing on it, in either direction; primary sourcing is what lifts the certainty ceiling.
${appendRule(`${RUN_DIR}/refine-${k + 1}.jsonl`)}
Boundaries: this one claim only. Return the summary.`,
      { label: `refine:${v.claim_id}`, phase: 'Refine', schema: FIND_SCHEMA, agentType: 'general-purpose' }
    )
  ))
  // New evidence means new (url, quote) pairs: recheck (cached URLs are free), rescore.
  await agent(runCli([mechCmds[0]]), { label: 'citations:recheck', phase: 'Refine', schema: CITATIONS_RESULT, agentType: 'general-purpose', effort: 'low' })
  const rescored = await scoreAgent('score:refined')
  if (rescored) scored = rescored
} else if (refinable.length) {
  log(`Refine: budget floor reached; ${refinable.length} low-confidence load-bearing claim(s) left unrefined: ${refinable.map((v) => v.claim_id).join(', ')}`)
}

// --- Synthesize (+ swap-order pairwise sanity check in ranking mode) ---
phase('Synthesize')
let pairwise = null
if (RUBRIC && scored.candidates) {
  const clean = scored.candidates.filter((c) => !c.blocked)
  if (clean.length >= 2) {
    const [x, y] = clean
    const judge = (first, second, label) => agent(
      `Rubric fit judgment. Two candidates were researched against the same rubric; from the per-criterion evidence below alone, decide which is the better overall fit. Ignore presentation order and verbosity; weigh criterion tiers (blocker > must > should > nice) and evidence strength.
FIRST: ${JSON.stringify(first)}
SECOND: ${JSON.stringify(second)}
Return winner as the candidate_id.`,
      { label, phase: 'Synthesize', schema: PAIRWISE_SCHEMA }
    )
    const [fwd, rev] = await parallel([
      () => judge(x, y, `pairwise:${x.candidate_id}-first`),
      () => judge(y, x, `pairwise:${y.candidate_id}-first`),
    ])
    pairwise = {
      a: x.candidate_id, b: y.candidate_id,
      forward: fwd, reverse: rev,
      agree: Boolean(fwd && rev && fwd.winner === rev.winner),
    }
    log(`Pairwise check ${x.candidate_id} vs ${y.candidate_id}: ${pairwise.agree ? `agreed on ${fwd.winner}` : 'order-dependent disagreement (reported, not averaged)'}`)
  }
}

const synthesisInput = {
  claims: scored.claims,
  candidates: scored.candidates || null,
  scorecard: scored.scorecard || null,
  pairwise,
  reconciliation,
  citations: mech ? mech.citations : null,
}
const report = await agent(
  `Write the cited research report answering: "${QUESTION}"
Use ONLY the scored data below; do not assert beyond the certainty the evidence supports. Certainties and bands come from the deterministic scoring engine and are the report's confidence labels.
Structure: a one-paragraph headline verdict;${RUBRIC ? ' the ranking with per-candidate rationale (fit score, blockers, evidence gaps; include the scorecard table verbatim; report the pairwise sanity check, including any order-dependent disagreement, as-is);' : ''} findings grouped by confidence band, each stating its certainty and citing its top driving sources; a "Refuted / low-confidence" section for what verification drove down; caveats (fold in reconciliation: claims with no evidence found, coined claims outside the registry, and citation-check counts); open questions; sources.
Write with plain punctuation (no em dashes), per the vault writing standard.

DATA:
${JSON.stringify(synthesisInput)}`,
  { label: 'synthesize', phase: 'Synthesize', agentType: 'general-purpose', effort: 'high' }
)

return {
  runDir: RUN_DIR,
  mode: RUBRIC ? 'ranking' : 'claims',
  facets: facets.length,
  findRounds: round,
  reconciliation,
  citations: mech ? mech.citations : null,
  verdicts: scored.claims,
  candidates: scored.candidates || null,
  pairwise,
  report,
}
