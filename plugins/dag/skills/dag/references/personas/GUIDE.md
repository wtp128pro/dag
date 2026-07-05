# Persona catalog — guide

The persona catalog is a **structured, per-file JSON library** with a lightweight index, so
Phase 1 can select cheaply (read the index; open only the entries it seriously considers)
without loading the whole catalog every run.

## Layout (this directory)
- **`index.json`** — the selection index: one object per persona with
  `{ name, role, description, mandate, skeptical_of, phase }` (phase trimmed to the assignment).
  **Read this FIRST** in Phase 1 to triage the full roster at a fraction of the cost of loading
  every persona's full entry — open a per-file entry only for a serious candidate.
- **`<kebab-name>.json`** — one file per persona, the full entry: required `name`, `role`,
  `description`; optional `mandate`, `optimizes_for`, `skeptical_of`, `phase`, `pair_with`,
  `qualifications` (array), `tags`. **Open a per-file entry only when a persona is a serious
  candidate** — the long `qualifications` research is adoption-time depth, not selection signal.
- All three persona sources — this curated catalog, user `~/.claude/dag/personas/*.json`,
  and project `.dag/personas/*.json` — share the **one** schema
  [../../schemas/persona.schema.json](../../schemas/persona.schema.json), so every persona
  validates uniformly regardless of origin.

## Selecting (Phase 1)
Select a **task-fit subset** of the catalog AND **synthesize task-specific personas** the
library lacks (hybrid sourcing). Rename generic archetypes to be concrete for the task
("Postgres Locking Expert", not "Domain Expert"). Every consequential producer persona must be
paired with a critic/verifier persona (propose ↔ critique).

Each entry's lens is: **mandate** (the decision it owns) · **optimizes_for** · **skeptical_of** ·
**phase** (typical phase/unit). Producer archetypes (Domain Expert, Implementer, Researcher,
Pragmatist, User Advocate) are meant to be **renamed + specialized** per task.

## Synthesizing new personas
When the library lacks a needed lens, define one with the same fields. Good task-specific
personas are **concrete** and **opinionated**: they should be able to *disagree* with another
persona on the merits. If two proposed personas can never disagree, you have one persona with
two names — merge them.

## Extending the library — your own personas
Add **reusable personas as JSON files** that Phase 1 discovers and merges into the candidate
pool automatically — no code, no edit to this skill. (This is persona *input*; it is distinct
from a run's `personas.json` roster *output*.)

**Discovery paths** (Phase 1 reads every `*.json` file under both):
- **Project:** `.dag/personas/*.json` — checked into the repo you are working in.
- **User:** `~/.claude/dag/personas/*.json` — your personal, cross-project library.

**Format** — one persona per file, validated by
[../../schemas/persona.schema.json](../../schemas/persona.schema.json); a copy-ready example is
[../../templates/persona.json](../../templates/persona.json). The field set is fixed
(`additionalProperties:false`): required `name`, `role`, `description`; optional `mandate`,
`optimizes_for`, `skeptical_of`, `phase`, `pair_with`, `qualifications`, `tags`. These are the
same fields a curated entry carries, so a discovered persona and a curated one are
interchangeable downstream. (The `/dag:personas` skill writes user/project personas in
exactly this shape.)

**Merge / override order.** The Phase-1 pool is the **union** of {this curated catalog,
discovered project JSON, discovered user JSON, task-synthesized personas}. On a **name
collision**, the more specific source wins: **project `.dag/personas/` > user
`~/.claude/dag/personas/` > curated catalog**. The merged roster still goes through the
Phase-1 persona **gate** (human confirmation) unchanged — discovery adds candidates, it does
not bypass the gate.
