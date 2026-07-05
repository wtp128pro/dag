# Fixture: scope_model_match (NEGATIVE — I12 / G4 scope.model, matching side)

Exercises the **G4 scope.model NARROWING conjunct** on the I12 propagation predicate (added in
U05): a learning bearing `scope.model` binds a run only when the run's model
(`fsm-state.json.model`) MATCHES (fnmatch glob OR prefix). This fixture proves the **matching**
side — a model-scoped learning that DOES match is force-injected exactly as before, so an
unlisted carrier still FAILs I12 propagation.

The run is otherwise valid — copied from `good/` — so nothing trips for the wrong reason. Setup:
`fsm-state.json.model = "claude-opus-4-8"`, `learnings.json` L1 gains
`scope.model = "claude-opus-*"` (MATCHES the run model), and `units/U01/brief.json` has
`learnings_applied: []` (omits L1). Because L1 matches the run model it stays in the propagation
set; U01 carries `tag:core` at wave 1 >= `since_wave 1` but does not list L1.

EXPECTED: exit 1 with the single operative failure
`FAIL I12 learnings propagation: units/U01 carries tag:core at wave 1 >= since_wave 1: MUST list
L1 in learnings_applied (has [])` and no Python traceback.

Companion positive: `scope_model_narrow/` (same setup but a NON-matching run model => L1 is
narrowed out => PASS).
