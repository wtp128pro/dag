# Evidence Standards — the anti-hallucination rulebook (req 10)

The rule is simple and absolute: **no material claim without admissible evidence.** What
counts as "admissible" is *adaptive to the claim type* (chosen because a generic task may
have no web-researchable facts at all — code claims are proven by code, not citations).

Executors attach an **evidence table** to every debrief. Verifiers reject any row whose
evidence is missing, inadmissible, or unreproducible.

## Evidence preference ordering — executable/reproducible **over** asserted (PR2)

Not all admissible evidence is equal. **Prefer evidence the verifier can *mechanically
regenerate* over evidence it must take on faith**, in this order:

1. **Executable / reproducible** — a command + its output, a re-run test, a diff of expected vs
   actual, a re-derived number (with the derivation). The verifier *re-runs it* and compares.
2. **Located but static** — a `file:line`, a dated URL + quoted section, an observed
   request/response captured earlier. The verifier *re-opens* it.
3. **Asserted** — "I checked and it holds." Admissible only when 1–2 are genuinely infeasible,
   and then it must be labeled `ASSUMPTION:` with its blast radius (rule 2).

Why this ordering is **load-bearing** (not stylistic): a re-run's correctness does **not depend on
the checker's reasoning depth** — the machine settles it. That makes reproducible evidence
*model-independent*: a modest verifier re-running a test reaches the same verdict a stronger one
would, so structure (reproducibility) substitutes for raw model IQ. It is also the **prerequisite
for data-parallel verification** (references/data-partitioning.md): a verifier that re-runs a
bounded op on a shard locator and diffs the result never needs the raw data in context. When a
claim *can* be made executable, an asserted-only version of it is a weaker debrief and the verifier
should down-rank or reject it.

## Claim taxonomy → admissible evidence

