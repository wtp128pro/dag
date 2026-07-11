# Fixture: p8_nongoal_unattested (NEGATIVE — I23 non-goal closure at DONE)

Exercises the **I23 closure non-goal clause**: at P8/DONE under WP-3 adoption, every
`non_goals` item needs a respected/not-applicable attestation row from some PASS unit.
Derived from the `guardrail_chain_ok` recipe (DONE phase, both units fully materialized,
I20/I21/I22 green: every DoD item covered, U01's single `non_goal_refs` entry attested,
rows verbatim, no violated row) — so it does not trip anything for the wrong reason. Sole
injected defect: both verifies' blocks attest only non_goals item 1, leaving item 2 ("do NOT
add NLP/semantic heuristics ...") attested by no PASS unit.

EXPECTED: exit 1 with the single operative failure
`FAIL I23 closure: non-goals with no respected/not-applicable attestation from any PASS unit: ['do NOT add NLP/semantic heuristics or new runtime dependencies to the validator']`
and no Python traceback. expectations.tsv pins substring `I23 closure`.
