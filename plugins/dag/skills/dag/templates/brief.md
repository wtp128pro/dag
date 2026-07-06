<!-- BRIEFING DOCUMENT — the self-contained contract handed to an executor subagent.
     Fill every section. The executor must need NOTHING outside this file and the
     paths it explicitly lists. Keep total required context ≤ 32K tokens. -->

# Brief — <UNIT-ID>: <title>

> **Also emit `brief.json`** (the machine-checkable sidecar, `schemas/brief.schema.json`) beside this
> file — the *orchestrator* writes it before dispatch. The validator's I11/I12/I16 checks key off this
> sidecar (required keys: `unit_id`, `title`, `wave`, `depends_on`, `persona`, `budget_tokens`,
> `acceptance_criteria`, `context_pointers`, `outputs`, `socratic_protocol`, `tags` ⊆ V_tag,
> `learnings_applied`). Prose reasoning stays here in `.md`; the sidecar carries only the extract.

- **Run:** <RUN_DIR name>
- **Wave / dependencies:** wave <k>; depends on: <U.. debriefs, or "none">
- **Persona to adopt:** <persona name> — <one-line mandate from PERSONAS.md>
- **Budget:** ≤ 32K tokens. Read ONLY the files listed under "Context pointers".
- **Tags:** `[<T ∈ V_tag>, …]` (from the `V_tag` registry in GRAPH.md — drives pattern-scoped learning propagation).
- **Learnings applied:** `[<Lid>, …]` — every LEARNINGS entry whose scope matches this unit (quote each below). `[]` only if none match.

## Objective
<one paragraph: exactly what this unit must produce. Single responsibility.>

## Acceptance criteria (verbatim, testable)
- [ ] <criterion 1 — how a verifier will check it>
- [ ] <criterion 2>

## Load-bearing facts (quoted inline so you don't rediscover them)
- <fact/decision the unit truly needs, quoted from CARTOGRAPHY/DECISIONS/CLARIFICATIONS>
- **Applicable learnings (one per `learnings_applied` id):** `<Lid>` — quote its `lesson`
  + `how_to_apply` verbatim so the executor acts on it without opening LEARNINGS.md.

## Context pointers (read ONLY these; read nothing else)
- `<path>` — <why / which section>
- `<path>` — <why>

## Evidence standard (see references/evidence-standards.md)
- Claim types expected in this unit: <e.g., code-behavior, empirical-world-fact>
- Required evidence: <e.g., path:line + a run; primary source + URL>

## Inputs / Outputs
- **Inputs:** <artifacts consumed>
- **Outputs:** write `units/<UNIT-ID>/debrief.json` (JSON-only) per templates/debrief.md; plus <artifacts, paths>.

## Out of scope (do NOT do these)
- <explicit non-goals to prevent scope creep / budget blowout>

## Socratic self-interrogation (run BEFORE producing output)
- **Self-mode:** run FORK·COUNTER·ADMIT·PIVOT·RESIDUAL on this unit's *material* claims
  (references/socratic-protocol.md). Skip if the unit is purely mechanical.
- Record the result in your debrief's `socratic` block (4 keys: `premise`, `counter`,
  `pivot`, `confidence`). A blank block, or a `counter` that promises instead of recording an
  outcome, fails verification.

## Required debrief
Produce `debrief.json` (JSON-only) per `templates/debrief.md` (authoritative field list). Its
schema-**required** keys are: `unit_id`, `persona`, `iteration`, `result`, `evidence_table`, the
`socratic` block, `confidence`, and `footprint` (report token usage). Optionally add
`acceptance_self_check`, `assumptions`, `residual_risks`, and `handoff_notes` for downstream
units. On a retry (`iteration > 1`), also
populate `prior_feedback` (verbatim echo of the prior `verify.feedback` + the `changes_made` in
response). Reason free-form in your reply first.
