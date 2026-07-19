<!-- CLARIFICATIONS.md — the ambiguity register + resolutions (output of Phase 2). -->

# Clarifications — <run label>

## Ambiguity register
| # | Ambiguity | Why it matters | Candidate interpretations | Materiality | Resolved (y/n) | Resolution |
|---|-----------|----------------|---------------------------|-------------|----------------|------------|
| 1 | <undefined term / missing criterion> | <impact> | <A / B / C> | material / minor | y / n | <user answer @ ts \| logged default> |

> Sidecar note: `clarifications.json` requires a per-row `resolved` **boolean** (row keys:
> `id, ambiguity, materiality, resolved`) — the I8 "no OPEN material ambiguity" guard keys off it
> — DISTINCT from the free-text `Resolution` (optional `resolution`). The `Why it matters` /
> `Candidate interpretations` columns are prose-only (`.md`) and are NOT carried into the sidecar
> (`additionalProperties:false`). `clarifications.json` ALSO requires two non-empty string arrays,
> `definition_of_done` and `non_goals` (the `## Definition of Done` and `## Non-Goals / Guardrails`
> sections below): the validator's artifact-driven **I-dod** invariant requires this file — with a
> non-empty `definition_of_done` AND `non_goals` — to exist once ANY post-clarification structural
> artifact exists (cartography, graph, units, or synthesis).

> **Resolution required on resolved MATERIAL items (schema conditional + I25 mirror):** a register
> row with `materiality: "material"` AND `resolved: true` MUST carry a non-empty `resolution`
> string — `clarifications.json` is schema-INVALID without it (the item-level `allOf` conditional),
> and the validator's **I25** mirror additionally rejects whitespace-only text. Record *how* the
> item was closed (the user's answer @ timestamp, or the logged default + rationale) — never a bare
> `resolved: true` on a material row.

> **`round_ref` on a register row (CL-4/AF-28 — optional).** A register row MAY carry an optional
> `round_ref` string (minLength 1): an opaque round-id that resolves into the transcript
> (`dialogues.json`) round-id set, linking the ambiguity to the Socratic round that closed it. The
> existing integer `round` field is UNTOUCHED (AF-29) — `round_ref` is additive, and absent ⇒ the
> archive stays valid.

## Definition of Done
<!-- Testable exit checklist. Each bullet becomes one string in clarifications.json `definition_of_done`
     (array, minItems 1, each item non-empty). Phrase as an observable, checkable outcome. -->
- [ ] <observable, testable exit condition — e.g. "validator exits 0 on the run dir">
- [ ] <observable, testable exit condition — e.g. "all acceptance criteria met with evidence">

## Non-Goals / Guardrails
<!-- Explicit "do NOT" list. Each bullet becomes one string in clarifications.json `non_goals`
     (array, minItems 1, each item non-empty). State what is deliberately out of bounds. -->
- do NOT <explicitly excluded goal / out-of-scope change>
- do NOT <guardrail the run must not cross — e.g. "add new runtime dependencies">


## Resolved success criteria (fold into PLAN.md)
- <testable criterion derived from resolutions>

## Scope boundaries
- **In scope:** <…>
- **Out of scope (explicit):** <…>

## Logged defaults (immaterial — chosen without bothering the user)
- <default> — <rationale>

## Still open (blocking → gate before proceeding)
- <material item awaiting user>

## Item confirmations
<!-- Carried into clarifications.json `item_confirmations` (CL-1/GV-6): the APPEND-ONLY
     confirmation event log over the anchor lists. Records are NEVER updated in place or deleted;
     array order IS record order. Currency (GV-35), reconciliation (GV-8), and add_units autonomy
     narrowing (GV-24/25) are U04 predicates over this array. OPTIONAL: absent ⇒ archives valid;
     presence arms GV-8/11. -->
One row per confirmation event. **Required per row:** `item`, `list`, `disposition`, `origin`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `item` | required | string minLength 1 | the verbatim anchor item text |
| `list` | required | `definition_of_done｜non_goals` | which anchor list the item belongs to |
| `disposition` | required | `confirmed｜edited｜added｜removed` | the confirmation event |
| `origin` | required | `elicited-forbid-round｜elicited-confirmation-round｜derived-orchestrator｜prompt-verbatim｜amendment` | how the item entered/was confirmed |
| `prior_text` | **conditional** | string minLength 1 | **REQUIRED iff `disposition∈{edited,removed}`** — the verbatim pre-event text |
| `transcript_ref` | **conditional** | string minLength 1 | a ref into `dialogues.json` (the confirming round) |
| `amendment_ref` | **conditional** | string minLength 1 | a ref into an `amendments/A<NN>.json` (mid-run additions) |

> **Human-evidence rule (GV-7):** a confirming record needs a human evidence ref — **`transcript_ref`
> OR `amendment_ref`** (the schema `anyOf`). Append-only is enforced by the currency predicate (GV-35),
> not the schema: a second non-superseded record for the same `(item, list)` is a FAIL.

## Anchors retired
<!-- Carried into clarifications.json `anchors_retired` (CL-2/GV-15): the append-only log of anchor
     items retired by a revise_anchors amendment. OPTIONAL: absent ⇒ archives valid. -->
One row per retired anchor item. **Required per row:** `list`, `prior_text`, `amendment_ref`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `list` | required | `definition_of_done｜non_goals` | which anchor list lost the item |
| `prior_text` | required | string minLength 1 | the verbatim text of the retired item |
| `amendment_ref` | required | string minLength 1 | the `revise_anchors` amendment that retired it |

## Pending halt (non-interactive)
<!-- Carried into clarifications.json `pending_halt` (CL-3/AF-35): the non-interactive halt marker
     recorded when a MATERIAL ambiguity cannot be resolved without the human on a non-interactive
     run. OPTIONAL object: absent ⇒ archives valid; adoption arms AF-35/36/42. -->
A single object (not an array). **Required:** `register_ids`, `surface`, `declared`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `register_ids` | required | integer[] `minItems:1`, each `≥1` | the blocking ambiguity-register row ids |
| `surface` | required | string | where the halt was surfaced to the human |
| `declared` | required | string | the halt declaration (the AF-43 sanctioned-signature line — the marker is a fixed, recognizable declaration, not free improvisation, so the resume path can key on it) |

## Provenance blocks
<!-- Carried into clarifications.json as THREE parallel arrays (CL-5/AF-32/AF-33):
     `definition_of_done_provenance`, `non_goals_provenance`, `out_of_scope_provenance`.
     One row per anchor/out-of-scope item. OPTIONAL: absent ⇒ archives valid; presence arms
     AF-17/AF-45. -->
Each block has the SAME row shape. **Required per row:** `item`, `register_ids`, `source`.

| Field | Req? | Type / bound | Notes |
|-------|------|--------------|-------|
| `item` | required | string | the anchor / out-of-scope item text |
| `register_ids` | required | integer[], each `≥1` | the ambiguity-register rows that produced it |
| `source` | required | `orchestrator-draft｜register-row｜human-round` | where the item came from |
| `round_ref` | optional | string minLength 1 | opaque round-id into `dialogues.json` (AF-28) |

> **Source coherence (AF-45):** a row whose `source==human-round` should trace to a `round_ref`
> (and to `item_confirmations`/`dialogues.json`); a row whose `source==register-row` should trace to
> `register_ids` that exist in the ambiguity register. Coherence is a validator predicate, not a
> schema `required`.
