# Verification — the maker is never the checker

**Audience:** technical (LLM / agent-systems). Pairs with
[07-accuracy.md](07-accuracy.md) (evidence standards) and
[04-self-learning-loops.md](04-self-learning-loops.md) (the correction loop this feeds).

**TL;DR.** Dag never lets the instance that produced a work unit sign off on it. A *separate*
verifier persona receives the brief, the debrief, and the artifacts — but **not** the
executor's chain-of-thought — and is incentivized to *refute*. Its verdict is a machine-checkable
`verify.json` (PASS / FAIL / DISAGREE) with a no-vague-FAIL rule and an independent premise
re-check. This same discipline runs three times: per unit (Phase 6), on genuine splits
(Phase 7 → human), and on the whole deliverable (Phase 8).

> **Proof-status legend** (used verbatim below): *machine-checked (in scope)* = a validator/schema
> enforces it on emitted artifacts; *hand-proved* = argued on paper, not mechanized; *asserted
> (consistent)* = a self-attestation the system records but cannot mechanically confirm. This page
> is about a system that insists on evidence, so it never says "proved for all inputs."

---

## 1. Why the maker cannot be the checker

Start from first principles. If you ask a model to grade its own answer, you are asking a
process to find the flaws in the very thing it just decided was flawless. That is not skepticism;
it is confirmation bias with extra steps.

The repo states the core idea plainly: *"a single model instance that both makes and checks its
own work suffers confirmation bias. So the checker must be a separate instance that is
incentivized to refute"* (`references/methodology.md` §Verification, lines 193–200).

