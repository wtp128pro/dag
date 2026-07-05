# Methodology — how each phase actually works

This file is the "why and how" behind SKILL.md. Read the section for the phase you are
in. Everything here serves three goals: **verified correctness, zero hallucination, and
no rediscovery.**

---

## §Socratic — the dialogue discipline (all prompts: human gates + subagent self-interrogation)

One shared move-set — **FORK · COUNTER · ADMIT · PIVOT · RESIDUAL** — lives in
[references/socratic-protocol.md](socratic-protocol.md), in two modes: **elicitation** (the
human gates, Phases 1/2/7/8) and **self-interrogation** (subagent briefs — executor,
verifier, cartographer, planner — run *before* producing output). Cite it by **one line per
prompt**; never copy it in. The dialogue is free-form prose; only its *result* is captured
in the small `socratic` block (§the field, in the protocol file).

A Socratic gate is **not** a menu. It is a structured elicitation that makes the user's
implicit knowledge and preferences explicit *before* they become expensive to change.

Principles:
- **Selective, not ritual.** Open a gate / run a self-interrogation pass **only** on a
  *material* surface (a wrong answer changes the deliverable or is hard to reverse) or a
  *detected* ambiguity — never as a fixed ceremony. Indiscriminate questioning is theater
  that burns budget without gain.
- **Decoupled.** Verification questions are answered *independently of the artifact under
  test* — from source/test/first principles, not by re-reading and rationalizing the draft.
  Joint verification reinforces errors; this is why the verifier re-runs COUNTER
  from evidence rather than reading the executor's reasoning.
