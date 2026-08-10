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
  Externally-sourced rows ALSO carry (schema `debrief.schema.json` is authoritative — this list
  is a NON-NORMATIVE mirror): `source_tier` (T-VENDOR/T-COMM/T-LOCAL/T-PARAM), `retrieval_rung`
  (live-fetch/vendored-docs/cached-copy/parametric-only), `accessed` (YYYY-MM-DD, never
  fabricated), `covers_owed` (owed ids this row discharges), `source_refs` (register S-ids),
  `vendor_silent` + `vendor_surface_searched`, and — on design-judgment rows —
  `extracted_premises` (+ `extracted_premises_none_reason`). Enforcement: I29/I30 + I31–I34
  (RL-1/RL-2/RL-3/CO-1), offline.
- `socratic.horizon{expedient, durable, durable_cost, choice[, debt]}` — OPTIONAL (1.14.0, I49).
  Name the **expedient** answer, the **durable** one, what durable **costs**, and which you chose. If
  you chose expedient, `debt{revisit_condition, decisions_ref}` is REQUIRED and the ref must RESOLVE
  in `DECISIONS.md`; if you chose durable, `debt` is FORBIDDEN — that is what makes
  `grep -l revisit_condition` an exact inventory of the run's debts. On a genuinely mechanical unit
  the legal value is the two answers coinciding, with
  `durable_cost: "no material horizon; the two answers coincide"`. **Record, never manufacture.**
  Adoption is closed: once any site in the run carries a horizon, every site must.
- `consumed_upstream[]{unit_id, used_for[, artifact_ref]}` — OPTIONAL (1.14.0). Which upstream unit
  outputs you ACTUALLY used. **No predicate reads this**, and that is deliberate: it exists so the
  deferred `I55` can be measured rather than argued about. Fill it if you can; nothing fails if you
  do not.
- `socratic{premise, counter, pivot, confidence}` — result of the pre-output self-interrogation;
  `counter` records an OUTCOME (mechanical units: `counter: "unit is mechanical; no material
  premise to break"`); `confidence` starts `high|medium|low`
- `confidence` (`high|medium|low`) — the top-level unit confidence enum, distinct from the
  `socratic.confidence` sub-key above
- `footprint{tokens_consumed, within_budget}` — `within_budget := tokens_consumed ≤ THIS unit's
  `brief.budget_tokens`` (F2; **not** the global 32K). Report `tokens_consumed` truthfully (it has no
  schema cap); set `within_budget: false` iff you exceeded *this brief's* `budget_tokens`. The validator
  (I5) FAILs a `tokens_consumed > brief.budget_tokens` paired with `within_budget: true`.

**Optional keys:** `acceptance_self_check[]` (`{criterion (required), met (required), evidence_ref
(optional)}`), `assumptions[]`, `residual_risks[]`, `handoff_notes[]` (facts downstream briefs
quote — prevents rediscovery), and — **retries only (`iteration>1`)** — `prior_feedback{}`: the
verbatim echo of iteration n−1's `verify.feedback` (`actionable_changes` + `do_not_touch`) plus
`changes_made[]`, ≥1 concrete change responsive to it (AO-6).

**Case-set discharge** (`case_set_discharge[]` — emit it whenever this unit's brief carries
`case_set`; the RULE the executor acts on is in SKILL.md Phase 6's dispatch blockquote, this is the
wire shape only, SPEC `units/U01/SPEC.md` §3):
- One row per frozen `brief.case_set` entry (`origin: "orchestrator"`), plus any row the executor
  ADDs (`origin: "executor"` — this array is the ONLY home for an added entry; there is no addendum
  file and no brief amendment).
- Row keys (`additionalProperties: false`) — REQUIRED: `id` (`^C[0-9]+$` when `origin:
  "orchestrator"`, `^CX[0-9]+$` when `origin: "executor"`), `origin` (`"orchestrator"` |
  `"executor"`), `outcome` (`"discharged"` | `"violated"` | `"infeasible"` | `"vacuous"`),
  `evidence` (a command + its ACTUAL output, or `path:line` + a quoted anchor phrase),
  `evidence_tier` (`"executable"` | `"located"` | `"asserted"`). Conditional: `asserted_reason`
  (iff `evidence_tier: "asserted"`), `non_vacuity[]` (iff `outcome: "discharged"`),
  `infeasible_reason` (iff `outcome: "infeasible"`), `vacuity_finding` (iff `outcome: "vacuous"`).
- `non_vacuity` is an **ARRAY**, `minItems: 1`, **one member per observation** —
  `{observation_ref, counterfactual, counterfactual_result}` (`additionalProperties: false`), plus
  `reason` iff `counterfactual_result: "not-run"`. `observation_ref` is a **VERBATIM** item of the
  entry's `required_observations` ∪ `forbidden_observations`; `counterfactual_result` is
  `"red"` | `"not-run"` — the field is `counterfactual_result`, **never** `result`.
- An `origin: "executor"` row ALSO carries the brief-entry keys (`check`, `check_form`,
  `trigger_ref`, `requirement_ref` / `requirement_ref_none_reason`, `required_observations`,
  `forbidden_observations`, `forbidden_observations_none_reason`, `production_path`,
  `production_path_none_reason`, each under its own condition). An `origin: "orchestrator"` row
  carries **none** of them — they live in the frozen brief, and a second copy can be quietly
  narrowed.


No `debrief.md` is written. `debrief.json` is authoritative and is what the verifier and every
downstream brief read.
