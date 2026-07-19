<!-- DIALOGUES.md — the human-readable companion to the run-root dialogues.json (Phase-2/gate
     Socratic transcript series). JSON is the LOAD-BEARING surface; this file is its human
     rendering (the sources.md / verify.md "JSON-only load-bearing, prose companion" pattern).
     Schema: schemas/dialogues.schema.json — the AUTHORITATIVE field list; this template is
     ILLUSTRATIVE (a field guide that tracks the schema; the schema wins on any drift).

     dialogues.json is NOT scaffolded at run start (init_run.sh does NOT create it): a dialogue
     record is authored at the moment a bounded Socratic surface (DS-1/2/4/5/6) CLOSES — one
     record per surface INSTANCE. The file has its OWN schema, is RAW-parsed by the validator,
     and carries a ZERO-required fsm-state delta (DP-21): the round counters live HERE, not in
     fsm-state.json. Presence is version-gated at 1.10.0 (I27-T1 T1); every shape check fires
     whenever the artifact is present (T2). -->

# Socratic dialogues — <run label>

Top-level object: `{ run_label?, dialogues[ ], anchors_baseline? }` (`additionalProperties:false`).
`dialogues` is the only REQUIRED key — an array with one object per surface INSTANCE.
`anchors_baseline` is written ONCE at the first P2 gate close (see `## anchors_baseline`).

## Surface record
One object per closed surface instance. **Required:** `surface_id`, `instance`, `phase`, `rounds`,
`rounds_used`, `termination`. Everything else on this level is optional/conditional.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `surface_id` | required | `DS-1｜DS-2｜DS-4｜DS-5｜DS-6` | the CLOSED surface vocabulary — free-form minting is a defect |
| `instance` | required | pattern `^(p1｜p2｜p3-cartography｜p2-r[0-9]+｜p7-U[0-9]{2,}-[0-9]+｜p8｜bga-A[0-9]{2,})$` | DP-49 closed per-surface vocabulary |
| `phase` | required | string, minLength 1 | e.g. `P2_CLARIFICATION`, `P8_SYNTHESIS` |
| `ss_refs` | optional | string[], each `^SS-[0-9]+$` | source-sweep rows this dialogue drew on |
| `rounds_used` | required | integer `0..3` (`maximum:3`) | the DP-14 round cap; mirrors `verify_rounds` |
| `mandatory_kinds_completed` | optional | string[] of `R-OPEN｜R-FORBID｜R-CONFIRM｜R-GATE｜R-PROBE` | which mandatory round kinds this surface discharged |
| `rollback_ref` | **conditional** | string, minLength 1 | **REQUIRED iff `instance` matches `^p2-r[0-9]+$`** (a P2 re-entry): the recorded rollback license (impasse-dossier choice (b) or a P7/T11 rollback-to-P2 decision) |
| `rounds` | required | array | the ordered round records — see `## Round` |
| `termination` | required | object | how the surface closed — see `## Termination` |

## Round
One object per round in `rounds[ ]`. **Required:** `round`, `kind`, `pages`, `questions`, `answers`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `round` | required | integer `1..3` | round index within this surface |
| `kind` | required | `R-OPEN｜R-FORBID｜R-CONFIRM｜R-GATE｜R-PROBE` | the round kind |
| `moves_used` | optional | string[] (`uniqueItems`) of `FORK｜COUNTER｜ADMIT｜PIVOT｜RESIDUAL` | the Socratic moves exercised |
| `pages` | required | integer `≥1` | pages of interaction this round consumed |
| `deferred` | optional | string[], each minLength 1 | items pushed to a later round / the impasse dossier |
| `questions` | required | array | see `## Question & answer` |
| `answers` | required | array | see `## Question & answer` |
| `dispositions` | optional | array | **R-CONFIRM rounds** (DP-30) — per-item `confirm｜edit｜drop`; see below |
| `probe_discharge` | optional | object `{trigger, q_refs[minItems1]}` | DP-12 rung 2: probe content that entered THIS round's frozen queue (both keys required when present) |
| `effects` | optional | object | DP-25 "what changed" + DP-36 forbid residue; see below |

