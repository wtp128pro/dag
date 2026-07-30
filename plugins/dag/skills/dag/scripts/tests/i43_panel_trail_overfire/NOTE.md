# Fixture: i43_panel_trail_overfire (GREEN / over-fire control — spec §0.3, §1.6 P1-G1 **in full**)

This is §1.6 **P1-G1** realised completely, which `i43_current_positive` is not: that fixture ships
only P1-G1's *silent-skip* half (a `P1-ok` row to assert on) and its own NOTE.md says so
("DOES NOT COVER: the aggregation channel (no `verify_p*.json` present …) — §0.3").

Bytes: `phase: "DONE"`, all five gates true including `signoff_confirmed`; `units/U01/debrief.json`
`iteration: 3`; `units/U01/verify.json` `iteration: 3`, `verdict: "PASS"`; **plus** the panel audit
trail `units/U01/verify_p1.json` (`iteration: 1`), `verify_p2.json` (`iteration: 2`),
`verify_p3.json` (`iteration: 3`) — each schema-valid against `verify.schema.json`,
`unit_id: "U01"`, `executor_reasoning_seen: false` (the D-04 blindness attestation).

PROVES two things at once, which is why the spec designates exactly this case:

1. **§0.3 — the normative `verify_p*` prohibition.** *"No predicate in this spec may open, stat, glob
   or read any `units/<u>/verify_p*.json`. The implementation must contain zero reference to
   `verify_p`."* An implementation that resolved the verify iteration by globbing `verify_p*` and
   taking the MIN reads `iteration: 1`, computes `SUPERSEDED` against `debrief.iteration: 3`, and —
   since `phase DONE` + `signoff_confirmed: true` puts the unit outside the in-flight carve-out —
   emits `FAIL  I43 verification currency (units/U01)` and exits 1. Both rows for this dir then go
   red: the positive pin (`… iteration 3 verified`) is absent AND the negative pin
   (`!FAIL  I43 verification currency`) is violated.
   **Demonstrated by mutation, not asserted** (iteration 2): in a `/tmp` copy of the scripts tree the
   verify-iteration accessor was shadowed by a `verify_p*` glob taking the MIN. Result — this dir
   goes RED (`exit 1`, `debrief.iteration=3 but the aggregated verify.iteration=1 … SUPERSEDED`)
   while `i43_current_positive` and every other pre-existing row in this family stays GREEN, i.e.
   before this fixture existed the §0.3 violation was invisible to the whole suite.
2. **The silent-skip half.** The `P1-ok` positive assertion must actually EMIT on the clean path
   (§0.7's last bullet: a GREEN control asserting only `exit == 0` is inadmissible for a
   materialization-armed predicate).

EXPECTED: exit 0, stdout contains `I43 verification currency (units/U01: iteration 3 verified)`,
and stdout does **not** contain `FAIL  I43 verification currency` (two rows; the second uses the
`!`-prefixed must-NOT-contain pin at `run_tests.sh:104-113`).

DOES NOT COVER: an implementation that reads `verify_p*` and takes the **MAX** — here `verify_p3` is
`iteration: 3`, so the MAX coincides with the aggregated verify and this fixture stays green. That
violation of §0.3 is behaviourally invisible on any trail whose newest member matches the aggregate,
and a witness for it needs a trail whose newest member is AHEAD of `verify.json`, which is itself a
P1-b shape and would confound the two assertions. Also not covered: the multi-unit case; a
`verify_p*` file that is schema-INVALID or `unit_id`-mismatched (the pre-existing D-04
validate-if-present block FAILs those on their **own** label, so they are not this predicate's
domain); the `sorted()` domain order.