Two research results the repo leans on (attributed exactly as it attributes them, in
`references/methodology.md` §Hard-won principles #1, line 278):

- **LLM judges provably favor their own outputs** — self-preference tied to self-recognition,
  which *persists even when authorship is hidden*. *(arXiv:2410.21819, NeurIPS'24 2404.13076.)*
- And a corollary the repo pairs with it (#2, line 281): **ground every correctness gate in an
  EXTERNAL signal** — a test, tool output, an independent verifier — never the model re-reading
  its own reasoning, because *intrinsic self-correction of reasoning is unreliable and can degrade
  output*. *(arXiv:2310.01798.)*

The second point is the sharp one: self-correction isn't just weak, it can make a *correct*
answer *worse*. So Dag doesn't hand the executor a mirror. It hands the result to someone else.

---

## 2. Independence of context — the verifier is blind to reasoning

Separateness of *instance* isn't enough; the verifier must also be separate in *what it sees*.
The rule (`references/methodology.md` §Verification, lines 202–204):

> **Independence of context.** The verifier receives the brief, the debrief, and the artifacts —
> **not** the executor's reasoning/chain of thought. It forms its own view.

Why exclude the chain-of-thought? Because reading the maker's reasoning is how you get *joined*
verification — you inherit its framing and re-confirm its errors. The Socratic protocol says this
directly: *"Joint verification reinforces errors; this is why the verifier re-runs COUNTER from
evidence rather than reading the executor's reasoning"* (`references/methodology.md` §Socratic,
lines 27–29; `references/socratic-protocol.md` COUNTER row, line 37: "answered *independently of
your draft* … not by re-reading and rationalizing your own reasoning").

**How it's mechanized.** The `verify.json` artifact carries a boolean the schema *pins* to false:

```json
"executor_reasoning_seen": { "type": "boolean", "const": false }
```

(`schemas/verify.schema.json`, lines 14–18). A report where this is anything but `false` is
schema-**invalid** — that structural fact is *machine-checked (in scope)*. The repo labels this the
independence invariant (the brief and the validator's invariant set call it **I1**; its
machine-checkable form is exactly this schema `const`). A companion, **I1b**, is the
*persona-distinctness* half: the verifier's persona must differ from the maker's — a checker
optimizing for a *different* thing (`references/methodology.md` §Personas, lines 73–80: *"The
Adversarial Verifier persona must be able to reach the opposite conclusion from the executor
without penalty; never staff it as a rubber stamp"*).

Be honest about the seam: the schema can prove the *field says* `false`, but it cannot prove the
verifier *actually* never saw the reasoning — that is a **self-attestation**, *asserted
(consistent)*, not a platform guarantee. The schema itself says so at line 17: *"Self-attestation,
not a platform guarantee (see state-machine Limitation A)."* See §9.

### Data-flow: what the verifier can and cannot touch

```mermaid
flowchart LR
    subgraph EX["Executor (maker) — isolated context"]
        COT["chain-of-thought /
        reasoning"]:::blind
        ART["artifacts"]
        DEB["debrief.json
        (result, evidence_table,
        socratic, handoff_notes)"]
    end
    BRIEF["brief.md
    (acceptance criteria,
    guardrails, evidence std)"]

    subgraph VF["Verifier (checker) — separate instance & persona"]
        V["forms its OWN view;
        re-runs COUNTER from evidence"]
    end

    BRIEF --> V
    DEB --> V
    ART --> V
    COT -. "NOT passed
    (I1 / executor_reasoning_seen=false)" .-> X((✗))

    V --> OUT["verify.json
    verdict + feedback + defects
    + premise_check"]

    classDef blind fill:#fdd,stroke:#c00,stroke-dasharray:4 3;
```

The dashed red edge is the whole point: the executor's reasoning is *inside the box* and never
crosses into the verifier. Everything the verifier reads (brief, debrief, artifacts) is an
*emitted, inspectable artifact* — the same evidence a third stranger could open.

---

## 3. The refutation mandate

A verifier that only confirms is broken. The mandate
(`references/methodology.md` §Verification, lines 205–207):

> **Refutation mandate.** Its job is to *break* the result: find the counterexample, the unmet
> criterion, the unsupported claim, the hallucinated citation, the budget breach. A verifier that
> only confirms is malfunctioning.

Note the incentive design in §Personas (lines 73–80): the critic *"optimizes for a different thing
than the proposer (proposer = ship the simplest correct change; critic = find the input that
breaks it)"* and *"must be able to reach the opposite conclusion … without penalty."* PASS is not
the default the verifier is nudged toward; a clean break earns as much as a clean pass.

---

## 4. Guardrail / scope-creep check

Refutation isn't only "did it do too little?" — it's also "did it do too *much*?" Dag treats
delivered-but-unasked-for work as a defect, not a gift
(`references/methodology.md` §Verification, lines 208–212):

> **Guardrail compliance.** … every artifact traces to an acceptance criterion (which in turn
> traces to a Definition-of-Done item), and nothing on the unit's Non-Goals / guardrails list was
> built. **A delivered non-goal is a FAIL, not a bonus** — scope creep is a defect the checker must
> catch, the same as an unmet criterion.

This closes the loop opened in Phase 2, where the Definition of Done and the Non-Goals / Guardrails
list are *mandatory* outputs (`references/methodology.md` §Clarification, lines 102–121). The
verifier's two-sided test: **every DoD item met** *and* **no non-goal shipped**. Phase 8 applies the
identical check at task scope (line 212).

---

## 5. Evidence re-check — reproduce, don't trust

Every debrief carries an **evidence table**; the verifier re-audits it row by row
(`references/methodology.md` §Verification, lines 213–216):

> **Evidence re-check.** For each claim … the verifier independently confirms the evidence is real
> and admissible … It reproduces results where feasible (run the test, open the cited page,
> re-derive the number).

The admissibility rules live in [evidence-standards.md](../plugins/dag/skills/dag/references/evidence-standards.md).
Evidence is judged *by claim type* — code claims want `path:line` **plus a run**, world-facts want a
primary dated source (two if contested), quotes must be verified verbatim before use
(`references/evidence-standards.md`, taxonomy table lines 12–20; operating rules lines 24–42). Two
rules the verifier weaponizes:

- *"Fabricated citations/APIs are the highest-severity hallucination — verifiers hunt these first"*
  (rule 4, line 34–35).
- *"A debrief with an unbacked material claim is a **FAIL**, regardless of how plausible the claim
  is"* (closing line, line 54).

And the anti-hallucination rule that cuts *both* ways: *"Absence of evidence is a finding"* (rule 7,
lines 41–42) — a verifier that can't reproduce a claim must *say so*, not wave it through. The
per-claim checklist the verifier runs is at `references/evidence-standards.md` lines 44–52.

---

## 6. The verdict / feedback JSON contract

The verifier's output is not prose — it's `units/<UID>/verify.json`, a machine-checkable extract
(`schemas/verify.schema.json`). Required fields: `unit_id`, `verifier_persona`, `verdict`,
`iteration`, `executor_reasoning_seen`, `feedback`, `defects`, `socratic`, `premise_check` (line 8).

**Three verdicts** (`verdict` enum, line 12; semantics in `references/methodology.md` lines 217–218):

| Verdict | Meaning | Schema constraint (*machine-checked, in scope*) |
|---|---|---|
| `PASS` | criteria met, evidence sound | `defects == []` — no phantom defects on an accepted unit (schema `allOf`, lines 99–108) |
| `FAIL` | specific defect + minimal repro | `>=1` defect **and** non-empty `feedback.actionable_changes` (lines 83–98) |
| `DISAGREE` | genuine judgment split, no objective resolution → Phase 7 | a `disagreement` object with `why_unresolvable` set (lines 110–120) |

**The no-vague-FAIL rule.** You cannot fail a unit with a shrug. A FAIL is *schema-invalid* unless
it carries at least one `defect` — and each defect must name a `severity`
(blocker/major/minor) and a `criterion` (schema lines 41–48) — **and** `feedback.actionable_changes`
is non-empty (lines 85–97). The schema description states it outright: *"FAIL is schema-INVALID
unless it carries >=1 defect (each naming a criterion) AND feedback.actionable_changes is
non-empty"* (line 5). So a FAIL is always *actionable*: it tells the next iteration exactly what to
change.

**Defects cite brief criteria, not the verifier's taste.** Each `defect.criterion` must be a member
of the brief's `acceptance_criteria` — *"membership cross-checked by the validator"* (schema line 37;
description line 5). That keeps the verifier honest: it can only fail you against a criterion you
were given, not one it invented.

**The feedback object** (schema lines 24–33) has two halves that make the correction loop
productive:

- `actionable_changes` — concrete edits for the next iteration (required; non-empty on FAIL).
- `do_not_touch` — what was already correct and must be *preserved*. This is what stops a retry from
  regressing the parts that passed.

---

## 7. Premise-check — the backstop against premise deflection

A clever self-check can defeat itself by examining a *safe* premise and ignoring the real one —
"premise deflection." The repo names the antidote
(`references/methodology.md` §Hard-won principles #6, lines 294–296):

> A self-check must confirm the **PREMISE** is the load-bearing claim before hunting a
> counterexample … The independent verifier confirms the premise, then **re-runs COUNTER from
> evidence**.

This is mechanized as the required `premise_check` object (`schemas/verify.schema.json`, lines
62–73), with four required fields:

```json
"premise_check": {
  "executor_premise_quoted":       "…",      // the maker's stated load-bearing claim, verbatim
  "is_load_bearing":               true,      // did the verifier agree that's THE claim?
  "counter_reran_independently":   true,      // COUNTER re-run decoupled, from evidence
  "outcome":                       "…"        // what the independent re-run found
}
```

The schema's own gloss (line 65): the verifier *"first confirmed the executor's stated premise is
the deliverable's LOAD-BEARING claim, then RE-RAN COUNTER on it independently (decoupled, from
evidence, never by reading executor reasoning)."* This is the COUNTER move of the Socratic protocol
(`references/socratic-protocol.md`, COUNTER row line 37) executed by the *checker*, not the maker —
the second, independent pass that catches a premise the maker quietly swapped.

The verifier also files its **own** 4-key `socratic` block (`premise` / `counter` / `pivot` /
`confidence`) on its verdict (schema lines 50–61) — same shape and rules as any debrief block, with
`counter` required to record an *outcome*, not a promise (`references/socratic-protocol.md`, lines
59–64).

---

## 8. Panels — odd number, diverse lenses

For irreversible or high-cost units, one skeptic isn't enough
(`references/methodology.md` §Verification, lines 219–222):

> **Panels for high stakes.** … run an **odd panel** (3) of verifiers with *different lenses*
> (correctness / adversarial-input / does-it-actually-reproduce) and take the majority. Diversity
> beats redundancy — three identical skeptics find less than three differently-motivated ones.

The design insight: an odd count guarantees a majority; *different lenses* (not three clones)
maximize the surface area of attack. It's the persona-diversity principle from §Personas applied to
the verifier seat.

---

## 9. How verification interweaves across Phases 6 / 7 / 8

Verification isn't a single station at the end — the same discipline recurs at three scopes.

```mermaid
flowchart TD
    E["Phase 6: unit executed
    → debrief.json"] --> V{"Adversarial verifier
    (separate instance+persona)
    verify.json"}
    V -->|PASS| DONE["unit accepted"]
    V -->|FAIL| L{"correction loop
    (cap 2 retries)"}
    L -->|"feed actionable_changes
    back → re-execute → re-verify"| E
    L -->|"still failing after cap"| D
    V -->|DISAGREE| D["Phase 7: human gate
    (Socratic elicitation)"]
    DONE --> F["Phase 8: final whole-deliverable pass
    every DoD item met · no non-goal shipped"]
    D --> F
```

**Phase 6 — per unit.** Each unit gets its own verifier and its own `verify.json`. A FAIL feeds the
`actionable_changes` back into a **correction loop capped at 2 retries**; if it still fails, it is
*not* an infinite loop — it becomes a Phase-7 disagreement
(`references/methodology.md` §Self-learning loops, lines 234–242). The `iteration` field
(schema line 13, `minimum: 1`) numbers each pass.

**Phase 7 — disagreement → human.** A `DISAGREE` verdict is reserved for a *genuine* judgment split
with no objective resolution (methodology line 218); the schema forces it to carry a
`disagreement.why_unresolvable` (lines 110–120), and it routes to a human Socratic gate — the
*elicitation* mode of the same protocol (`references/socratic-protocol.md`, lines 11–13; the gate
discipline in `references/methodology.md` §Socratic, lines 9–44). Machine disagreement escalates to
a person; it is never silently resolved by re-running the loser.

**Phase 8 — final whole-deliverable pass.** After all units pass, the guardrail + DoD check is
re-applied at *task* scope: *"every DoD item met, no non-goal shipped"*
(`references/methodology.md` line 212). Unit-level PASS does not imply deliverable-level PASS — the
seams between units are exactly where an incomplete whole hides.

Trace of authority for this section: verdict semantics and loop caps →
`references/methodology.md` §Verification / §Self-learning loops; the JSON contract →
`schemas/verify.schema.json`; evidence admissibility →
`references/evidence-standards.md`; the Socratic gate/self-mode →
`references/socratic-protocol.md`.

---

## 10. Honest limits

This page would violate its own subject if it overstated the guarantee. Two limits, stated plainly:

- **Self-attestation (Limitation A).** `executor_reasoning_seen: false` is *machine-checked (in
  scope)* as a **field value** — the schema rejects any other value. But that the verifier *truly*
  never saw the executor's reasoning is a **self-attestation**, *asserted (consistent)*, not a
  platform-enforced guarantee. The schema says so at line 17: *"Self-attestation, not a platform
  guarantee (see state-machine Limitation A)."* A dishonest or careless run could write `false` and
  still have peeked; the invariant catches structure, not intent.
- **Shared weights (Limitation D, per the repo's limitation ledger).** Maker and checker are
  *different personas / instances*, but on the same platform they may share the *same underlying
  model weights*. Self-preference research (§1) shows bias can survive hidden authorship; a separate
  persona reduces but does not *eliminate* correlated blind spots. The strongest available
  mitigation the repo names is a *different model* where possible (`references/methodology.md`
  §Hard-won principles #1, line 276: *"ideally a different model"*) plus panel diversity (§8) — both
  *reduce* correlation rather than prove independence.

  > **Grounding note.** The "Limitation A" locator is confirmed in
  > `schemas/verify.schema.json:17`. The **D** label and the full limitation ledger live in
  > `references/state-machine.md` §5 / `references/self-learning-loops.md` §5 (referenced from
  > `references/methodology.md` lines 249–252), which were **not** read for this page — treat the
  > exact "D" index as *asserted from the brief*, while the *substance* (shared-weights /
  > correlated-bias risk) is grounded in §1's cited research and methodology #1.

The takeaway is not "trust the verifier" — it's "the verifier's independence is *structurally
enforced where it can be, and honestly labeled where it can't be*." That honesty is the guarantee.

---

*Sibling pages:* [07-accuracy.md](07-accuracy.md) (the evidence rulebook the verifier applies) ·
[04-self-learning-loops.md](04-self-learning-loops.md) (where a FAIL goes next) ·
[08-how-it-fits.md](08-how-it-fits.md). This page closes the propose → critique → verify arc.
