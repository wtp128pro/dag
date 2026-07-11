# Fixture: guardrail_ref_uncovered (NEGATIVE — I22 non_goal_refs coverage)

Exercises the **I22 guardrail compliance coverage clause** (WP-2 synergy): when a unit carries
`non_goal_refs` AND its verify carries the block, every ref needs an attestation row. Copied
from `good/`, otherwise valid — I21 green (U01's ref verbatim + mirrored in its brief; U02
carries the explicit-none `[]`), I22 membership green (the row names non_goals item 2
verbatim), closure green, no violated row — so it does not trip anything for the wrong reason.
Sole injected defect: U01's `non_goal_refs` names non_goals item 1 ("do NOT edit the live dag
skill") but its rows attest only item 2.

EXPECTED: exit 1 with the single operative failure
`FAIL I22 guardrail compliance (units/U01): unit's non_goal_refs lack an attestation row: ['do NOT edit the live dag skill']`
and no Python traceback. expectations.tsv pins substring `I22 guardrail compliance`.
