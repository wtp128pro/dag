# Fixture: signoff_ok (POSITIVE — D-06(a)/BRK-13)

Proves a run may reach phase `DONE` when the Phase-8 human sign-off is recorded. D-06 adds
`gates.signoff_confirmed` to the validator's REQUIRED_GATES for `DONE`, closing the skip-the-human
hole (the validator previously could not tell sign-off happened).

Copied from `good/`, advanced to a complete single-unit `DONE` run: `graph.json` trimmed to just
`U01` (its edge + wave 2 removed); `fsm-state.json.phase = DONE` with all gates true **including
`signoff_confirmed: true`**; `U01` carries brief + debrief + verify (PASS). The optional
`learnings.json` is dropped (a single-unit graph cannot satisfy a `tag:`-scoped learning's ≥2-carrier
admission gate) and the brief's `learnings_applied` is emptied accordingly.

EXPECTED: exit 0 (RESULT: PASS). Twin: `signoff_missing`.
