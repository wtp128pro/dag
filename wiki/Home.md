# dag — the wiki

**Audience:** anyone who wants to understand what `dag` is and how it earns trust — from the curious newcomer to the person about to change its formal machinery.

**TL;DR.** `dag` is a Claude Code skill that runs a hard task through a gated, multi-phase pipeline instead of answering in one shot. It splits the maker from the checker, refuses claims that carry no admissible evidence, and keeps all state on disk so nothing is rediscovered ([`plugins/dag/skills/dag/SKILL.md`](../plugins/dag/skills/dag/SKILL.md), Prime directives, lines 49–86). The rest of this wiki explains that machine from the ground up.

## The one-paragraph pitch

Large language models are fast and fluent, and that is exactly the problem: a single confident answer to a high-stakes question hides its own mistakes. `dag` treats a hard task the way a careful team would. It picks a set of **personas** (lenses) and pairs them propose-against-critique, clarifies every material ambiguity before touching the work, maps the terrain, then breaks the objective into **atomic work units** wired into a dependency graph and run wave-by-wave ([`SKILL.md`](../plugins/dag/skills/dag/SKILL.md) Phases 1–6, lines 151–389). Each unit is handed to an executor under a self-contained brief and a token budget, then handed to an **independent adversarial verifier** that never sees the executor's reasoning — only the brief, the debrief, and the artifacts ([`SKILL.md`](../plugins/dag/skills/dag/SKILL.md) Prime directive 3, lines 56–59). Disagreements that matter stop for a human. Everything durable — plan, decisions, progress, learnings — lives in a run-directory ledger, so the same mistake is never made twice. The payoff is a *verified* result you can audit line by line, not a plausible one you have to trust.

## Recommended reading order

Start at the intuition and climb toward the proofs. Each page stands on its own, but this order builds the mental model layer by layer.

1. [`01-layman-intuition.md`](01-layman-intuition.md) — the whole idea with no jargon: why one-shot answers are risky and what "split the maker from the checker" buys you.
2. [`02-llm-workings.md`](02-llm-workings.md) — just enough about how LLMs actually behave (fluent but fallible) to see *why* `dag` is shaped the way it is.
3. [`03-formal-methods.md`](03-formal-methods.md) — what "formal method" means here, and the vocabulary (FSM, invariant, proof) the later pages lean on.
4. [`04-self-learning-loops.md`](04-self-learning-loops.md) — the bounded correction loop: retry, escalate, and learn within a run without ever looping forever.
5. [`05-learnings.md`](05-learnings.md) — how a lesson is captured, generalized (the ≥2-unit gate), and propagated into later briefs so nothing is rediscovered.
6. [`06-verification.md`](06-verification.md) — the independent adversarial verifier: what it checks, how it refutes, and the PASS/FAIL/DISAGREE contract.
7. [`07-accuracy.md`](07-accuracy.md) — the anti-hallucination stance: adaptive evidence standards and "no claim without admissible evidence."
8. [`08-how-it-fits.md`](08-how-it-fits.md) — the nine phases end to end, and how the ledger threads them together.
9. [`09-personas-and-marketplace.md`](09-personas-and-marketplace.md) — personas as reusable lenses, and how `dag` ships as a Claude Code plugin/marketplace.
10. [`10-proof-appendix.md`](10-proof-appendix.md) — the TLA+/Alloy proof layer and exactly *what* is proved (and what is not).
11. [`11-diagrams-and-formulas.md`](11-diagrams-and-formulas.md) — the pipeline diagrams and formulas collected in one reference.

If you only read one page, read [`01-layman-intuition.md`](01-layman-intuition.md). If you are about to *change* the formal machinery, read [`04-self-learning-loops.md`](04-self-learning-loops.md) and [`10-proof-appendix.md`](10-proof-appendix.md) first.

## A note on proof status — read every guarantee at its true strength

This wiki is about a system that insists on evidence, so it holds itself to the same bar. Every guarantee is tagged with how strongly it is actually established. Mirror this legend exactly and never round up:

- **machine-checked (in scope)** — mechanically verified by a *machine* over emitted artifacts: either a model checker (TLC / Alloy) over a *bounded* model, **or** the runtime validator (`validate_run.py`) over a single run's ledger + briefs. `dag` describes its FSM as backed by a TLA+/Alloy proof layer for safety and termination ([`SKILL.md`](../plugins/dag/skills/dag/SKILL.md) lines 43–44; [`plugins/dag/skills/dag/references/formal-models.md`](../plugins/dag/skills/dag/references/formal-models.md)). "In scope" is load-bearing: a bounded check is not a proof for all inputs.
- **hand-proved** — argued on paper (e.g. the correction-loop termination proof), rigorous but not mechanized ([`plugins/dag/skills/dag/references/self-learning-loops.md`](../plugins/dag/skills/dag/references/self-learning-loops.md)).
- **asserted (consistent)** — a design property stated and kept internally consistent, but not proved. Discipline-enforced budgets are an example ([`SKILL.md`](../plugins/dag/skills/dag/SKILL.md) Scope note, lines 476–483: the 32K budget "is enforced by *discipline*", not a platform cap).

When a page says something is guaranteed, it will name which tier it means. If you catch a claim that overstates its tier, that is a bug in the wiki — file it.
