<!-- DEBRIEF ARTIFACT GUIDE — the executor produces units/<id>/debrief.json ONLY (JSON-only; no
     debrief.md is written). The validator, the independent verifier, and downstream briefs all
     consume the JSON — there is no second markdown copy to keep in sync. Schema:
     schemas/debrief.schema.json.

     ACCURACY NOTE: reason FREE-FORM in your reply FIRST (evidence, tradeoffs, the Socratic pass) —
     do NOT shortcut the thinking — THEN write the JSON, keeping the prose fields (`result`,
     `handoff_notes`) rich and unhurried. The free-form reasoning lives in your turn + these string
     fields; the schema gates structure, never the reasoning itself. -->

# Debrief artifact — `units/<UNIT-ID>/debrief.json`

Reason freely in your response (what you produced, the evidence, the tradeoffs, and the Socratic
FORK·COUNTER·ADMIT·PIVOT·RESIDUAL self-interrogation on your material claims), **then** write
`debrief.json`. It is the single artifact — write full prose into `result` and `handoff_notes`;
never truncate to "fit" the schema.

**Required keys** (`schemas/debrief.schema.json`):
- `unit_id`, `persona`, `iteration`
- `result` — full narrative of what was produced / concluded (this is where the reasoning lands;
  if you produced an artifact, give its path)
- `evidence_table[]` — one row per material claim: `{claim, type, evidence (locator: path:line /
  URL§ / command→output), reproducible}`. **`type` MUST be one of these seven LITERAL schema strings**
  (U8 — the schema enum, not the prose labels): `empirical-world-fact`, `code-behavior`,
  `api-tool-contract`, `numeric-quantitative`, `causal`, `design-judgment`, `provenance-quote`
  (taxonomy rationale: evidence-standards.md).
- `socratic{premise, counter, pivot, confidence}` — result of the pre-output self-interrogation;
  `counter` records an OUTCOME (mechanical units: `counter: "unit is mechanical; no material
  premise to break"`); `confidence` starts `high|medium|low`
- `confidence` (`high|medium|low`) — the top-level unit confidence enum, distinct from the
  `socratic.confidence` sub-key above
- `footprint{tokens_consumed, within_budget}`

**Optional keys:** `acceptance_self_check[]` (`{criterion (required), met (required), evidence_ref
(optional)}`), `assumptions[]`, `residual_risks[]`, `handoff_notes[]` (facts downstream briefs
quote — prevents rediscovery), and — **retries only (`iteration>1`)** — `prior_feedback{}`: the
verbatim echo of iteration n−1's `verify.feedback` (`actionable_changes` + `do_not_touch`) plus
`changes_made[]`, ≥1 concrete change responsive to it (AO-6).

No `debrief.md` is written. `debrief.json` is authoritative and is what the verifier and every
downstream brief read.
