# Fixture: missing_personas (NEGATIVE)

Exercises the **G-personas** non-skippable guard (state-machine.md G-personas / T2): the human
persona-selection gate (Phase 1) cannot be skipped — the validator requires
`gates.personas_confirmed=true` backed by a VALID `personas.json` from Phase 2 onward.

The run presents post-Phase-1 work (`clarifications`, `cartography`, `graph`, `units`,
`learnings`) at phase `P6_EXECUTE_VERIFY` but ships **no** `personas.json`, so the persona gate
was skipped. This fires two complementary checks.

EXPECTED: exit 1 with
`FAIL G-personas non-skippable: run shows post-Phase-1 work […] but no VALID personas.json` and
`FAIL gate ordering: phase P6_EXECUTE_VERIFY requires gates ['personas_confirmed'] = true`,
and no Python traceback.
