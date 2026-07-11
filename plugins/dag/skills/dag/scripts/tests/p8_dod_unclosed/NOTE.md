# Fixture: p8_dod_unclosed (NEGATIVE — I23 DoD closure at DONE)

Exercises the **I23 closure DoD clause**: at P8/DONE (I10's phase condition) under WP-1
adoption, every `definition_of_done` item must be referenced by some PASS-verified unit's
`dod_refs`. Derived from the `guardrail_chain_ok` recipe (DONE phase, both units fully
materialized, I20/I21/I22 all green, mirrors consistent, blocks compliant) — so it does not
trip anything for the wrong reason. Sole injected defect: BOTH units' `dod_refs` cite DoD
item 1 only, leaving DoD item 2 ("the schema self-check (--self-check) passes") referenced by
no unit.

EXPECTED: exit 1 with the single operative failure
`FAIL I23 closure: DoD items referenced by no PASS-verified unit: ['the schema self-check (--self-check) passes']`
and no Python traceback. expectations.tsv pins substring `I23 closure`.