| Claim type | Example | Admissible evidence (ground truth) | Inadmissible (reject) |
|---|---|---|---|
| **Empirical/world fact** | "Library X's v3 dropped API Y." | External scope: T-VENDOR source, quoted + URL/locator + retrieval rung + accessed date. Two independent sources (neither derived from the other) for contested/version-sensitive facts. T-COMM corroborates (vendor-silent form for sole support). Project scope: T-LOCAL reproducible locator (git SHA, path:line, PR#, ledger path). | "I recall…", blog without primary backing, undeclared parametric memory, a fresh date stamped on a stale source |
| **Code behavior** | "`verify()` rejects expired tokens." | The code itself (path:line), plus a **run**: a test/REPL/command output showing the behavior | "It should…", reading a name and inferring behavior |
| **API/tool contract** | "This endpoint returns 429 on limit." | T-VENDOR docs, fetched + quoted + dated (URL + accessed); an observed request/response corroborates and is expected where feasible. Observation alone supports only an observed-behavior claim, via a declared fallback rung | Guessing from the function name; observation alone presented as the contract; an undated doc recollection; the contract retyped as code-behavior to dodge the tier |
| **Numeric/quantitative** | "p95 latency is 180ms." | The measurement + how it was produced (command, dataset, date) | Round numbers with no derivation |
| **Causal** | "The leak is caused by Z." | A reproduction that toggles Z and shows the effect appear/disappear | Correlation, plausibility |
| **Design/judgment** | "Approach A is better than B." | An argument grounded in the *clarified acceptance criteria*, with the tradeoff made explicit; not "facts" but must be *reasoned*, and the losing option's merits stated. Every load-bearing factual premise inside the argument is extracted as its own typed claim and listed in the row's `extracted_premises` (empty only with an explicit none-reason) | Assertion of superiority with no criteria linkage; a factual premise laundered inside the argument without its own evidence row |
| **Provenance/quote** | "Author says '…'." | The exact source, verbatim, with locator; verify it exists before quoting | Paraphrase presented as a quote; unverifiable attributions |

## Source tiers & mandatory retrieval standard

Externally-sourced evidence carries a **tier tag**; retrieval is **mandatory per claim type**,
not advisory. Tier authority is claim-scoped, not a global order: local sources are PRIMARY for
project-scoped claims and hearsay for world claims; vendor docs are PRIMARY for external
normative claims. Direct observation (a run/reproduction with its recipe recorded) is an evidence
FORM for behavior/measurement/causal claims, not a source tier. Tier requirements per claim type
are normative in the claim-type table above — this section defines the tiers, the fallback
ladder, and the claims-owed obligations.

| Tier | Covers | Authority |
|---|---|---|
| **T-VENDOR** | Official docs, changelogs, specs, standards, official API refs, the vendor's own repo | Authoritative for external normative claims; contested/version-sensitive facts need two independent sources (neither citing nor deriving from the other) |
| **T-COMM** | Known-good community venues admitted ONCE in the run's SOURCES register under: K-A accountable venue (attributable standing/editorial control AND public correction machinery); K-B chaseable to primary or reproducible artifact; K-C dated + version-matched, not stale | Corroborative. Sole support for a load-bearing external claim ONLY with `vendor_silent: true` + a `vendor_surface_searched` locator + the row's recorded K-B chase outcome (the chased primary locator, or `primary-silent`) |
| **T-LOCAL** | git log/commits/PRs/issues, archived run ledgers, learnings stores, CLAUDE.md, session memory, the project's code/docs | Authoritative for project-scoped claims via reproducible locators (git SHA, path:line, PR#, ledger path; dates from metadata, never invented). Hearsay for world claims — never satisfies a vendor-tier obligation |
| **T-PARAM** | Model parametric memory | Never authoritative; only as the declared final fallback rung below |

**Fallback ladder (when the live source is unreachable)** — the rung is a REQUIRED field on every
externally-sourced row; silent skipping is impossible by construction:

1. `live-fetch` — URL + verbatim quoted span + accessed date (this run).
2. `vendored-docs` — local/vendored vendor docs, man pages, `--help` output: path/command +
   version + quoted span.
3. `cached-copy` — a previously-fetched copy whose locator is VERIFIER-REACHABLE (run dir,
   archived ledgers, repo or installed-dependency paths) + ORIGINAL fetch date + staleness note.
   If the verifier cannot open it, it is not a cached copy — declare `parametric-only`.
4. `parametric-only` — declared model-memory support: labeled `ASSUMPTION:` with blast radius,
   confidence-capped, recorded in `residual_risks[]` when it covers an owed claim, and
   verifier-visible for a next-higher-rung probe. It cannot solely support a claim an acceptance
   criterion depends on UNLESS higher rungs are declared unreachable in the row's ladder fields —
   then the claim's confidence is capped and the gap is a recorded residual risk.

Take the highest reachable rung; each rung is attempted before declaring the next. Stamping a
fresh access date on a cached or remembered source is date fabrication — highest-severity
hallucination (rule 4).

**Claims owed (obligations precede execution):** at briefing time the orchestrator derives the
unit's `claims_owed` entries — each `{id, type, trigger_ref, min_tier}` — from its acceptance
criteria under rules **O1** (external system/vendor/tool named ⇒ a world-fact entry, or an
api-tool-contract entry when the wording is contract-shaped, owed at T-VENDOR), **O2** (file/code
state asserted ⇒ provenance-quote owed at T-LOCAL), **O3** (number/threshold ⇒ measurement owed),
**O4** (causal wording ⇒ toggle reproduction owed). The executor may add claims, never shrink the
owed set. Every owed id must be covered by an evidence row that lists it in `covers_owed`, matches
its type, and satisfies its min_tier (T-VENDOR obligations accept the vendor-silent T-COMM form or
a declared-unreachable parametric row, both confidence-capped; T-LOCAL obligations accept only
reproducible local locators). An empty owed set must say so explicitly, with a reason. Verifiers
re-derive the owed set from the brief via O1–O4 and treat an uncovered, mis-linked, or
under-tiered owed claim as a defect citing that criterion.

## Operating rules

1. **Tag every material claim** with its type and evidence in the debrief evidence table.
   Immaterial asides don't need rows, but anything a downstream unit or the final
   deliverable relies on is material — and every debrief carries **≥1 evidence row**
   (schema `minItems: 1`). A purely mechanical unit's single row records the mechanical
   action itself (e.g. the command run + its exit status), which is its evidence.
2. **Assumptions are labeled, never laundered into facts.** If you must proceed without
   evidence, write "ASSUMPTION:" + why it's reasonable + its blast radius if wrong. The
   verifier **flags** a material unverifiable assumption — in `verify.json` `feedback`/`defects`,
   or a `DISAGREE` verdict when it blocks adjudication — and the **adjudicator/human** decides the
   re-route (a clarification via Phase 2, or a dedicated verification unit, via the Phase-7 rollback
   options). The verifier's job is to refuse to pass it silently, not to pick the re-route.
3. **Cite locators, not vibes.** `file.py:42`, a URL + section, a command + its output, a
   dated measurement. A claim a verifier cannot re-open is not evidence.
4. **Verify before quoting.** Never produce a verbatim quote, citation, API name, config
   key, function signature, or file path you have not confirmed exists. Fabricated
   citations/APIs are the highest-severity hallucination — verifiers hunt these first.
5. **Two sources for contested world-facts.** If a fact could be wrong or is version-
   sensitive, corroborate independently and note the date (facts expire).
6. **Reproduce where feasible — and prefer the reproducible form.** Follow the evidence
   preference ordering above: when a claim *can* be backed by an executable/reproducible signal
   (run the test, diff the output, re-derive the number), that form is required over an asserted
   one; a verifier can regenerate it, and its correctness is model-independent. Reserve asserted
   evidence for claims where reproduction is genuinely infeasible.
7. **Absence of evidence is a finding.** "I could not verify X" is a legitimate, required
   output — surface it, don't paper over it. This is the single most important anti-
   hallucination behavior: say "unknown" out loud.
8. **No laundering through design-judgment.** A judgment row may not embed an unsourced factual
   premise; extract each load-bearing premise as its own typed claim owing its own source tier,
   and list it in the row's `extracted_premises` (an empty list requires an explicit none-reason —
   laundering must be a recorded false "none," never an omission). "Fewer typed claims" must mean
   fewer facts relied on — never less evidence for the same facts.
