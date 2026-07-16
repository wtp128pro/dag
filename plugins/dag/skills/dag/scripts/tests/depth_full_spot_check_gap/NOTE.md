# Fixture: guardrail_chain_ok (POSITIVE — I20/I21/I22/I23/I24/I25 all adopted, all green)

The WP-F shared positive fixture: one DONE-phase run adopting EVERYTHING the guardrails-1.8.0
release added, all six new invariants PASSING simultaneously (mirrors `amend_ok`'s role for
I17/I18/I19). Copied from `good/` and extended (the COPY only) with a fully-materialized
`units/U02/`. Adoption inventory: every unit carries valid `dod_refs` (U01 -> DoD item 1,
U02 -> DoD item 2: every DoD item covered by a PASS-verified unit — I20 + I23 DoD clause);
every unit carries `non_goal_refs` (U02's legitimately `[]`, the explicit none-applicable
statement — I21); both briefs mirror both lists; every verdict-bearing verify carries a
compliant `guardrail_compliance` block incl. a `not-applicable` row, every ref covered, no
violated row (I22); every non-goal attested respected/not-applicable by a PASS unit (I23
non-goal clause); the register is non-empty with resolutions on material items (I24, I25);
fsm-state is at DONE with `signoff_confirmed: true`.

EXPECTED: exit 0, `RESULT: PASS`, no Python traceback. expectations.tsv row has the empty
substring per the header convention.
