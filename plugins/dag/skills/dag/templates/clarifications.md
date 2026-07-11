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