- **Surface the fork, not just the options.** State the tradeoff each choice implies and
  what becomes hard to reverse later. ("If we treat X as out of scope, the verifier
  cannot later flag X gaps — confirm that's intended.")
- **Recommend, then ask.** Always mark your best-supported proposal and say *why*. The
  user should be able to accept your recommendation with one click, or override.
- **One decision per question.** Keep `AskUserQuestion` items atomic and ≤4 per batch;
  loop for more. Never bundle unrelated decisions into one option list.
- **Elicit, don't lead.** Ask what the user is optimizing for and what they fear, not
  only which option they prefer. Their fear often reveals the real acceptance criterion.
- **Log the answer as a decision** immediately (DECISIONS.md), including the alternatives
  rejected, so no later phase reopens a settled question.

When to open a gate: persona selection, material clarifications, material disagreements,
final sign-off. When *not* to: anything with a safe default and low reversibility cost —
choose, log, move on.

---

## §Personas — propose/critique staffing (Phase 1)

Why personas: a single undifferentiated "assistant" voice averages its judgments and
hides its blind spots. Named personas force *distinct* optimization targets and make
disagreement visible and productive.

- **Hybrid sourcing.** Start from the curated catalog — read the selection index
  `references/personas/index.json` and open individual `references/personas/<name>.json` only for
  serious candidates — then synthesize task-specific personas the library lacks. Name them
  concretely ("Postgres Locking Expert", not "Database Person").
- **Extensible JSON personas (user-supplied).** The library is extensible without touching
  the skill: before presenting the roster, Phase 1 discovers every `*.json` at two paths —
  project `.dag/personas/*.json` and user `~/.claude/dag/personas/*.json` —
  and merges them into the candidate pool. Each file is one persona validated by the SAME
  `schemas/persona.schema.json` the curated catalog uses: **required** `name`, `role`,
  `description` (non-empty strings); **optional** `mandate`, `optimizes_for`, `skeptical_of`,
  `phase`, `pair_with` (strings), `qualifications` and `tags` (string arrays) — one uniform
  field set across curated entries, `templates/persona.json`, and user/project files. The pool
  is the **union** of {curated catalog, discovered project + user JSON, synthesized personas};
  on a **name collision** the more specific source wins — **override order: project > user >
  curated**. There is **no loader script** (Dag reads the files in Phase 1), and this INPUT
  path does not change what the run validator requires — `persona.schema.json` is meta-validated
  by `--self-check` but is not a run artifact. Full convention: references/personas/GUIDE.md
  §Extending the library.
- **Propose ↔ critique pairing.** For every persona that *produces* a consequential
  artifact, assign a persona that *attacks* it. The critic optimizes for a different
  thing than the proposer (e.g., proposer = "ship the simplest correct change";
  critic = "find the input that breaks it").
- **Mandate, not vibes.** Each persona gets: role, mandate (the decision it owns),
  what it optimizes for, what it is skeptical of, and its phase/unit assignments.
- **Independence for verification.** The Adversarial Verifier persona must be able to
  reach the *opposite* conclusion from the executor without penalty; never staff it as
  a rubber stamp.

---

## §Clarification — eliminating material lapses (Phase 2)

The ambiguity register is a table, not prose. For each item capture: the ambiguity, why
it matters, the candidate interpretations, the **materiality** (does a wrong guess change
the deliverable?), and the resolution (user answer or logged default).

Checklist of where lapses hide:
- **Terms** used as if defined but aren't ("real-time", "secure", "done", "large").
- **Success criteria** — how will we *know* it worked? What is the acceptance test?
- **Scope boundaries** — what is explicitly OUT? Absent boundaries cause scope creep.
- **Audience & format** — who consumes the output, in what form, at what depth?
- **Constraints** — time, budget, tools, environment, compliance, style.
- **Assumptions** — anything you're about to take for granted. Name it; verify or ask.
- **Failure modes** — what must *not* happen? These often encode the true priorities.

Materiality is the filter that keeps this from becoming interrogation. Only *material*
ambiguities reach the user; the rest get logged defaults.

**Two outputs are mandatory, not optional (MUST).** Beyond the register, Phase 2 always
produces a **Definition of Done** — a testable exit checklist — and a **Non-Goals /
Guardrails** list — an explicit "do NOT build / out-of-scope / no gold-plating" enumeration.
You may right-size their *contents* to the task, but never their *presence*. And strengthen
input-gap coverage: a resolution that names what to build but not what to steer clear of is
not resolved — cover both the what-to-do and the what-to-avoid for every material gap.

**These are mechanically enforced in two layers**, so this is not advice you can skip. The
schema fields are `definition_of_done` and `non_goals` (both required, non-empty). (L1) a
present `clarifications.json` missing or emptying either field hard-fails the schema; (L2)
the validator's `I-dod` check fires as soon as a run has ANY post-clarification structural
artifact (cartography, graph, units, or synthesis) and then demands a schema-valid
`clarifications.json` with non-empty `definition_of_done` AND `non_goals`, even if the file is
absent — so deleting one artifact does not dodge it (the trigger is the union of
cartography / graph / units / synthesis; the `learnings.json` ledger sidecar is deliberately
excluded — it can stand alone and, in a real run, only appears alongside those structural artifacts).

These concepts thread forward: in Phase 4 each unit's acceptance criteria trace to a DoD item
and each unit carries its slice of the Non-Goals as explicit guardrails; in Phases 6 and 8 the
checker confirms every DoD item is met and no non-goal was delivered (§Verification).

---

## §Cartography — contextual vs mechanical mapping (Phase 3)

**Mechanical** cartography enumerates: "here are the 214 files / 30 sources / 12
systems." It is nearly useless because it conveys no meaning and blows the budget.

**Contextual** cartography answers questions:
- What is the *shape* of this terrain — the few structures that organize everything else?
- What matters **for this task**, and why? (Relevance is defined by the objective.)
- How do the relevant pieces **relate** — dependencies, data flows, contracts, ownership?
- Where are the **risks, unknowns, and invariants** — the things that will bite?
- What is **authoritative** here — which source/test/doc is ground truth vs. hearsay?

Produce a map a newcomer could use to *act*, not just to locate. Prefer annotated
structure ("AuthService owns token issuance; everything downstream trusts its `verify()`;
the invariant is tokens are never logged") over inventories. Explicitly mark **unknowns**
— each becomes a clarification (Phase 2) or a work unit (Phase 4). Use a second lens
(different persona) when the terrain is contested or unfamiliar.

For non-code tasks the terrain differs but the discipline is identical: research → the
landscape of credible sources, prior art, open questions, and who disagrees with whom;
operations → systems, dependencies, and blast radius; writing → audience, prior art,
argument structure, and the claims that need support.

---

## §Decomposition — atomicity and the DAG (Phase 4)

An **atomic** work unit satisfies all of:
1. **Single responsibility** — one clearly-stated goal, one owner persona.
2. **Independently verifiable** — a verifier can judge it PASS/FAIL from its brief +
   artifacts alone, without running the rest of the task.
3. **Budget-fit** — its entire required context (brief + the files it must read) fits
   comfortably under 32K tokens. If not, split it.

Right-sizing heuristics:
- If a unit's brief would need to quote more than a few files' worth of context → split.
- If a unit "does X **and** Y" → two units (unless Y is trivially entailed by X).
- If two units always fail/pass together → maybe they're one unit.
- Prefer more, smaller units: they verify better and parallelize better. The cost is
  coordination, which the DAG + briefs absorb.

**Dependency graph:** an edge A→B means B consumes A's outputs (or A must hold for B to
be valid). The graph must be acyclic. Topologically sort into **waves**: wave *k* = all
units whose dependencies are all in waves < *k*. Units in a wave are mutually independent
and run in parallel. A critique pass validates: no cycles, no missing edges (a unit that
secretly needs another's output), no unit over budget.

---

## §Briefing — the self-contained contract (Phase 5)

The brief is the *only* channel into the executor's isolated context. Design it so the
executor needs zero rediscovery and stays under budget.

- **Include the load-bearing facts inline** (the 3–10 decisions/values the unit truly
  needs), quoted from the ledger so the executor doesn't re-derive them.
- **Point to everything else by path** ("read `units/U03/debrief.json` → `result`/`handoff_notes`"), and tell
  the executor to read *only* those. This is how budget is held.
- **State acceptance criteria verbatim and testable.** The executor and the verifier must
  read the *same* criteria.
- **Name the evidence standard** for this unit's claim types (evidence-standards.md).
- **Attach the debrief schema** so the output is machine-consumable up the line.

A good brief is falsifiable: a stranger could execute it and a different stranger could
verify the result, neither needing you.

---

## §Verification — decoupling the maker from the checker (Phase 6)

The central idea (articulated by Boris Cherny, co-creator of Claude Code, in his talks on
agent/verification loops — the exact term "self-learning loops" is not in the official
docs, but the *practice* is well attested): **a single model instance that both makes and
checks its own work suffers confirmation bias.** So the checker must be a *separate*
instance that is *incentivized to refute*.

Rules for the adversarial verifier:
- **Independence of context.** The verifier receives the brief, the debrief, and the
  artifacts — **not** the executor's reasoning/chain of thought. It forms its own view.
- **Refutation mandate.** Its job is to *break* the result: find the counterexample, the
  unmet criterion, the unsupported claim, the hallucinated citation, the budget breach.
  A verifier that only confirms is malfunctioning.
- **Guardrail compliance.** The verifier confirms the unit delivered **no out-of-scope or
  gold-plated work**: every artifact traces to an acceptance criterion (which in turn traces
  to a Definition-of-Done item), and nothing on the unit's Non-Goals / guardrails list was
  built. A delivered non-goal is a FAIL, not a bonus — scope creep is a defect the checker
  must catch, the same as an unmet criterion. The Phase 8 sign-off applies this same check at
  task scope: every DoD item met, no non-goal shipped.
- **Evidence re-check.** For each claim in the debrief's evidence table, the verifier
  independently confirms the evidence is real and admissible (evidence-standards.md). It
  reproduces results where feasible (run the test, open the cited page, re-derive the
  number).
- **Verdict.** `PASS` (criteria met, evidence sound), `FAIL` (specific defect + minimal
  repro), or `DISAGREE` (a genuine judgment split with no objective resolution → Phase 7).
- **Panels for high stakes.** For irreversible or high-cost units, run an **odd panel**
  (3) of verifiers with *different lenses* (correctness / adversarial-input / does-it-
  actually-reproduce) and take the majority. Diversity beats redundancy — three identical
  skeptics find less than three differently-motivated ones.

---

## §Self-learning loops — used wisely (Phase 6, req 12)

> **Contract of record:** the loops below are formalized as a bounded state machine with a
> checkable termination argument, a verdict/feedback JSON contract, a `LEARNINGS` entry
> schema, and anti-oscillation invariants AO-1…AO-7 in
> [references/self-learning-loops.md](self-learning-loops.md). This section is the *why*;
> that file is the *what* the validator enforces.

Two loop types, both bounded:

1. **Correction loop (within a unit).** verifier FAIL → feed the specific findings back
   → re-execute → re-verify. **Cap at 2 retries.** If it still fails, it is a
   disagreement (Phase 7), not an infinite loop. Log every iteration in PROGRESS.md.
2. **Learning loop (across units).** When a mistake is *generalizable* (would recur in
   other units), write it to LEARNINGS.md and **inject it into subsequent briefs**. This
   is the durable feedback system: the pipeline gets smarter as it runs, and — if
   promoted at sign-off — across future runs (e.g., into `CLAUDE.md` or a skill).

"Wisely" means: only capture *generalizable* lessons (one-off facts stay in the unit
debrief); never let a loop re-open a human-decided gate; never re-verify a passed claim in
a way that can oscillate; always bound iteration.

---

## §Evidence & anti-hallucination

See the dedicated rulebook: [evidence-standards.md](evidence-standards.md). Summary: every
material claim is tagged by type and must carry evidence *admissible for that type*;
claims that can't be backed are marked as assumptions and either verified or surfaced as
clarifications — never asserted as fact.

---

## §Hard-won principles (baked-in learnings)

These are durable, generalizable lessons — several grounded in 2023–2026 research, several
learned the hard way when an adversarial verifier broke a plausible-looking artifact. Injected
here so every future run inherits them. Apply them in the phase noted.

1. **Decouple the maker from the checker.** The verifier is a *different* persona (ideally a
   different model) with authorship neutralized; LLM judges provably favor their own outputs
   (self-preference tied to self-recognition, persists even when authorship is hidden). *(§Verification;
   arXiv:2410.21819, NeurIPS'24 2404.13076.)*
2. **Ground every correctness gate in an EXTERNAL signal** — a test, tool output, an independent
   verifier, a rubric — never the model re-reading its own reasoning (intrinsic self-correction of
   reasoning is unreliable and can *degrade* output). *(§Verification, §Self-learning; arXiv:2310.01798.)*
3. **Structure the plumbing, not the reasoning.** Let agents reason free-form, THEN extract the
   machine-checkable artifact; a schema guarantees valid *structure*, not correct *content*
   (validity ≠ correctness). Never force the reasoning itself into a rigid format. *(§Briefing, §Socratic;
   arXiv:2501.10868, arXiv:2408.02442 vs blog.dottxt.ai/say-what-you-mean.html.)*
4. **Socratic questioning is selective and decoupled, never ritual.** Trigger on a material surface
   or a detected ambiguity; answer verification questions independently of the draft. Indiscriminate
   questioning is theater that burns budget. *(§Socratic; arXiv:2309.11495, arXiv:2409.00557.)*
5. **Fan-out earns its ~4–15× token cost only for high-value, decomposable, parallel work**; most
   multi-agent failures are architectural, not model quality. Spend effort on typed specs, persisted
   ledger state, explicit termination conditions, and a separate verification stage. *(§Decomposition;
   anthropic.com/engineering/multi-agent-research-system, arXiv:2503.13657.)*
6. **A self-check must confirm the PREMISE is the load-bearing claim** before hunting a
   counterexample — otherwise "premise deflection" (examine a safe premise, ignore the real one)
   defeats it. The independent verifier confirms the premise, then re-runs COUNTER from evidence.
   *(§Socratic, §Verification.)*
7. **Absence is an attack surface.** A validator that only checks the artifacts that happen to be
   *present* will pass an incomplete run. Enforce required-artifact presence and fail *closed* on
   unparseable/empty inputs — do not silently pass them. *(§Verification; the validator's I3/I9/I10.)*
8. **Test the unhappy paths the system is meant to ENFORCE.** A happy-path-only fixture set hides
   seam bugs — e.g. a schema that rejects a *legitimate* FAIL, which would make the correction loop
   un-runnable. Keep a fixture per reachable state (good, malformed, missing-artifact, cycle, and a
   real FAIL/RETRY). *(§Self-learning; the validator's `tests/` fixtures.)*
