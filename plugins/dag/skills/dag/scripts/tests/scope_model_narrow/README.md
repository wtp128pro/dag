# Fixture: scope_model_narrow (POSITIVE — 04/G4 scope.model narrowing)

Positive companion to `scope_model_match/`. Proves the G4 `scope.model` conjunct can only NARROW
I12 propagation: a model-scoped learning whose model does NOT match the run's model is EXCLUDED,
so a carrier unit that omits it still PASSes.

Setup (copied from `good/`): `fsm-state.json.model = "claude-sonnet-4-5"`, `learnings.json` L1
gains `scope.model = "claude-opus-*"` (does NOT match), and `units/U01/brief.json` has
`learnings_applied: []`. Because L1's model does not match the run, G4 drops it from the
propagation set entirely, so U01's omission is not a violation.

Observed:
`PASS I12 model narrowing (04/G4): L1 scope.model='claude-opus-*' does not match run model
'claude-sonnet-4-5' — EXCLUDED from propagation this run (narrowing conjunct)` => RESULT: PASS.
Contrast `scope_model_match/` (matching model => L1 injected => I12 FAIL, exit 1).

EXPECTED: exit 0 (RESULT: PASS). No `NOTE.md` (this is a positive fixture).