### dispositions (R-CONFIRM)
Per item exactly one of `confirm｜edit｜drop`. **Required per row:** `item`, `disposition`, `origin`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `item` | required | string minLength 1 | verbatim PRE-round text |
| `disposition` | required | `confirm｜edit｜drop` | the per-item decision |
| `edited_to` | **conditional** | string minLength 1 | **REQUIRED iff `disposition==edit`; FORBIDDEN unless `edit`** (strict iff) — verbatim POST-round text |
| `rationale` | **conditional** | string minLength 1 | **REQUIRED iff `disposition∈{edit,drop}`** (one-directional — legal narrative on any row) |
| `origin` | required | `orchestrator-authored｜human-elicited` | provenance of the item |
| `q_ref` | optional | string minLength 1 | the R-CONFIRM question that presented it (DP-29 per-disposition join) |
| `elicited_round_ref` | optional | string minLength 1 | for human-elicited auto-confirmed items (DP-31): ref to the eliciting round instead of a presentation `q_ref` |
| `reopened_by` | optional | string minLength 1 | DP-42: names new evidence when a settled item is re-presented |

### effects
All keys optional. `register_rows_resolved` (integer[] `≥1`), `dod_edits` (string[]),
`non_goals_added` (string[]), `draft_edits` (object[] `{item, offered, amendment}` all minLength 1),
`clean_sweep` (boolean — DP-36 R-FORBID), `clean_sweep_statement` (string minLength 1 —
**REQUIRED iff `clean_sweep==true`**), `decisions_ref` (string minLength 1), `summary` (string).

## Question & answer
`questions[ ]` and `answers[ ]` are the round's interaction. A `q_ref` on an answer resolves to a
question's `qid` (U01 owns the `qid` format; the schema keeps it an opaque minLength-1 string).

**Question — required:** `q`, `move`, `recommended`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `qid` | optional | string minLength 1 | per-question id; the resolution target of `answers[].q_ref` and `dispositions[].q_ref` |
| `q` | required | string minLength 1, `\S` | the question text |
| `move` | required | `FORK｜COUNTER｜ADMIT｜PIVOT｜RESIDUAL` | the Socratic move |
| `recommended` | required | string minLength 1, `\S` | DP-24/DP-43: a non-blank recommended answer on EVERY question |
| `battery_topic` | optional | `forbid｜fear｜rejection｜invariant` | **R-FORBID questions only** (DP-35) |
| `items_presented` | optional | string[] `maxItems:4`, each minLength 1 | **R-CONFIRM questions only** (DP-29): presented item strings VERBATIM; maxItems 4 is the stuffing-FAIL bound |

**Answer — required:** `a`, `q_ref`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `a` | required | string minLength 1, `\S` | DP-24: the literal VERBATIM human answer; NEVER orchestrator-filled |
| `q_ref` | required | string minLength 1 | joins to the question's `qid` |
| `answer_ref` | optional | string | a DECISIONS.md supplement (never a substitute for `a`) |
| `deviation` | optional | boolean | DP-24: RECOMPUTED by the validator (`a` vs `recommended`, whitespace-normalized); recorded for the sidecar |

### Worked example (minimal DS-5 sign-off, one converged R-GATE round)

```json
{
  "dialogues": [
    {
      "surface_id": "DS-5",
      "instance": "p8",
      "phase": "P8_SYNTHESIS",
      "rounds_used": 1,
      "rounds": [
        {
          "round": 1,
          "kind": "R-GATE",
          "pages": 1,
          "questions": [
            { "qid": "p8.r1.q1", "q": "Accept the deliverable as-is, or iterate?", "move": "ADMIT", "recommended": "Accept — every DoD item passed verification." }
          ],
          "answers": [
            { "a": "Accept.", "q_ref": "p8.r1.q1" }
          ]
        }
      ],
      "termination": { "reason": "converged" }
    }
  ]
}
```

