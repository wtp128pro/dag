# Orchestrator Conduct — depth for the cross-repo rules (lazy-loaded)

This file carries the **reasoning** behind a set of orchestrator rules distilled from three
independent `.dag/learnings` stores (BubbleBrain, music, dag). `SKILL.md` carries at most a
one-or-two-line hook per rule at the moment it binds; the argument, the evidence strength and the
redundancy check live here and cost nothing until the phase arrives.

**Read it once, at the head of Phase 3**, and re-open the relevant section when you hit the decision
moment named in the index. Nothing here is a new invariant, a new state, an edge or a gate — every
item is orchestrator *conduct* at an existing decision point, enforced (if at all) by the ordinary
verifier and adjudicator machinery.

## How to read a rule

Every rule below carries four things, and a rule missing any of them is not a rule:

| Field | What it means | Why it is mandatory |
|---|---|---|
| **Sources** | Qualified lesson ids — `BB-` (BubbleBrain), `MU-` (music), `DAG-` (this repo) | The three stores number **independently**: `BB-L32` is a *different* lesson from `MU-L32`. A bare `L`-number with no store prefix is a defect, not shorthand |
| **Binds at** | The one decision moment where following/ignoring the rule changes the artifact | A rule that binds no moment changes nothing and should be deleted |
| **Strength** | How much of the corpus independently reached it (below) | A rule derived in three repos and a rule from one entry must not read with the same authority |
| **Checked against** | The `file:line` **plus a quoted anchor phrase** in this skill it was tested against, and the verdict | This is what licenses the rule to exist rather than duplicate. The quote is the durable half — see *Locator maintenance* below |

### Locator maintenance — these citations are line-number-coupled (read this before trusting one)

**Every `SKILL.md:NNN` below is coupled to one revision of `SKILL.md` and goes stale the moment
anyone inserts a line above it.** This is a real maintenance obligation, stated here rather than
hidden, because concealing it is exactly the `DAG-L7`/`R16` failure this file also argues against:
it already happened once. The first draft of this file anchored 16 locators against a 956-line
`SKILL.md`; the unit that mounted this file's hook lines then grew `SKILL.md` and **all 16 stopped
resolving** — two of them (the old `:559-561` and `:463-470`) because the insertions landed *inside*
the cited span, so the range matched at no line at all.

Two mitigations are in force:

1. **Citation form: line number + quoted anchor phrase.** Each verdict prints
   `SKILL.md:NNN-MMM` **and** a short distinctive phrase from the cited text. The number is the
   fast path; the **phrase is authoritative**. When they disagree, the phrase wins and the number
   is stale — re-derive it with `grep -n '<phrase>' SKILL.md`. This is deliberate: a bare number
   degrades *silently and wrongly* (it keeps resolving, to whatever text drifted into that
   position), whereas number-plus-phrase degrades to **stale but findable**. A locator that
   resolves to the wrong content is worse than one that resolves nowhere — the reader of a bare
   stale number has no signal that anything moved. (Receipt: the first draft's `R15` locator
   `SKILL.md:620-627` was off by ten lines *before any edit* and pointed at the absolute-paths
   note instead of the adversarial-verify mandate. It read as valid for a whole iteration because
   nothing about a bare range can be falsified without opening the file.)
2. **Redundancy verdicts are pinned to a baseline commit, not to the working tree.** Every verdict
   below answers *"did the shipped skill already say this **before this run touched it**?"* — so
   the reference point is commit **`2dee92a`**, the last commit before this run's edits. This
   matters now: the hook lines this run mounted into `SKILL.md` **state several of these rules
   verbatim**, so a naive grep of the current tree "finds" them and would flip an honest `ABSENT`
   into a false `ALREADY-SAYS-IT`. That is the self-referential-measurement trap `R12` names, one
   file wider than the footer's original `--exclude` guarded against. See the provenance footer for
   the pinned, reproducible form.

**Obligation:** whenever `SKILL.md` changes, re-derive every locator in this file from its anchor
phrase before citing it. `grep -n` on the quoted phrases is the whole procedure.

### Strength tiers — stated honestly, because most of these are thin

