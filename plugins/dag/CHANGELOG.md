# Changelog — dag plugin

All notable changes to the `dag` plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-07-05

### Added
- **Bounded self-learning-loop layer (rings 02/03/04)** — all additive and **post-hoc**
  (offline validator predicates only; nothing gates the FSM, so termination is preserved):
  - **Post-hoc AO-2 / AO-6 checks (`I14` / `I15`)** — on a retry (`debrief.iteration > 1`),
    `I14` verifies the new verify's `defects[].criterion` are disjoint from the prior
    iteration's `do_not_touch`, and `I15` requires a responsive `changes_made`. Both are
    **presence-gated and read from the debrief's self-reported `prior_feedback` echo** (the
    validator retains only the latest `verify.json`) — a documented Named Limitation, not full
    AO-2/AO-6 enforcement.
  - **Across-run learnings stores** — a **project** store (`.dag/learnings/*.json`) and a
    **user** store (`~/.claude/dag/learnings/*.json`), merged at intake with **override order
    project > user**, plus an **expiry** grammar (`run | project | runs:N | date:<iso>`,
    loader-side), **idle decay / GC** (archive-not-delete; decidable for `max_idle_runs == 0`),
    and **supersedes / contradiction** escalation (advisory NOTE).
  - **Global tag registry (`04/G1`, flagged)** — widens the `I11`/`I12` tag domain to
    `V_tag_eff = global ∪ project ∪ run-local` via `~/.claude/dag/tags.json`, with the
    **authored-vs-imported admission carve-out** and an explicit provenance-trust boundary
    (a domain revision of `I11`/`I12`, not a purely additive check).
  - **`scope.model` narrowing (`04/G4`)** — an optional per-entry model glob/prefix that
    narrows `I12` propagation to matching runs.
  - **Advisory principles-promotion NOTE (`04/G3`)** — surfaces promotable entries for
    **human** promotion to `~/.claude/dag/principles.md`; never auto-writes, never gates.
  - **Advisory tier for imported cross-run learnings (`03/P4`)** — imported entries are
    **advisory** (loaded, reported, voluntarily citable, **not** force-injected by `I12`) until
    **re-grounded** to a local signal via the optional entry-level `grounding: "re-grounded"`
    marker; re-grounded imports and all run-local authored entries stay **active** and
    `I12`-enforced (preserves AO-4).
  - Supporting prose in `SKILL.md` (Phase 0.5 learnings intake, Phase-6 in-run capture /
    per-tag panel escalation / guarded forward re-brief, Phase-8 promote→persist write) and the
    `references/` self-learning / state-machine / methodology docs, plus new validator test
    fixtures. Ring 05 (sharable / trust) is **not** included in this release.

## [1.0.1] — 2026-07-05

### Changed
- Paraphrased the expressive third-party **blog quotations** in the persona catalog
  (Martin Fowler's *TestPyramid* and *Eradicating Non-Determinism in Tests*, the Testing Library
  guiding principle, and Unosquare / em-tools.io T-shaped-engineer commentary) into original
  wording, with their attributions preserved. The factual certification-body, standards-body,
  official-doc, and job-posting quotes are unchanged (fair-use quotation). No behavior change.

### Added
- Plugin README: an **MIT license** line and a **"Verify the formal claims yourself"** section —
  the one-command TLC re-run (expect 327 distinct states, no error) with a pointer to
  `references/formal-models.md` for the full transcript and the Alloy models.

## [1.0.0] — 2026-07-05

### Added
- Initial release of the `dag` gated, multi-phase task-execution pipeline:
  - **Socratic persona selection** (Phase 1) from a curated per-file JSON catalog plus
    user (`~/.claude/dag/personas/`) and project (`.dag/personas/`) personas, all under one
    uniform `persona.schema.json`.
  - **Exhaustive clarification** (Phase 2) with a materiality-ranked ambiguity register and a
    mandatory Definition of Done + Non-Goals/Guardrails.
  - **Contextual cartography** (Phase 3), **atomic work-unit decomposition + dependency DAG**
    (Phase 4), and **self-contained per-unit briefings** (Phase 5).
  - **Budget-capped subagent executors** (propose/critique) with **independent adversarial
    verification** of every work unit (Phase 6), a **disagreement gate** (Phase 7), and
    **synthesis + sign-off** (Phase 8).
  - **Formally-enforced invariants** — JSON Schemas + a finite-state-machine spec + a runnable
    validator (`scripts/validate_run.py`) that mechanically rejects malformed runs, plus a
    **TLA+/Alloy formal-model layer** (TLA+ machine-checked with TLC; Alloy hand-proved).
  - **Adaptive anti-hallucination evidence standards** and a durable
    plan/decision/progress/learnings ledger.
- Companion **`dag:personas`** skill to list/add/modify/remove reusable persona JSON files
  across the project, user, and built-in catalog sources.
