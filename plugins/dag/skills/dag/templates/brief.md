<!-- BRIEFING DOCUMENT — the self-contained contract handed to an executor subagent.
     Fill every section. The executor must need NOTHING outside this file and the
     paths it explicitly lists. Keep total required context ≤ 32K tokens. -->

# Brief — <UNIT-ID>: <title>

> **Also emit `brief.json`** (the machine-checkable sidecar, `schemas/brief.schema.json`) beside this
> file — the *orchestrator* writes it before dispatch. The validator's I11/I12/I16 checks key off this
> sidecar (required keys: `unit_id`, `title`, `wave`, `depends_on`, `persona`, `budget_tokens`,
> `acceptance_criteria`, `context_pointers`, `outputs`, `socratic_protocol`, `tags` ⊆ V_tag,
> `learnings_applied`). Prose reasoning stays here in `.md`; the sidecar carries only the extract.
> The sidecar ALSO mirrors the graph unit's **`dod_refs`** / **`non_goal_refs`** (scaffolded
> default): when the graph unit carries them, `brief.json` MUST carry the SAME sets — the I20/I21
> brief-mirror clause FAILs a missing or drifted mirror offline.
> The sidecar MAY also carry **`required_sources`** / **`claims_owed`** (+
> `claims_owed_none_reason`) — the execution-effort contract (I29): once any brief in the run
> adopts them, every brief must carry `claims_owed` (entries or explicit-none), and a non-empty
> set requires the verbatim CB-1 bridge criterion in `acceptance_criteria`.