| Tier | Meaning | How to treat it |
|---|---|---|
| **T3 — three-store** | Independently derived in all three stores | Follow it; a unit deviating owes a stated reason in its debrief |
| **T2 — two-store** | Derived in two of three | Follow it; the third store's silence is unmeasured, not contrary |
| **T1x — one store, several derivations** | One store, but the same failure recurred there | Follow it *where that store's conditions hold*; ask whether the conditions transfer before generalizing |
| **T1 — single entry** | One lesson, one repo, one incident | A **default with a receipt**, not a law. Deviating is legitimate; deviating *silently* is not — say so in the debrief |

Exactly **one** rule below is T3 (`R1`). **Nine of the eighteen** distilled rules rest on a single
entry. That is a statement about the corpus, not about the rules' importance: the corpus is a record
of failures that happened to be written down, so silence is usually absence of writing, not absence
of the failure. Two consequences: (a) do not cite "the learnings say so" as authority — cite the
tier; (b) a T1 rule whose receipt you can see repeating is the highest-value thing to promote at
Phase 8.

## Index — what binds where

| Rule | Binds at | Strength | Depth |
|---|---|---|---|
| `R16` | Phase 3 cartography of a refresh-over-an-existing-corpus run | T1 (`DAG-L7`) | §1 |
| `R3` | Phase 4 step 1 — atomicity test + `brief.budget_tokens` | T2 (5 derivations, BB+MU) | §2 |
| `R6` | Phase 4 step 4 — critique pass, DoD coverage | T1x (2 × MU) | §2 |
| `R19` | Phase 4 step 4 — critique pass, shared integration points | T1 (`MU-L12`) | §2 |
| `R4` | Phase 5 — writing a context-pointer bullet | T1 (`DAG-L5`) | §3 |
| `R10` | Phase 5 — writing the load-bearing facts a brief quotes | T1 (`BB-L40`) | §3 |
| `R17` | Phase 5 — writing a documentation unit's acceptance criteria | T1 (`MU-L44`) | §3 |
| `R15` | Phase 5/6 — writing the VERIFIER brief for a `validator`/`design`/`formal` unit | T1x (3 × DAG) | §3 |
| `R5` | Phase 6 wave dispatch; Phase 7 repair dispatch | T1x (2 × MU) | §4 |
| `R1` | Phase 6 — after a `debrief.json`+`verify.json` PAIR lands, before `validate_run.sh` | **T3** (7 derivations) | §4 |
| `R8` | Any human-gate message carrying a count (P2 R-CONFIRM, P8 sign-off) | T1 (`BB-L44`) | §5 |
| `R7` | Phase 8 step 3 — sign-off message when a unit did not run | T1 (`BB-L34`) | §6 |
| `R9` | Phase 8 step 4 — promoting learnings to `.dag/learnings/` | T1 (`BB-L33`) | §6 |

Rules that live on other surfaces are routed in §7. Rule id `R2` is **vacant** — a rule shipped
under it in an earlier draft of the intake ledger had no source in the corpus and was retired; the id
is left unfilled rather than reused so old references resolve to the retirement, not to a different
rule.

---

## §1 — Phase 3: cartography

### R16 · Pre-existing debt is a separate line item from the change delta

**Sources:** `DAG-L7` · **Strength:** T1 · **Binds at:** Phase 3 cartography of any run that
refreshes an existing corpus (docs, references, locators, config), **before** the human's scope
decision. · **Checked against:** `SKILL.md:502-505`, anchor *"Map the terrain the task lives in"*
(the Phase-3 opening paragraph) and `references/methodology.md §Cartography` — **ABSENT**; neither
distinguishes debt already in the corpus from drift the current change causes.

A corpus that has drifted for several releases accumulates stale locators *independent of the change
under way*. Cartography naturally measures the delta — that is what the run is about — and folds
whatever pre-existing rot it happens to trip over into the same number. The human then makes a
scope decision (delta-only vs fix-everything) against a size that is wrong in one direction only:
too small.

Conduct: at cartography for a refresh run, run a **whole-corpus** locator existence + spot-resolution
pass, and report **two** numbers — `pre-existing drift` and `delta-caused drift` — as separate line
items. Size the run (units, budget, waves) for both, and put the choice in front of the human with
both figures visible. If pre-existing debt only surfaces mid-run, prefer a **bounded graph amendment**
(`add_units`) over cramming the extra surface into units already briefed for the delta: an amendment
is visible in the ledger; a silently widened unit is not, and it will overrun its budget where the
overrun looks like executor sloppiness.

