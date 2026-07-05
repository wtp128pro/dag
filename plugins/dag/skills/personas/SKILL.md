---
name: personas
description: >-
  List, add, remove, or modify reusable Dag personas through a short,
  selective Socratic dialogue. Use whenever the user wants to list / browse / review /
  create / add / edit / update / delete / remove / manage / curate a persona, a persona
  library, or a `.dag/personas` file — at the project level (`.dag/personas/`),
  the user/"global" level (`~/.claude/dag/personas/`), or to see the built-in curated
  catalog. `list` aggregates all three sources so the user can pick one to edit or delete;
  add/modify write one schema-valid persona per file so Dag Phase 1 can discover it.
  Invoke with `/dag:personas`.
argument-hint: "[list | add | remove | modify a persona]"
allowed-tools: Read, Write, Edit, Bash, Glob, AskUserQuestion
---

# personas — manage the Dag persona library

You maintain the reusable persona JSON files that Dag Phase 1 discovers and
merges into its candidate pool. A persona lives in **one file** at a discovery path:

- **Project** (checked into the current repo): `.dag/personas/*.json` (CWD-relative).
- **User / "global"** (cross-project, personal): `~/.claude/dag/personas/*.json`.

A third source, the **built-in curated catalog**
([../dag/references/personas/](../dag/references/personas/)), ships with the plugin as
**per-file JSON** (`<name>.json` + an `index.json` selection index), the SAME schema you write
here. Phase 1 merges it into the same pool, but it is **read-only** — you do not edit or delete
the plugin's shipped entries; you can only shadow one with a project/user JSON of the same
`name` (override order below). `list` surfaces all three sources together.

Do the smallest thing that satisfies the request. Run the Socratic dialogue
**selectively** — ask only where a choice is genuinely open. Never interrogate a field
the user chose to skip. For the move-set behind this elicitation style, see
[../dag/references/socratic-protocol.md](../dag/references/socratic-protocol.md).

## The persona schema (enforce this inline — no external validator)

Authoritative contract:
[../dag/schemas/persona.schema.json](../dag/schemas/persona.schema.json).
Model the written shape on
[../dag/templates/persona.json](../dag/templates/persona.json). The field set is
**fixed** (`additionalProperties: false` — reject anything not listed):

| Field | Required | Type | Meaning |
|---|---|---|---|
| `name` | **yes** | non-empty string | Concrete persona name, e.g. "Java Backend Architect". |
| `role` | **yes** | non-empty string | Short role label, e.g. "Architect", "Verifier". |
| `description` | **yes** | non-empty string | What the persona is and the lens it brings. |
| `mandate` | no | string | The decision this persona owns. |
| `optimizes_for` | no | string | What it optimizes for. |
| `skeptical_of` | no | string | What it is skeptical of. |
| `phase` | no | string | Typical Dag phase/unit the persona is invoked at (e.g. `6`, `3/6`). |
| `pair_with` | no | string | The critic/verifier persona this one names as its counterpart. |
| `qualifications` | no | array of strings | Concrete qualification claims (each with its source), for researched roles. |
| `tags` | no | array of strings | Free-form tags for filtering/discovery. |

This is the **one uniform schema** shared by the curated catalog and every user/project persona —
`add`/`modify` here always write this same shape, so a persona you create is byte-for-byte
interchangeable with a curated one downstream.

Rules you enforce before writing any file:
- The three required fields must be present and non-empty.
- Only the ten fields above may appear. **Reject unknown fields** — do not silently drop
  them; tell the user and stop.
- **One persona per file** (a single JSON object, not an array).
- **Filename = kebab-case of `name`** (e.g. "Java Backend Architect" →
  `java-backend-architect.json`). Lowercase, spaces/underscores/punctuation → single hyphens,
  collapse repeats, trim leading/trailing hyphens.
- **Create the target directory if missing** (`mkdir -p`).

## Stage 1 — operation (elicitation)

Ask what the user wants to do. Use **AskUserQuestion** with options **List**, **Add**,
**Remove**, **Modify**. If the invocation argument already names the operation unambiguously
(e.g. "add a persona", "list personas"), skip this question — that is the selective rule, not
ritual.

## Stage 2 — location (elicitation)

Ask where the persona lives. Use **AskUserQuestion** with two options:
- **Project** → `.dag/personas/` (relative to the current working directory).
- **User / global** → `~/.claude/dag/personas/` (expand `~` to the real home).

If the user already stated "global" / "user" / "project" / "this repo", skip the question.

**Skip Stage 2 entirely for `List`** — it aggregates all sources at once. Skip it for
Remove/Modify too when **List** has already pre-selected a target file (its location is known).

## Stage 3 — complete the operation

### List (aggregate all sources, then optionally edit/delete)

