# Fixture: i44_override_malformed (RED — the valve FAILS CLOSED; spec §2.3 fail-closed rule / §2.5 P2-R4)

Identical to `i44_override_wellformed` except `accepted_incomplete.rationale` is `"   "` — present, a
`str`, but blank after `.strip()`, so downgrade condition (3) is unmet while (1),(2),(4),(5),(6) all
hold.

PROVES the fail-closed posture, in both halves:
1. **No unit is downgraded.** U01 must still carry its own hard FAIL `I44 sign-off closure
   (units/U01)`. A malformed override may never silently suppress.
2. **Exactly one ADDITIONAL hard FAIL fires**, labelled `I44 sign-off closure
   (accepted_incomplete malformed)`, naming the FIRST unmet condition by number — (3) here.
It also pins §0.5: a malformed override must never CRASH, and a crash inside the new block would
silently disable every downstream predicate (R6).

EXPECTED (two rows, iteration 2): exit 1 AND a FAIL row labelled `I44 sign-off closure
(accepted_incomplete malformed)` — the arm unique to this fixture — **and** exit 1 with
`I44 sign-off closure (units/U01)`, which is the NO-DOWNGRADE half. §2.5 P2-R4 requires all three
assertions ("exit 1, AND a FAIL row … naming condition (3), AND U05 still carries its own
`I44 sign-off closure (units/U05)` FAIL (no downgrade)"); iteration 1 pinned only the first, so the
fail-closed property held but was unasserted. Measured, both rows are present here:
`FAIL  I44 sign-off closure (accepted_incomplete malformed): … unmet condition (3) …` and
`FAIL  I44 sign-off closure (units/U01): ABSENT verification … (arm a; …)`. (The spec's U05/U07 unit
ids are realised as U01/U02 — the shape, not the ids, is the requirement; recorded as a deviation.)

DOES NOT COVER: conditions (1),(2),(4),(5),(6) failing — each needs its own witness and only (3) is
shipped; whether the detail names the condition NUMBER (the stem pin cannot check the number);
`accepted_incomplete` present as a non-dict (e.g. a list or a string), which is condition (1).