## Termination
The `termination` object records HOW a surface closed. **Required:** `reason`
(`converged｜human-early｜capped-unconverged｜halt-pending`). The other payloads are strictly
conditioned on `reason` — one worked row per corner:

| `reason` corner | Required conditional payload | Forbidden payload | Optional on any close |
|-----------------|------------------------------|-------------------|-----------------------|
| `converged` | — (nothing extra) | `capped_open`, `impasse_dossier`, `pending_questions` | `probes_lapsed[ ]`, `gate_answer` |
| `human-early` | — (nothing extra) | `capped_open`, `impasse_dossier`, `pending_questions` | `probes_lapsed[ ]` (a `human-early` cause), `gate_answer` |
| `capped-unconverged` | `capped_open` (`minItems:1`) **and** `impasse_dossier` | `pending_questions` | `probes_lapsed[ ]`, `gate_answer` |
| `halt-pending` | `pending_questions` (`minItems:1`) | `capped_open`, `impasse_dossier` | `probes_lapsed[ ]` |

- `capped_open` — object[] of `{item (req, minLength 1), disposition?}` (the per-item impasse choice).
- `impasse_dossier` — `{ options[{option (req), recommended (req boolean = the ★ mark), evidence?, reversibility?}], per_item_choices[{item (req), choice (req)}], chained_halt_pending? }` (DP-18).
- `probes_lapsed` — object[] of `{trigger (req), q_ref?, item?, cause (req: cap-exhausted｜human-early)}`; one entry per fired-but-unserved obligation (DP-12/DP-26). Cause LEGALITY is a validator predicate (MC-9/MC-10 arithmetic).
- `pending_questions` — string[], each minLength 1 (DP-19/DP-26 non-interactive halt).
- `gate_answer` — string minLength 1. **REQUIRED non-blank at `surface_id==DS-2` iff `reason∈{converged,human-early}`** (surface-level conditional so it can read both `surface_id` and `termination.reason`); at DS-1/4/5/6 it is an optional echo of the terminal R-GATE answer (DP-26).

> **Corner discipline (L8):** the four `reason` values are a strict partition — a `converged`
> close carries NO `capped_open`/`impasse_dossier`/`pending_questions` (the backward `not` clauses
> make each conditional a strict iff). A recorded `probes_lapsed` entry is legal on a `converged`
> close only when the probe fired in the surface's FINAL recorded round with no free rung left
> (DP-12 arithmetic; contrast a mid-run free slot, which forces a dedicated R-PROBE) — otherwise it
> is rung-choice laundering, an MC-9/MC-10 FAIL.

## anchors_baseline
The GV-34 write-once snapshot of the two anchor lists, taken at the FIRST P2 gate close
(`clarification_resolved`); **P2 re-entry NEVER re-snapshots.** **Required:** `definition_of_done`
(`minItems:1`), `non_goals` (`minItems:1`), `content_hash` (minLength 1 — a content hash over the
two verbatim lists). OPTIONAL at the schema level so archives stay valid; fail-closed PRESENCE on an
armed run (`validator_version ≥ 1.10.0` ∧ `clarification_resolved`) is a validator predicate, not a
schema `required`.

> **Immutability note (§E — carried verbatim in the artifact, not just the debrief).** This mirrors
> `graph.json.baseline_units`/`fuel_initial` immutability. JSON Schema cannot express "write-once":
> a schema validates one snapshot, not a mutation history. Immutability is delivered by the same
> mechanism I17/I18 rely on — the field is **written once** (GV-34: at the FIRST P2 gate close;
> P2 re-entry never re-snapshots) and any later divergence is caught by the validator's replay
> (GV-8(d)/GV-23) **against this fixed reference**, plus the `content_hash` self-consistency check.
> **Honest residual (forwarded to U04/U06):** transcript-file integrity itself is **Limitation-P /
> attestation class** — the baseline and its hash live in ONE run-dir file under the validator's
> single-snapshot posture, so a fully-coordinated multi-file hand-edit that also rewrites the
> snapshot is structurally harder but **not provably closed**. Do **not** relabel this "Closed";
> scope it to I17-parity ("closed up to transcript-file integrity").
