# Fixture: overrun_honest (POSITIVE — IMP-04 / Task 6.1)

Proves that a REAL budget overrun can be reported **truthfully**. `debrief.schema.json`
formerly capped `footprint.tokens_consumed` at `maximum:32000`, so an executor that actually
spent more could only stay schema-valid by lying — defeating the `within_budget:false` signal and
the SKILL.md Scope-note discipline ("If footprint reports exceed budget, re-atomize — do not wave
it through"). PR-6 removes the `maximum` and adds a schema `if/then`: `tokens_consumed>32000 ⇒
within_budget const false`.

Copied from `good/`; its **sole** change: `units/U01/debrief.json`
`footprint = { "tokens_consumed": 40000, "within_budget": false }` — an honest overrun report.

EXPECTED: exit 0 (RESULT: PASS). The plan-side 32K cap on `brief.budget_tokens` /
`graph.est_footprint_tokens` is untouched (you still cannot PLAN >32K); only the *actual-usage
report* may exceed it, and only while self-identifying as over-budget. Twin: `overrun_dishonest`.
