# Fixture: i44_override_partial (RED — the per-unit coverage rule; spec §2.3 / §2.5 P2-R3)

Built on the two-unit `i9_midloop_note/` spine. `gates.signoff_confirmed: true`; BOTH `U01` and
`U02` are executed (debrief present) with NO `verify.json`. A well-formed `accepted_incomplete`
names exactly `["U01"]`, with non-blank `rationale`, `decision_ref` containing `DECISIONS.md`, and
`DECISIONS.md` present.

PROVES: coverage is evaluated **PER UNIT**. There is no blanket form — an override cannot be written
to mean "all open units". The override downgrades the unit it NAMES (U01 -> exit-neutral
`N-I44 ... (accepted-incomplete override)`) and leaves the unit it OMITS (U02) as a **hard FAIL**.
An implementation that treats a well-formed override as a global mute exits 0 here and passes; that
is the class this fixture exists to catch.

EXPECTED: exit 1 AND a FAIL row labelled `I44 sign-off closure (units/U02)`, with **no** FAIL row for
U01 (U01 appears as the override NOTE instead).

DOES NOT COVER: an override naming a unit that is not open at all (the over-broad NOTE); ordering of
the emitted rows; the case where the override names SOME but not all of three-or-more open units
beyond the 1-of-2 shape shipped here.

