# Fixture: guardrail_pass_violated (NEGATIVE — I22 violated+PASS)

Exercises the **I22 guardrail compliance decidable semantic clause**: a `violated` row on a
PASS verdict is a FAIL ("a delivered non-goal is a FAIL, not a bonus", SKILL.md Phase 6).
Copied from `good/`, otherwise valid — the row's `non_goal` is verbatim in
`clarifications.json.non_goals` (membership green), U01's verify is the only verdict-bearing
verify and it carries the block (closure green), and no unit has `non_goal_refs` (coverage
clause dormant) — so it does not trip anything for the wrong reason. Sole injected defect:
`units/U01/verify.json` (`verdict: PASS`) carries one `status:"violated"` row.

EXPECTED: exit 1 with the single operative failure
`FAIL I22 guardrail compliance (units/U01): a violated non-goal row on a PASS verdict: a delivered non-goal is a FAIL, not a bonus`
and no Python traceback. expectations.tsv pins substring `I22 guardrail compliance`.
