# Fixture: i44_no_signoff_antecedent (GREEN over-fire control — the antecedent; spec §2.5 P2-G2)

Phase `P6_EXECUTE_VERIFY`, `gates.signoff_confirmed` **ABSENT**; `units/U01/debrief.json` present,
NO `verify.json`, `fsm.units[U01].status: "verifying"`.

PROVES: with `SIGNED_OFF` false, P2 is **entirely silent** — not merely non-fatal. The identical
artifact shape RED-flags in `i44_absent_verify_any_phase`, whose ONLY difference is the gate flag, so
the pair isolates the antecedent from every artifact condition. An implementation that keys P2 on
"phase is terminal" or on `_fsm_unit_status` rather than on the gate fires here and fails the row.
Per §2.1(i), P2 must not read `_fsm_unit_status` for any DECISION — only to interpolate it into a
FAIL's detail — because status-keyed formulations newly RED 3 archived runs for cosmetic desync.

EXPECTED (two rows, iteration 2). This substrate emits **no row of P2's own** at any severity — not
even §2.4's positive assertion, because the antecedent gates the whole predicate — so there is no
positive substring to pin here, and the `RESULT: PASS` row is retained as a *liveness* assertion (the
pass reached its verdict rather than aborting inside a new block, §0.5 R6). The real assertion is the
second row, a must-NOT-contain pin on `I44 sign-off closure`: no `I44` row of **any** severity, which
is exactly §2.5 P2-G2's wording and which the presence-only harness could not express before
`run_tests.sh:104-113` landed. The negative substring omits the `N-` prefix deliberately, so it forbids
the NOTE rows as well as the FAILs.
I9's own in-flight NOTE at `:5596` may still emit — its absence is deliberately NOT asserted.

DOES NOT COVER: `signoff_confirmed` present-and-`false` (identity vs presence — the I43 twin
`i43_inflight_signoff_false` covers that distinction for P1 but no P2 fixture does); a non-dict
`gates` (§0.5.2).

