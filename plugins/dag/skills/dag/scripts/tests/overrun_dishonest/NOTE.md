# Fixture: overrun_dishonest (NEGATIVE — IMP-04 / Task 6.1)

The other half of the budget-overrun-honesty tie. A debrief reporting `tokens_consumed>32000`
MUST self-identify as over-budget (`within_budget:false`); claiming `within_budget:true` while
over the ceiling is the dishonest report the schema now rejects (PR-6 `if/then` on `footprint`).

Copied from `good/`; its **sole** injected defect: `units/U01/debrief.json`
`footprint = { "tokens_consumed": 40000, "within_budget": true }`.

EXPECTED: exit 1 with the single operative failure
`FAIL units/U01/debrief.json: $.footprint.within_budget: must equal const False, got True`
and no Python traceback. Twin: `overrun_honest` (same tokens, `within_budget:false`, exit 0).
