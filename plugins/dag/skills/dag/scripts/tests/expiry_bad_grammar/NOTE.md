# Fixture: expiry_bad_grammar (NEGATIVE — N-08 / Task 6.4)

`learnings.schema.json` `scope.expiry` was an unconstrained string while `templates/graph.md` +
SKILL.md document the loader grammar `run|project|runs:N|date:<iso>`. A nonconforming value was
silently accepted and treated as INERT by `validate_run.py`'s `_expiry_expired` parser (a no-op).
PR-6 pins the field with `pattern: ^(run|project|runs:[0-9]+|date:[0-9]{4}-[0-9]{2}-[0-9]{2})$`,
turning that silent no-op into a visible failure.

Copied from `good/`; its **sole** injected defect: `learnings.json[0]` (a run-local entry) sets
`scope.expiry: "someday"`.

EXPECTED: exit 1 with the single operative failure
`FAIL learnings.json[0]: $.scope.expiry: 'someday' does not match pattern '…'` and no Python
traceback. The malformed run-local entry is REPORTED and DROPPED before the I12 propagation
comparison (run-local `learnings.json` malformation stays gating — it IS this run's artifact; cf.
`store_malformed_nongating` where an imported STORE entry is non-gating). `expiry_excluded`
(`date:2020-01-01`) still conforms and stays exit 0.