9. **Cover what you owe, not just what you say.** The brief's `claims_owed` entries are
   obligations: each owed id must be covered by an evidence row that lists it in `covers_owed`,
   matches its type, and satisfies its min_tier or a declared fallback rung. Making fewer claims
   does not shrink the debt, and one row does not discharge two subjects.

## Verifier's evidence checklist (per claim)

- [ ] Claim is tagged with a type.
- [ ] Evidence is admissible for that type (table above).
- [ ] Evidence is in its **most reproducible feasible form** (executable > located > asserted);
      an asserted claim that could have been made executable is down-ranked.
- [ ] Locator is present and resolves (the file/line/URL/command actually exists).
- [ ] For reproducible claims: the verifier reproduced it independently (re-ran + diffed).
- [ ] Quotes/citations/APIs/paths were confirmed real, not plausible.
- [ ] Assumptions are labeled as such and their risk assessed.
- [ ] Any "could not verify" is surfaced, not hidden.
- [ ] Re-open externally-sourced locators — including cache paths: the quoted span exists at the
      locator (citing without reading is the first hunt). Field presence is the validator's job.
- [ ] Every owed id in the brief's `claims_owed` is discharged by its linked `covers_owed` row —
      per entry: does THIS row's subject answer THIS trigger_ref? Re-derive the owed set via
      O1–O4; an uncovered, mis-linked, or under-tiered owed claim is a defect citing that
      criterion.
- [ ] Before accepting a `parametric-only`, `vendor_silent`, or `cached-copy` row, probe one rung
      higher (or open the cache); a reachable higher rung the executor skipped is a defect.
- [ ] Normative vocabulary ("supported", "guaranteed", "contract", "always returns") inside a row
      typed code-behavior or design-judgment is a misclassification defect — retype it as
      api-tool-contract and demand the tier.

A debrief with an unbacked material claim is a **FAIL**, regardless of how plausible the
claim is.