## §2 — Phase 4: decomposition and the critique pass

### R3 · Budget by evidence-production obligation, not by reading load

**Sources:** `BB-L32` (primary) + `BB-G2`, `BB-L47`, `MU-L14`, `MU-L18` · **Strength:** T2 — five
derivations across **two** stores (3 BB + 2 MU), **zero** dag. (The intake ledger's per-entry note on
`MU-L14` calls this "3/3 repos"; the source list contains no `DAG-` id, so read it as 2/3 — see
§8.) · **Binds at:** Phase 4 step 1, applying the atomicity test and setting `brief.budget_tokens`.
· **Checked against:** `SKILL.md:551-553`, anchor *"a **reasoning/instruction budget, not a data
budget**"*, and `references/methodology.md:190-194`, anchor *"Independently verifiable within
budget"* — **WEAKER**: every
budget framing in the skill is a *reading/context* framing ("a reasoning budget, not a data budget",
"touch bulk data by reference"). `methodology.md:204`, anchor *"If a unit \"does X **and** Y\" → two
units"*, has the split rule only in that generic form.

The unmodelled cost is not what the unit must **read** — it is what the unit must **produce as
evidence**. A unit that must *measure* something and then *write* something has two token sinks: the
measurement (which is unbounded until it is done — the chased dependency, the grep that returns 200
hits, the re-run after the last edit) and the authored artifact. Budgeting the reading load prices
the second and ignores the first, and the failure is quiet: the unit ships the writing and skips or
fakes the measurement, so the run *looks* complete. `MU-L18` extends the same undercount to
read-only investigation units, where the cost is the un-pre-listed dependency chase.

Conduct: price a unit as `reading + evidence production`, and apply the split test in its sharp form —
**a unit that must MEASURE and WRITE is two units**, unless the measurement is a single bounded
command whose output fits in the brief. When you cannot split (the writing needs the measurement in
context), say so in the brief and raise the budget deliberately rather than by hope.

### R6 · DoD coverage must be clause-granular, not item-granular

**Sources:** `MU-L9` (primary) + `MU-L35` · **Strength:** T1x (2 × music) · **Binds at:** Phase 4
step 4 — the critique persona checking DoD coverage. · **Checked against:** `SKILL.md:584-585`,
anchor *"DoD item is covered by ≥1 unit"* —
**WEAKER**: the check is *"every DoD item is covered by ≥1 unit"*, which an item containing "A, B,
**or** C" satisfies while a clause ships nothing.

Definition-of-Done items are written by humans in prose, and prose items contain conjunctions and
disjunctions. Item-granular coverage is satisfied by any unit that plausibly addresses the item's
headline; the sub-clause that no unit owns then disappears between the plan and the sign-off, where
`I23`'s P8 closure check also reads at item granularity and cannot see it. `MU-L35`'s receipt is
the sharper shape: a sub-clause split across an enum-defining unit and a UI-rendering unit shipped as
**dead code**, because each unit was locally correct and no unit owned the concrete case.

Conduct: in the critique pass, decompose each DoD item into its clauses first, then assert coverage
clause by clause and record which unit owns each. A clause with no owner is a graph defect found for
free at Phase 4; found at Phase 8 it costs an amendment or a residual.

### R19 · A shared integration point needs an owning unit — or a cross-unit criterion on every consumer

