#!/usr/bin/env bash
# init_run.sh — deterministically bootstrap a dag run directory.
#
# Usage:   init_run.sh <label> [base_dir]
#   <label>     short human label for the run (will be kebab-cased)
#   [base_dir]  where to create the run dir (default: current working dir)
#
# Creates:  <base_dir>/.wip/<YYYY-MM-DD>_<HHMMSS>_<label>/
#           (all runs live under a single gitignored .wip/ parent; the run dir
#            itself does NOT start with a dot)
#           ├── INPUT.md        (raw task prompt — filled by Dag)
#           ├── PLAN.md         (living master plan)
#           ├── DECISIONS.md    (append-only decision log)
#           ├── PROGRESS.md     (append-only progress log)
#           ├── LEARNINGS.md    (self-learning loop ledger)
#           ├── fsm-state.json  (initial pipeline FSM state — phase P0_BOOTSTRAP)
#           └── units/          (per-work-unit brief/debrief/verify)
#
# JSON-sidecar convention (validated by <skill>/schemas via <skill>/scripts/validate_run.sh):
#   most artifacts are written as <name>.md PLUS a machine-checkable <name>.json (e.g. GRAPH.md +
#   graph.json). The per-unit debrief and verify are JSON-only (units/U01/debrief.json, verify.json):
#   reason free-form in your reply, then write the JSON. Dag runs validate_run.sh after each artifact and
#   before every gate; a non-zero exit is a hard stop. Schemas + validator live in the SKILL
#   dir (validate_run.py resolves schemas at ../schemas), so the run dir needs no schema copy.
#
# Prints the absolute path of the created run dir on the LAST line of stdout.
# Idempotent-safe: refuses to clobber an existing directory.
set -eu

if [ "$#" -lt 1 ]; then
  echo "ERROR: missing <label> argument" >&2
  echo "usage: init_run.sh <label> [base_dir]" >&2
  exit 2
fi

RAW_LABEL="$1"
BASE_DIR="${2:-$(pwd)}"

# Kebab-case the label: lowercase, non-alnum -> '-', squeeze, trim leading, cap length.
# N-18: cap to 40 chars FIRST, then trim any trailing hyphen the cut may have exposed (reordered,
# so a truncated label never ends in '-').
LABEL=$(printf '%s' "$RAW_LABEL" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-*//' \
  | cut -c1-40 \
  | sed -e 's/-*$//')
[ -n "$LABEL" ] || LABEL="run"

# N-18: one clock read, formatted twice, so the dir stamp and ISO timestamp cannot straddle a
# second boundary (macOS `date -r <epoch>`; GNU/Linux `date -d @<epoch>`).
NOW_EPOCH=$(date +%s)
STAMP=$(date -r "$NOW_EPOCH" +"%Y-%m-%d_%H%M%S" 2>/dev/null || date -d "@$NOW_EPOCH" +"%Y-%m-%d_%H%M%S")
ISO=$(date -r "$NOW_EPOCH" +"%Y-%m-%dT%H:%M:%S%z" 2>/dev/null || date -d "@$NOW_EPOCH" +"%Y-%m-%dT%H:%M:%S%z")
RUN_DIR="$BASE_DIR/.wip/${STAMP}_${LABEL}"

if [ -e "$RUN_DIR" ]; then
  echo "ERROR: run dir already exists: $RUN_DIR" >&2
  exit 3
fi

mkdir -p "$RUN_DIR/units"

# Absolute path (portable; avoids realpath dependency).
ABS_RUN_DIR=$(cd "$RUN_DIR" && pwd)
# N-18: JSON-escape the path (it may contain " or \) so fsm-state.json is always valid JSON.
# python3 is a hard skill dependency (validate_run.py); json.dumps emits the surrounding quotes too.
ABS_RUN_DIR_JSON=$(python3 -c 'import json,sys; sys.stdout.write(json.dumps(sys.argv[1]))' "$ABS_RUN_DIR")

cat > "$RUN_DIR/INPUT.md" <<EOF
# Task Input

- **Run:** \`${STAMP}_${LABEL}\`
- **Created:** ${ISO}

## Raw prompt
_(Dag: paste the verbatim task prompt here)_

## Provided parameters / constraints
_(Dag: list any parameters, files, deadlines, or constraints supplied)_
EOF

cat > "$RUN_DIR/PLAN.md" <<EOF
# Master Plan — ${LABEL}

- **Created:** ${ISO}
- **Status:** intake

## Objective
_(one-paragraph statement of what "done" means, refined after clarification)_

## Success criteria
_(bulleted, testable acceptance criteria)_

## Personas
_(link: PERSONAS.md)_

## Phase ledger
| Phase | State | Artifact |
|-------|-------|----------|
| 0 Bootstrap | done | INPUT.md |
| 1 Personas | pending | PERSONAS.md |
| 2 Clarification | pending | CLARIFICATIONS.md |
| 3 Cartography | pending | CARTOGRAPHY.md |
| 4 Decomposition | pending | GRAPH.md |
| 5 Briefing | pending | units/*/brief.md |
| 6 Execute+Verify | pending | units/*/debrief.json, verify.json |
| 7 Disagreement gates | as-needed | units/*/disagreement.md |
| 8 Synthesis | pending | SYNTHESIS.md |

## Open questions
_(carried from clarification until resolved)_
EOF

cat > "$RUN_DIR/DECISIONS.md" <<EOF
# Decision Log — ${LABEL}

> Append-only; newest last: choice · rationale · alternatives rejected · decided-by.

| # | Timestamp | Decision | Rationale | Alternatives rejected | Decided by |
|---|-----------|----------|-----------|-----------------------|------------|
| 1 | ${ISO} | Run initialized | Bootstrap run | — | init_run.sh |
EOF

cat > "$RUN_DIR/PROGRESS.md" <<EOF
# Progress Log — ${LABEL}

> Append-only, newest at the bottom. One line per state change.

- ${ISO} — RUN INITIALIZED (\`${STAMP}_${LABEL}\`)
EOF

cat > "$RUN_DIR/LEARNINGS.md" <<EOF
# Learnings Ledger — ${LABEL}

> Append-only; keep entries GENERALIZABLE (scope ≥2 units) — one-offs go in a unit debrief.
> Each entry is injected into later briefs.

| # | Timestamp | Lesson | Trigger (what went wrong) | How to apply going forward | Scope (applies_to / excludes / expiry) | since_wave | Evidence |
|---|-----------|--------|---------------------------|----------------------------|----------------------------------------|------------|----------|
EOF

# Seed the initial pipeline FSM state. Seeding all-false gates is valid at P0/P1 where no gate
# is yet required: no loop substate yet, all gates false — the gate-ordering invariant fires
# from P2 onward (personas_confirmed is required from P2; see references/state-machine.md).
cat > "$RUN_DIR/fsm-state.json" <<EOF
{ "run_dir": ${ABS_RUN_DIR_JSON}, "phase": "P0_BOOTSTRAP", "updated_at": "${ISO}",
  "gates": { "personas_confirmed": false, "clarification_resolved": false,
             "cartography_done": false, "decomposition_approved": false },
  "units": [] }
EOF

echo "OK: seeded ledger files (INPUT, PLAN, DECISIONS, PROGRESS, LEARNINGS), fsm-state.json + units/"
# LAST line = machine-readable run dir path for Dag to capture.
printf 'RUN_DIR=%s\n' "$ABS_RUN_DIR"