- **Run:** <RUN_DIR name>
- **Wave / dependencies:** wave <k>; depends on: <U.. debriefs, or "none">
- **Persona to adopt:** <persona name> — <one-line mandate from PERSONAS.md>
- **Budget:** ≤ 32K tokens. Read the files listed under "Context pointers" AND consult the entries under "Required sources" — nothing else.
- **Tags:** `[<T ∈ V_tag>, …]` (from the `V_tag` registry in GRAPH.md — drives pattern-scoped learning propagation).
- **Learnings applied:** `[<Lid>, …]` — every LEARNINGS entry whose scope matches this unit (quote each below). `[]` only if none match.
- **DoD refs:** `["<verbatim definition_of_done item>", …]` — the DoD items this unit serves (≥ 1; mirrors the graph unit's `dod_refs`, I20).
- **Non-goal refs:** `["<verbatim non_goals item>", …]` — the non-goals this unit must actively respect; `[]` = explicitly none apply (mirrors the graph unit's `non_goal_refs`, I21).

## Objective
<one paragraph: exactly what this unit must produce. Single responsibility.>

## Acceptance criteria (verbatim, testable)
- [ ] <criterion 1 — how a verifier will check it>
- [ ] <criterion 2>

## Load-bearing facts (quoted inline so you don't rediscover them)
- <fact/decision the unit truly needs, quoted from CARTOGRAPHY/DECISIONS/CLARIFICATIONS>
- **Applicable learnings (one per `learnings_applied` id):** `<Lid>` — quote its `lesson`
  + `how_to_apply` verbatim so the executor acts on it without opening LEARNINGS.md.

## Context pointers (read ONLY these + the Required sources below; nothing else)
- `<path>` — <why / which section>
- `<path>` — <why>

## Required sources (via the register; consult through the fallback ladder)
<!-- Mirrors brief.json `required_sources[]` / `claims_owed[]` (I29). S-ids come from
     RUN_DIR/sources.json; locators are copied INLINE — the executor NEVER opens sources.json.
     Omit this section ONLY when the sidecar carries neither field. -->
- `S<n>: <locator> (tier, disposition)` — <what this unit must take from it>
- **Claims owed** (fixed by the ORCHESTRATOR from the acceptance criteria + register, O1–O4;
  you may ADD entries, never shrink): `<id>` — `<type>` @ `<min_tier>`, owed for criterion
  "<trigger_ref>", candidate source `S<n>`. `[]` is legal only with the recorded none-reason
  — the light floor verbatim (PR-4): `"claims_owed": [], "claims_owed_none_reason": "all
  criteria are design-judgment over run-local artifacts"`.
- Consult each required source at the HIGHEST reachable ladder rung (`live-fetch` →
  `vendored-docs` → `cached-copy` → `parametric-only`), declare the rung — never skip silently;
  evidence rows carry `source_tier`, `retrieval_rung`, `accessed`, `covers_owed`, `source_refs`.
- **CB-1 (copy VERBATIM into the acceptance criteria whenever this section is non-empty — I29-4):**
  Retrieval coverage: every claims_owed entry is discharged per its min_tier by evidence rows linked via covers_owed, and every required_sources entry is consulted at a declared fallback-ladder rung or its unreachability is declared in the debrief — never silently skipped.

## Case set (`case_set[]` — mirrors `brief.json`; sibling of `claims_owed`)
<!-- TEXT ONLY. The RULE — who derives it, when, how many entries, and what the executor may do
     with it — is stated in full in SKILL.md Phases 5 and 6; an orchestrator acts on it without
     opening this file. What follows is the wire shape and the strings that must be copied
     byte-for-byte (SPEC: units/U01/SPEC.md §2, §4.1). Omit this section ONLY when the sidecar
     carries neither `case_set` nor `case_set_none_reason`. -->
- **Entry keys** (`brief.json` `case_set[].items`, `additionalProperties: false`) — REQUIRED:
  `id` (`^C[0-9]+$`, unique in the array), `check`, `check_form` (`"command"` | `"locator"`),
  `trigger_ref` (**VERBATIM** member of this brief's `acceptance_criteria[] ∪ dod_refs[] ∪
  non_goal_refs[]`), `required_observations[]` (≥1), `forbidden_observations[]`, `production_path`
  (boolean), plus **exactly one** of `requirement_ref` (**VERBATIM** member of this brief's
  `dod_refs[] ∪ non_goal_refs[]`) / `requirement_ref_none_reason`. Conditional companions:
  `forbidden_observations_none_reason` (iff `forbidden_observations` is empty),
  `production_path_none_reason` (iff `production_path` is `false`). There is **no**
  `min_evidence_tier` key and **no** `note` key — both were deleted.
- **`check_form: "locator"` shape, verbatim:** `^[^\s:]+:[0-9]+([ \t][^\n]*)?$` — a `path:line`,
  optionally followed by a single-line anchor phrase. `check_form: "command"` = a command line whose
  exit status carries the observation.
- **Explicit-none (copy the pair VERBATIM, as with `claims_owed`):** `"case_set": [],
  "case_set_none_reason": "<what was searched before concluding no case set applies>"`. A
  none-reason whose text names empty `dod_refs`/`non_goal_refs` as the ground is not an
  explicit-none — that class uses the per-entry `requirement_ref_none_reason` form instead.
- **`forbidden_observations_none_reason` — the verbatim content-test form (one line, copy as-is):**
  `searched the quoted requirement_ref for not / never / must not / rather than / without / no X; none present.`
- **Worked pair, byte-for-byte from SPEC §4.1** (one DoD item with **two** negative statements ⇒
  **two** entries, because one `check` cannot reach every observation):

```json
[
  {
    "id": "C7",
    "check_form": "command",
    "check": "python3 -c \"import json,sys;b=json.load(open('brief.json'));d=json.load(open('debrief.json'));B=[e['id'] for e in b.get('case_set',[])];D=[r['id'] for r in d.get('case_set_discharge',[]) if r.get('origin')=='orchestrator'];miss=sorted(set(B)-set(D));dup=sorted({i for i in D if D.count(i)>1});print('missing',miss,'duplicate',dup);sys.exit(1 if miss or dup else 0)\"",
    "trigger_ref": "The spec states the orchestrator-derives / executor-may-ADD-never-shrink rule and names the debrief discharge record as the ONLY home for an added entry (D13b).",
    "requirement_ref": "SKILL.md Phase 5 instructs the ORCHESTRATOR to derive case_set[] pre-dispatch from the Definition of Done and the clarification register, each entry traced verbatim to its source item, with the forbidden observations derived from the requirement's own negative statements rather than from what the planned implementation happens to check; SKILL.md Phase 6 states the executor may ADD entries but never shrink one, and must escalate an infeasible entry with a recorded reason rather than dropping it silently.",
    "required_observations": [
      "every id in brief.case_set[] appears exactly once in debrief.case_set_discharge[] with origin 'orchestrator'"
    ],
    "forbidden_observations": [
      "a brief case_set[] id with no origin 'orchestrator' row in case_set_discharge[] (shrink by omission)"
    ],
    "production_path": false,
    "production_path_none_reason": "The requirement governs what two artifacts state about each other; there is no runtime consumer surface."
  },
  {
    "id": "C8",
    "check_form": "command",
    "check": "python3 -c \"import json,sys;d=json.load(open('debrief.json'));bad=sorted(r['id'] for r in d.get('case_set_discharge',[]) if r.get('outcome')=='infeasible' and not str(r.get('infeasible_reason','')).strip());print('silent_drop',bad);sys.exit(1 if bad else 0)\"",
    "trigger_ref": "The spec states the orchestrator-derives / executor-may-ADD-never-shrink rule and names the debrief discharge record as the ONLY home for an added entry (D13b).",
    "requirement_ref": "SKILL.md Phase 5 instructs the ORCHESTRATOR to derive case_set[] pre-dispatch from the Definition of Done and the clarification register, each entry traced verbatim to its source item, with the forbidden observations derived from the requirement's own negative statements rather than from what the planned implementation happens to check; SKILL.md Phase 6 states the executor may ADD entries but never shrink one, and must escalate an infeasible entry with a recorded reason rather than dropping it silently.",
    "required_observations": [
      "every row with outcome 'infeasible' carries a non-empty infeasible_reason"
    ],
    "forbidden_observations": [
      "a row with outcome 'infeasible' and an absent or whitespace-only infeasible_reason (the silent drop)"
    ],
    "production_path": false,
    "production_path_none_reason": "The requirement governs what two artifacts state about each other; there is no runtime consumer surface."
  }
]
```


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
