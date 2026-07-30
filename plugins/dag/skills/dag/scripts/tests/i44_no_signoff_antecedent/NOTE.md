# Fixture: i44_no_signoff_antecedent (GREEN over-fire control — the antecedent; spec §2.5 P2-G2)

Phase `P6_EXECUTE_VERIFY`, `gates.signoff_confirmed` **ABSENT**; `units/U01/debrief.json` present,
NO `verify.json`, `fsm.units[U01].status: "verifying"`.

PROVES: with `SIGNED_OFF` false, P2 is **entirely silent** — not merely non-fatal. The identical
artifact shape RED-flags in `i44_absent_verify_any_phase`, whose ONLY difference is the gate flag, so
the pair isolates the antecedent from every artifact condition. An implementation that keys P2 on
"phase is terminal" or on `_fsm_unit_status` rather than on the gate fires here and fails the row.
Per §2.1(i), P2 must not read `_fsm_unit_status` for any DECISION — only to interpolate it into a
FAIL's detail — because status-keyed formulations newly RED 3 archived runs for cosmetic desync.

Pinned substring is `RESULT: PASS` (an absence assertion is not expressible in `expectations.tsv`),
which additionally proves the pass reached its verdict rather than aborting inside a new block.
I9's own in-flight NOTE at `:5596` may still emit — its absence is deliberately NOT asserted.

DOES NOT COVER: `signoff_confirmed` present-and-`false` (identity vs presence — the I43 twin
`i43_inflight_signoff_false` covers that distinction for P1 but no P2 fixture does); a non-dict
`gates` (§0.5.2).

