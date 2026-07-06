# Fixture: store_malformed_nongating (POSITIVE — IMP-07 / Task 2.5: a corrupt store is non-gating)

Proves the "learnings role never gates a phase transition" promise (SKILL.md Phase 0.5 /
self-learning-loops.md). A cross-run STORE (project `.dag/learnings/`, user `~/.claude/dag/learnings/`)
is IMPORTED CONTEXT, not this run's emitted artifact; a stale/corrupt store file must not brick every
future run of the project. The old validator `rep.fail`ed on a malformed store entry → exit 1 → PD7
hard stop, contradicting both docs. Now a malformed store file/entry is a NON-GATING `NOTE` (still
DROPPED, never reaching I12). Run-local `learnings.json` malformation stays `rep.fail` (see
`tests/bad_learnings`, still exit 1 — it IS this run's artifact).

Contents: a minimal valid run (`personas.json`, `fsm-state.json` at `P2_CLARIFICATION` with
`personas_confirmed=true`) plus a project store entry `.dag/learnings/G9.json` that is valid JSON but
schema-invalid (`since_wave: "BAD"`, a string).

BEFORE the fix: exit 1 with `FAIL learnings-store .dag/learnings/G9.json[0]: $.since_wave: expected
type ['integer'], got string`. AFTER the fix: exit 0 with a `NOTE  learnings-store … MALFORMED
(dropped, non-gating — imported store context): …` line.

EXPECTED: exit 0 (RESULT: PASS) with the `NOTE learnings-store … MALFORMED …` line and no Python
traceback.