**Sources:** `MU-L12` · **Strength:** T1 · **Binds at:** Phase 4 step 4 — for any unit whose
deliverable is "add a new consumer of shared state X". · **Checked against:** `SKILL.md:584-585`,
anchor *"DoD item is covered by ≥1 unit"* —
**ABSENT**. (Same paragraph as `R6`, different absence: `R6` is about how finely coverage is checked,
`R19` is about an invariant that *no single unit's* acceptance criteria can express.)

Disjoint-file ownership (`R5`) prevents units from overwriting each other. It does **not** protect an
invariant that only holds across the union of them — a registration list, a shared enum, a
serialization order, a lifecycle contract every consumer must honour. `MU-L12` is explicit that
briefing each unit to touch only its own listed Outputs *"is not sufficient on its own"*, and binds
its own remedy to the Phase-4 critique.

Conduct: at the critique pass, for each unit adding a consumer of shared state X, ask: do this unit's
acceptance criteria re-verify the **cross-unit** invariant X exists to protect, or only this
consumer's local correctness? If only the latter, either (a) give X an owning unit that verifies the
invariant over all consumers, or (b) put the cross-unit criterion on **every** consumer unit —
partial coverage is the worst of the three, since it produces PASSes that read as coverage.

## §3 — Phase 5: briefing

### R4 · A pointer into a file too large to read whole carries a line range or section anchor

**Sources:** `DAG-L5` · **Strength:** T1 · **Binds at:** Phase 5, writing a brief's context-pointer
bullet for a unit that must edit or cite inside a monolithic file. · **Checked against:**
`SKILL.md:647-650`, anchor *"the minimal **context**: pointers (file paths)"* (the minimal-context
bullet) — **ABSENT** *at baseline `2dee92a`*: the bullet asked for paths and inline load-bearing
facts; nothing required a range. **Note the citation is now self-referential** — this run mounted
the `DAG-L5` hook *inside* that same bullet (it is why the old `:559-561` range stopped resolving),
so the current tree does say it. The `ABSENT` verdict is what licensed adding the hook, not a
description of the file after it.

A single-editor unit over a monolithic file cannot fit a plan-side budget if verifying its own
anchors means reading the file: the read alone can exceed the unit's whole allowance, and the unit
then either overruns or inserts against an unverified anchor. This is a **briefing** defect, not an
executor defect, and it is why it is separate from `R3` — no budget number fixes it.

Conduct: a pointer to a file the unit cannot read whole must carry a line range or a section anchor,
and the anchor must be a **paragraph boundary you verified**, quoted in the brief so the executor can
falsify it before editing. Hard-wrapped files make this sharp: an anchor taken from a `grep -n` hit
routinely lands mid-sentence, and an insertion there splits a sentence from its own parenthetical.
When several insertions target one file, brief them in **descending line order** — applying top-down
invalidates every later anchor.

### R10 · The orchestrator may not state an unmeasured mechanism as a premise in a brief

**Sources:** `BB-L40` · **Strength:** T1 — but with the corpus's strongest single receipt: three
briefs, three shipped defects, two of them straight regressions. · **Binds at:** Phase 5, writing the
load-bearing facts a brief quotes inline. · **Checked against:**
`references/evidence-standards.md:99-100`, anchor *"Assumptions are labeled, never laundered into
facts"* (rule 2) — **WEAKER**:
that rule binds the **executor's** debrief. Nothing bars the **orchestrator** from asserting an
unmeasured mechanism in a brief, where it arrives as a contract the executor is told not to
rediscover.

A brief is a contract, and its factual claims are read as settled. When the orchestrator writes
*"the stall is caused by M"* rather than *"a correct fix must achieve O"*, the executor inherits a
diagnosis it was told not to re-derive, and every artifact downstream is conditioned on it. If the
mechanism is wrong, the unit is not merely unhelpful — it is confidently wrong, and the verifier,
seeing brief and debrief agree, has nothing to refute.

Conduct: state the **observable requirement** — a test an outside observer could run against emitted
artifacts, naming no mechanism and no sentence to write. If a mechanism is genuinely load-bearing and
unmeasured, ship it as an explicit `ASSUMPTION:` **to falsify**, with the cheapest falsifying
observation named, never as a premise. Requirements phrased this way also make the guardrail check
mechanical: for each rule the unit proposes, it must name the decision point and the alternative
behaviour foreclosed — a rule with no reachable alternative is not a rule.

### R17 · A documentation unit is a stale-string detector for the code

**Sources:** `MU-L44` · **Strength:** T1 · **Binds at:** Phase 5, writing a documentation unit's
acceptance criteria. · **Checked against:** `SKILL.md:645`, anchor *"objective + acceptance criteria
(verbatim, testable)"* — **ABSENT**: nothing distinguishes a doc unit's two possible responses to a
prose/behaviour mismatch.

A unit told to make prose match behaviour walks the whole surface comparing documented claims against
real ones — the most systematic read of the product anyone in the run performs. It therefore surfaces
**code-side** defects no code unit is looking for. Whether the run gets them depends entirely on the
acceptance criteria: "make the docs accurate" is discharged by silently rewording the doc to match a
bug.

Conduct: a doc unit's criteria must require it to **report** each prose/behaviour mismatch as a
finding — with the locator on both sides and which side it believes is wrong — *and then* fix the
prose. Give it an explicit output slot for those findings so reporting is not scope creep.

### R15 · Validator/enforcement units: enumerate sub-clauses from the SPEC TEXT, never from a fixture name

**Sources:** `DAG-L4` (primary) + `DAG-L8`, `DAG-L11` · **Strength:** T1x — three derivations, all
dag-store, because **only this repo builds validators**; the other stores' silence is
non-evidence here, not disagreement. · **Binds at:** Phase 5/6, writing the **verifier** brief for
any unit tagged `validator` / `design` / `formal`. · **Checked against:** `SKILL.md:776-783`, anchor
*"4. **Adversarially verify** (req 9)"* (the adversarial-verify mandate) — **WEAKER**: the mandate is
claim- and criterion-scoped ("re-check every
claim's evidence… hunt hallucinations and unmet criteria"); nothing directs the verifier to
re-derive the *sub-clause list* of the spec being implemented. (**Corrected locator.** The first
draft cited `SKILL.md:620-627`, which at baseline `2dee92a` was the absolute-paths note plus the
propose/critique and debrief steps — not the verify mandate at all. The verdict was right and the
number was wrong by ten lines from the start; this is the receipt behind the *Locator maintenance*
note's claim that a bare range cannot be falsified without opening the file.)

This is this repo's own recurring failure mode, and it recurs at finer grain each time it is
"fixed". `DAG-L4`: a validator unit under-implements a multi-part spec and self-misfiles the
resulting `REVISES` as `PRESERVES`. `DAG-L8`: a design unit composing a **new** mechanism with an
**existing** invariant gets the corner cells wrong because it worked from the invariant's headline
instead of its text. `DAG-L11`: a block co-developed with its own pinning fixture lets a dropped
sub-clause go unpinned while the suite stays green — the same trap one level down, and evidence the
`DAG-L4` fix did not hold.

Conduct: the verifier brief for such a unit must instruct the verifier to (a) enumerate the spec's
sub-clauses **from the spec text**, never from the fixture names, the test titles or the
implementation's own list; (b) check each sub-clause against the artifact independently; and (c)
re-derive the **composed** corner cells when a new mechanism meets an existing invariant, rather than
trusting either one's headline. A green suite co-authored with the thing it pins is exactly the
mechanism that could not have produced a different answer.

## §4 — Phase 6: dispatch and execution (and Phase 7 repairs)

### R5 · Shared-tree concurrency

**Sources:** `MU-L25` (primary), `MU-L40` · **Strength:** T1x (2 × music) · **Binds at:** dispatching
a wave (Phase 6 head); dispatching a repair between adjudications (Phase 7). · **Checked against:**
`SKILL.md:227-228`, anchor *"executors with `isolation: 'worktree'` (Agent tool)"* — **WEAKER**:
worktree isolation is *"consider"*-ed and only for **executors**; `SKILL.md:704-705`, anchor
*"Process waves in topological order"*, states wave parallelism with no shared-tree caveat at all;
`SKILL.md:959-968`, anchor *"**Frozen executed prefix (I17) — the load-bearing rule.**"*, freezes
**graph** mutation during execution but says nothing about dispatching work onto artifacts under
adjudication.

Three distinct hazards, one rule:

1. **Same-wave units must own disjoint files.** Two units editing one file in parallel produce a
   last-writer-wins artifact whose loser's verify still PASSes against a file that no longer contains
   its work.
2. **No evidence-reproducing verifier concurrent with a tree-mutating executor.** A verifier's core
   move is to re-run the executor's evidence. If the tree changes underneath, its re-run measures a
   different artifact than the one it is adjudicating — and the failure is invisible, because both
   sides produce plausible output. (`R18`'s content digests exist to make exactly this detectable
   after the fact; see §7.)
3. **No repair dispatched while a verification is in flight.** The repair mutates the artifacts the
   in-flight verify is reading, so its verdict adjudicates a mixture of two states.

Conduct: partition each wave by file ownership before dispatch and state the partition; keep
verify-with-reproduction serialized against mutation; and hold repairs until the outstanding
adjudication lands. Where the harness offers it, `isolation: 'worktree'` removes hazard 1 for
executors but not hazards 2–3, which are ordering constraints, not isolation ones.

### R1 · Run the offline artifact normalizer before the validator

**Sources:** `BB-L26` (primary), `DAG-L2`, `MU-L32` + `BB-L8`, `DAG-L6`, `MU-L15`, `MU-L34` ·
**Strength:** **T3 — the only rule in this file independently derived in all three stores**, seven
derivations. · **Binds at:** after a unit's `debrief.json`+`verify.json` **pair** lands and **before**
`validate_run.sh` runs on that pair. · **Checked against:** `SKILL.md:173-179`, anchor *"In Phase 6,
\"each artifact\" means each unit's `debrief.json`+`verify.json` PAIR"* (the pair-cadence paragraph),
and `SKILL.md:769`, anchor *"quote it (expanded) rather than paraphrase"* — **the "quote the exact
shape, don't paraphrase" half is ALREADY-SAYS-IT**; the normalizer half is **ABSENT** at baseline
`2dee92a`. The existing text names the drift and its compounding, then prescribes only earlier
validation.

The empirical claim all three stores reached independently is precise: **quoting the required shape
into the brief is necessary but not sufficient.** Drift recurs across most units of a wave *even
when the shape is spelled out inline* (`DAG-L6`), and it concentrates in **nested required key
names** when the shape is described in prose (`DAG-L2`). The drift set is enumerable and small —
enum casing, severity synonyms, natural field names for schema keys, string-where-array, nested
sub-object shapes (`BB-L26`, `MU-L15`, `MU-L34`). music's receipt: an orchestrator-side normalizer
run after each wave's verifies land and before validation turned **~150 schema FAILs into 0 without
changing a single PASS/FAIL verdict** (`MU-L32`).

Conduct: between the pair landing and `validate_run.sh`, run the **offline, idempotent,
non-gating** normalizer over the run dir's artifacts, then validate. Three properties are
load-bearing and must not be traded away:

- **Offline and non-gating.** It rewrites artifacts; it never blocks a transition, and it is never
  the thing that decides a verdict. If normalization and adjudication can disagree, adjudication wins.
- **Verdict-preserving.** It coerces *shape*, never content: a `PASS`/`FAIL`, a defect's severity
  meaning, a count or a claim must be byte-equivalent in meaning before and after. A normalizer that
  can change a verdict is a second, unreviewed adjudicator.
- **Idempotent.** Running it twice equals running it once, so a re-validate after a retry is safe.

Everything it fixes is drift a human would have called obvious; the reason it earns machinery is that
the cost is *silent compounding* — deferred to the wave's end, the same defect must be repaired in a
dozen units at once.

## §5 — Any phase: human-gate messages

### R8 · No count in a human-gate message without its counting rule

**Sources:** `BB-L44` · **Strength:** T1 — with a **live receipt from this run** (below).
· **Binds at:** rendering any human-gate message carrying a tally or an exhaustive-sounding count
(P2 R-CONFIRM, P8 sign-off). · **Checked against:** `references/evidence-standards.md:38`, anchor
*"**Numeric/quantitative**"* — **ALREADY-SAYS-IT for evidence-table rows** (a numeric claim owes "the
measurement + how it was produced"); `SKILL.md:491`, anchor *"`resolution_source` tally"* —
**WEAKER**: it mandates a gate-message tally and requires no derivation for it.

The evidence rules bind debriefs, which verifiers read adversarially. Gate messages bind **humans**,
who read them once, under time pressure, with no artifact to re-run — and a human "yes" at a gate is
the strongest authority in the pipeline. A wrong number therefore propagates *further* from a gate
than from a debrief, past the one reader who cannot check it.

Receipt, from this run: a human-confirmed DoD item asserted a store-size tally of **34/50/10** against
an actual **33/49/10**. The count was wrong, the gate passed, and it took a later unit re-running
`ls -1 <store>/*.json | wc -l` to catch it — precisely because no derivation had been required of it.

Conduct: any count in a gate message carries the rule that produced it — the command, or one clause
naming what was counted and over what set ("`*.json` files in each store, per `ls -1 … | wc -l`").
The same applies to exhaustiveness words: "all", "every", "the only" are counts in disguise, and owe
the same one clause. Re-run the derivation **after** the last edit to the thing being counted, not
before — a figure computed before your own final edit is the classic form of this defect, and this
rule's own ledger committed it twice.

## §6 — Phase 8: sign-off and promotion

### R7 · A unit that did not run leaves its DoD items UNDISCHARGED, named at sign-off

**Sources:** `BB-L34` · **Strength:** T1 · **Binds at:** Phase 8 step 3, assembling the sign-off gate
message when any unit was skipped, blocked or never dispatched. · **Checked against:**
`SKILL.md:1039-1042`, anchor *"**Mechanical counterpart (I23):** at P8/DONE"* — **WEAKER**: closure is enforced only at
P8/DONE and only as "referenced by no PASS-verified unit"; nothing names a skipped unit's items
**undischarged at skip time**, and nothing forces that word into the human's message.

A run with one unrun unit and everything else green reads, in a sign-off message, as whole-task
confirmation. The bias is systematic and it points one way: the unit that gets skipped is
disproportionately the **empirical** one — the measurement, the live reproduction, the
environment-dependent check — because that is the unit most likely to be blocked. So the surviving
PASSes are exactly the least conclusive evidence the run could have produced, presented as its
conclusion.

Conduct: when a unit does not run, mark its DoD items **UNDISCHARGED** at that moment, carry the word
into the sign-off gate message next to the items themselves, and state which *kind* of evidence went
missing with it. "Unit U0x was skipped" is a status line the human skims; "DoD item 4 is UNDISCHARGED
— the only unit that would have measured it did not run" is a decision.

### R9 · Promotion is write AND land

**Sources:** `BB-L33` · **Strength:** T1 · **Binds at:** Phase 8 step 4, writing promotable learnings
into `.dag/learnings/`. · **Checked against:** `SKILL.md:1108-1114`, anchor *"**Promote durable
LEARNINGS → persist (03/P2 write end).**"* — **ABSENT** at baseline `2dee92a`: the step specified
the write and stopped.

Phase 0.5 intake reads the **working tree**, so a promoted learning that was written but never
committed is visible to the next run *in this working tree* and to nobody else. It looks like it
worked, for exactly the person who can't tell. The failure is silent and total: the learning is not
degraded, it is absent for every other clone, worktree and future session — which is the entire
point of promoting it.

Conduct: after writing the store files, check that they are **tracked and committed** — `git
ls-files <store path>` / `git status --porcelain <store path>` — and report the promotion as
**UNLANDED** in the sign-off message until it is. In a repo whose policy routes every change through
a PR, "landed" means the commit exists on a branch that is going to the PR, and the sign-off says so;
never quietly commit to a protected branch to make this rule green.

## §7 — Rules that live on other surfaces

These are part of the same intake and are recorded here **for routing only** — their depth belongs to
the surface that owns them, and duplicating it here would be the bloat this file exists to avoid.

| Rule | Home surface | Binds at | Sources · strength |
|---|---|---|---|
| `R11` — an evidence artifact is admissible only if its producing mechanism **could have produced a different answer** | `references/evidence-standards.md` (core rules) | An executor choosing the command that will serve as evidence; a verifier adjudicating that row | 9 derivations across **two** stores (3 BB + 6 MU, zero dag) · T2 — the corpus's largest cluster |
| `R12` — self-referential claim row: claims about your OWN artifact | `references/evidence-standards.md` (claim taxonomy) | Writing an evidence row whose subject is this unit's own artifact — a tally, "I removed X", "the only Y is Z", a ledger timestamp | `BB-L49` + `DAG-L3` · T2 |
| `R13` — sweep/audit axis independence + variant enumeration | `references/evidence-standards.md` | Writing a sweep/audit/rename unit's criteria; the verifier checking its axis list | `BB-L42` + `MU-L13`, `MU-L38`, `MU-L39`, `MU-L43` · T2 |
| `R14` — before/after symmetry; a regression test must be shown FAILING pre-fix | `references/evidence-standards.md` | Adjudicating any "fixed" / "improved" / "no longer happens" claim | `BB-L48` + `BB-L23`, `MU-L45` · T2 |
| `R18` — give the verifier **content digests**, not just paths | `templates/verify.md` (`inputs_reviewed[]` rows carry a sha256) | The verifier recording what it read; detecting that an artifact moved under a running verification (`R5` hazard 2) | `BB-L46` · T1 |

## §8 — Carried, not resolved

Three items the intake deliberately did not turn into rules. They are recorded so a later run finds
them instead of re-deriving them:

- **Budget-ceiling revision (`BB-L50`).** The conclusion — raise a unit's budget ceiling above 32,000
  — **REVISES** the atomicity argument at `SKILL.md:549-556`, anchor *"Adopt the
  **Planner/Architect** persona"* (Phase 4 step 1), rather than adding to it, and a revision
  owes a migration argument no unit has yet owned. Carried as a residual, not as conduct.
- **Disagreement adjudication over a vendor string (`BB-L28`, second half).** When two agents disagree
  on a vendor string, do not adjudicate on authority or seniority: have a third party re-fetch and
  compare ETags, then look for a page revision that explains **both** readings — a revision is more
  likely than either party being careless. Nothing in this skill says this; its natural home is
  `references/evidence-standards.md`'s adjudication guidance, unowned this run.
- **`R3`'s store span — a ledger defect this file does NOT inherit.** The intake ledger's `MU-L14`
  rationale reads *"Raises `R3`'s derivation count to 3/3 repos"*, but `R3`'s own source list in
  `artifacts/dispositions.json` is `['BB-G2','BB-L32','BB-L47','MU-L14','MU-L18']` — **3 BB + 2 MU +
  0 dag**, i.e. **2/3 repos**, re-confirmed by `collections.Counter` over the source prefixes at this
  iteration. `R3` is therefore graded **T2** here and in the §Index table (*"T2 (5 derivations,
  BB+MU)"*), never T3; nothing in this file was graded off the ledger's "3/3" string. Read `R3` at T2
  until a dag-store derivation exists. **The ledger entry itself is still wrong and is not this
  file's to fix** — it is carried to the adjudicator as a ledger correction, the same class as the
  `R11` "all three repos" error an earlier ledger iteration already had to correct.

---

**Provenance of the "checked against" column.** Every `file:line` above was re-opened at this
iteration and confirmed to contain the text its anchor phrase quotes; the 17 `SKILL.md` locators were
re-derived from their anchor phrases against a `SKILL.md` of **1201 lines** (`wc -l`, run twice with
an identical result to confirm the file was not mid-edit). The four **ABSENT** verdicts rest on a
search rather than on a weaker sentence.

**Pin the search to the baseline commit.** Each was measured from `plugins/dag/skills/dag/` with

```
git grep -nEiI '<pattern>' 2dee92a -- SKILL.md references templates
```

where `2dee92a` is the last commit **before this run's edits**. The pin replaces the earlier
`grep -rniI --exclude=orchestrator-conduct.md …` form and is strictly more robust:

| verdict | pattern | hits at `2dee92a` | hits in the CURRENT tree |
|---|---|---|---|
| `R4` | `line range\|section anchor\|line-range` | 0 | **2** — `SKILL.md:649-650`, anchor *"MUST carry a line range or"*: the `DAG-L5` hook **this run mounted** |
| `R16` | `pre-existing\|preexisting` | 4 — all unrelated (`formal-models.md:379`, `self-learning-loops.md:182`, `state-machine.md:207`, `:208`), each the phrase *"a pre-existing gap"* about a validator invariant, none about counting corpus debt at cartography | 4 — the same four lines, unchanged |
| `R17` | `stale string\|stale-string\|silently reword` | 0 | 0 |
| `R19` | `integration point\|shared state\|owning unit` | 0 | **1** — `state-machine.md:230`, matching *"owning unit"* inside the new `I42` digest-integrity row (`R18`/`BB-L46`), unrelated to a shared integration point |

Why the pin, and why `--exclude` was not enough. The original command excluded only **this** file,
which was correct when this file was the only new text containing the patterns. It is no longer:
the run has since mounted rule hooks into `SKILL.md` and a new invariant row into
`state-machine.md`, so two of the four patterns now match **because the run acted on the verdict**.
An un-pinned re-run would report the rules as already-present and retire them — a verdict deleting
its own cause. Pinning to the pre-run commit asks the only question the verdict was ever about
(*did the skill already say this before we touched it?*), needs no `--exclude` at all (this file is
untracked and absent from the commit), and cannot rot as the working tree moves. A verdict is only
as current as the tree it was run against: re-run the pinned form, and re-derive every locator from
its anchor phrase (see *Locator maintenance*), before trusting any rule's right to exist.
