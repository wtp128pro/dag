<!-- REFERENCE — one shared Socratic protocol, cited by every prompt in the skill.
     Cited by ONE line per prompt; never copied into a brief. Read on demand.
     Grounded in three principles: decoupled verification, selective (non-ritual)
     clarification, and reason-free-form-then-extract. -->

# The Socratic Protocol

One move-set, two modes. It exists so questioning is **genuine, decoupled, and cheap** —
not a ritual. Same five moves everywhere; the mode just changes *who answers*.

- **Elicitation mode** (human gates — Phases 1, 2, 7, 8): you surface the moves **to the
  user** and elicit their answer.
- **Self-interrogation mode** (subagent briefs — executor / verifier / cartographer /
  planner): you run the moves **on yourself, from evidence**, *before* producing output,
  and record the **result** (not the dialogue) in the `socratic` block of your debrief.

## When to run it (the trigger — read this first)

Run the moves **only on material surfaces**: a decision or claim where a wrong answer
changes the deliverable, or is hard to reverse. **Skip** mechanical, unambiguous, or
low-reversibility steps (a file read, a rote extraction, a settled default). Scale depth
to stakes: one material claim → one pass; a lookup unit → none.

> **Anti-theater rule (the reason this file exists).** Indiscriminate questioning is
> "question theater" — it burns budget, and clarifying/self questioning helps *only* when
> triggered by a real ambiguity, not run as a fixed ritual. Worse, it invites
> you to *manufacture* doubt about facts that are actually solid: the unprompted "self-
> correction" that can *degrade* a correct answer into a wrong one. If a
> move finds nothing, write **"sought X; none found"** in one line and move on. Never invent
> a counterexample to look diligent. Fewer, real questions beat many hollow ones.

## The five moves (mnemonic: FORK · COUNTER · ADMIT · PIVOT · RESIDUAL)

| # | Move | Self-interrogation mode (answer from evidence) | Elicitation mode (ask the user) |
|---|------|-----------------------------------------------|---------------------------------|
| a | **FORK** — premise + falsifier | State the one claim your output stands or falls on, and what observation would *falsify* it. | Surface the fork, not the menu: the tradeoff each option implies + what becomes irreversible later. |
| b | **COUNTER** — seek the counterexample, **decoupled** | Actively hunt the case that breaks your premise, answered *independently of your draft* — from source/test/first principles, **not** by re-reading and rationalizing your own reasoning (joint verification reinforces errors). | Steelman the option you are **not** recommending, so the user is not led. |
| c | **ADMIT** — interrogate the evidence | For each load-bearing source: is it real, primary, and admissible for this claim type? (Feeds your evidence table — do **not** re-encode it in the `socratic` block.) | State the evidence behind your recommendation, plainly. Recommend, *then* ask. |
| d | **PIVOT** — what would change the answer | Name the single fact/result that, if flipped, flips your conclusion. | Ask what the user is **optimizing for** and what they **fear** — the fear usually names the real acceptance criterion. |
| e | **RESIDUAL** — declare uncertainty | State residual uncertainty + a calibrated confidence (high/medium/low). | One decision per question; log the answer + the alternatives rejected (DECISIONS.md). |

Free-form *first*, then extract: think the moves through in prose, then
distill the result into the small block below. Never conduct the dialogue *inside* JSON.

## The `socratic` field (the checkable result — for the debrief / verify schema)

The extracted, machine-checkable residue of a self-interrogation pass. **4 keys**, each a
short string; a validator confirms the block is present and non-blank (proof the protocol
was actually engaged, not skipped):

```
socratic:
  premise:    <one sentence: the claim this output stands or falls on>          # FORK
  counter:    <the counterexample sought + outcome: "sought X; it holds/breaks because…">  # COUNTER
  pivot:      <the one fact/result that, if flipped, would flip the conclusion> # PIVOT
  confidence: <high|medium|low> — <residual uncertainty in one clause>          # RESIDUAL
```

Valid-value rules (what the schema and validator check):
- all four keys present; `premise`, `counter`, `pivot` non-empty (≥ a clause each);
- `counter` must record an *outcome*, not a promise — blank or "n/a" fails; on a genuinely
  mechanical unit the correct value is `"unit is mechanical; no material premise to break"`;
- `confidence` starts with one of `high | medium | low` (regex-checkable; same vocabulary as the
  top-level `confidence` enum — no `med` abbreviation).

Elicitation-mode results are **not** encoded here — they live in DECISIONS.md (existing
schema). The self-mode block is recorded in a **schema-enforced** `socratic` field for every role
that runs it: the **executor** in `debrief.json` and the **verifier** in `verify.json` (both
required); the **cartographer** in `cartography.json` and the **planner/architect** in `graph.json`
(both an OPTIONAL `socratic` block added for these roles — they emit no debrief.json — and, when
present, I13-checked exactly like debrief/verify; D-07). In all four the `counter` must record an
OUTCOME.

## Cost (why this does not blow the 32K budget)

Per prompt, the added footprint is **one reference line + one ~4-line block** — not a copied
essay. The essay lives *here*, once, read on demand. The reference line names the moves
(FORK/COUNTER/ADMIT/PIVOT/RESIDUAL) so a capable model runs the protocol *without* opening
this file; it reads the file only when it needs the "how." Example reference line for a brief:

> **Socratic (self-mode):** run FORK·COUNTER·ADMIT·PIVOT·RESIDUAL on your material claims
> (references/socratic-protocol.md); record the result in your debrief's `socratic` block.

## Worked example (a real executor pass)

Unit: "recommend a zero-dependency JSON-Schema validator for the run."
```
socratic:
  premise:    Python3 + jsonschema is present, so no new dependency is needed.
  counter:    Sought a box without jsonschema; `python3 -c 'import jsonschema'` exited 1 on a
              clean env — premise BREAKS, so I add a stdlib-only fallback check.
  pivot:      If jsonschema were guaranteed present, the fallback is dead weight and I drop it.
  confidence: medium — verified on this box only; other environments unconfirmed.
```
Contrast — a mechanical unit does **not** manufacture doubt:
```
socratic:
  premise:    Copy the four ledger filenames from init_run.sh into the template.
  counter:    unit is mechanical; no material premise to break.
  pivot:      n/a — a wrong copy is caught by the file-exists check.
  confidence: high — names read directly from source.
```