1. **Gather** personas from all three sources:
   - **Built-in (read-only):** `Read`
     [../dag/references/personas/index.json](../dag/references/personas/index.json) —
     one object per built-in persona (`name`, `role`, `description`, `mandate`, `skeptical_of`,
     `phase`); for a full entry `Read` the matching
     `../dag/references/personas/<name>.json`. These ship with the plugin — no file to edit
     or delete.
   - **User / global:** `Glob ~/.claude/dag/personas/*.json`; `Read` each → name / role /
     description. An empty or missing directory is fine — just show none for that source.
   - **Project / local:** `Glob .dag/personas/*.json`; `Read` each → name / role /
     description. Empty/missing is fine.
2. **Display** a unified list grouped by source (**Project → User → Built-in**). Every entry,
   built-in or not, now has `name`/`role`/`description`, so each row is
   `name — role: <first clause of description>`; for Project/User entries also show the **file
   path** (built-ins ship with the plugin, so note them as read-only rather than editable files).
   State the override order **project > user > built-in**,
   and **flag any name that shadows another source** — normalize names the same way as the
   filename rule above (lowercase; collapse whitespace/punctuation to single hyphens; trim
   leading/trailing hyphens) before comparing, so e.g. `Planner-Architect` and the built-in
   `Planner / Architect` heading are recognized as the same name (a project `Clarifier` overrides
   the built-in one).
3. **Ask** (AskUserQuestion) whether to **Edit**, **Delete**, or **Done / just view**. On Edit
   or Delete, present the personas as options to pick the target, then route into the existing
   **Modify** / **Remove** flow **with the file already selected** — skipping that flow's own
   location + `Glob` discovery (steps 1–2).
   - If the picked persona is **built-in** (has no file):
     - **Edit** → explain it is read-only; **offer to create an override** via the Add flow with
       `name` pre-filled, at project or user level (Phase 1 prefers the override on a name
       collision). Proceed only if the user agrees.
     - **Delete** → explain built-ins ship with the plugin and cannot be removed; the closest
       action is a project/user override that redefines it. Offer that override or cancel.

### Add

1. Elicit the **three required fields** — `name`, `role`, `description` — one lens at a time,
   in prose (elicitation mode). Push for a *concrete* name and a description that captures the
   lens, mirroring `templates/persona.json`.
2. **Offer** the optional fields (`mandate`, `optimizes_for`, `skeptical_of`, `phase`,
   `pair_with`, `qualifications`, `tags`) together, with an explicit easy skip ("say skip / none
   to leave any of these out"). Do **not** re-question or defend a field the user skips — omit it
   from the JSON entirely. This is the same uniform field set the curated catalog uses, so an
   added persona is interchangeable with a built-in one.
3. Build the JSON object with only the fields provided. Reject any field the user tries to add
   that is not in the schema.
4. Derive the filename (kebab-case of `name`) and the full path from the Stage-2 location.
   `mkdir -p` the directory if needed.
5. **Collision check** with Glob/Read: if a file of that name already exists, this is a
   destructive overwrite — show the existing persona and **confirm** (AskUserQuestion:
   Overwrite / Add numeric suffix like `-2` / Cancel) before writing.
6. Write the file, then verify it is valid JSON: `python3 -m json.tool <path> >/dev/null`
   (stdlib only — this confirms parseability, not schema; schema is your job above).
7. Give the **completion confirmation** (see below).

### Remove (list-and-pick, destructive)

> If **List** already chose the target file, skip steps 1–2 and go straight to step 3.

1. `Glob` `*.json` at the chosen location. If none, say so and stop.
2. For each file, `Read` it and show **name / role / description**. Present them via
   AskUserQuestion so the user picks the target.
3. **Confirm the deletion** (AskUserQuestion: Delete / Cancel) — show the file path and persona
   summary first. Only on explicit confirmation, delete: `rm <path>`.
4. Give the completion confirmation.

### Modify (list-and-pick, then guided edit; destructive overwrite)

> If **List** already chose the target file, skip step 1 and start at step 2.

1. List-and-pick exactly as in Remove (steps 1–2) to select the target file.
2. `Read` the current JSON. Ask which fields to change; guide the edit in elicitation mode for
   just those fields. Adding an optional field is fine; removing one is fine. Do not touch or
   re-interrogate fields the user leaves alone.
3. Re-validate the whole object against the schema (required non-empty; no unknown fields; one
   object). If `name` changed, the filename should change too — recompute the kebab-case name,
   and treat the rename as a new-file collision check (confirm before clobbering; remove the old
   file only after the new one is written and confirmed).
4. This overwrites an existing file → **confirm before writing** (show a before/after summary).
5. Write, verify JSON with `python3 -m json.tool`, then confirm completion.

## Completion confirmation (every operation ends here)

State plainly:
- the **resulting file path** (or, for remove, the deleted path);
- a one-line **persona summary** (`name` — `role`: first clause of `description`);
- for add/modify, note that Dag Phase 1 will now discover it at that location, with
  override order **project > user > curated** on a name collision.
- for a **List** that ends with no follow-up action, just confirm what was shown (counts per
  source) — no file was written or deleted.

Do not commit, push, or edit any file outside the chosen persona path.
