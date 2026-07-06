# Fixture: verify_without_debrief (NEGATIVE)

Exercises the **I9 verify-without-debrief** check (IMP-17) — the converse of `missing_verify`: a unit
dir carrying a `verify.json` but NO debrief is incoherent (a verifier attested to a unit that
produced no debrief to verify). Fail closed.

Copy of `good` with `units/U01/debrief.json` deleted (verify.json kept, phase left at
`P6_EXECUTE_VERIFY` so the P8-only I10 completeness check does not fire). BEFORE the fix this returned
rc=0 (RESULT: PASS) — a verify with nothing verified passed silently.

EXPECTED: exit 1 with the single operative message
`FAIL  I9 verify-without-debrief (units/U01): verify present but no debrief — a verifier output with
nothing verified is incoherent` and no Python traceback.
