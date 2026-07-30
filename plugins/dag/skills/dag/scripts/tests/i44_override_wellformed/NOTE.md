# Fixture: i44_override_wellformed (GREEN — the recorded override downgrades FAIL to NOTE; spec §2.3/§2.5 P2-G3)

Identical to `i44_absent_verify_any_phase` (signed off, `units/U01` executed with NO verify.json)
plus a WELL-FORMED `accepted_incomplete` object at the top level of `fsm-state.json` naming exactly
`["U01"]`, with non-blank `rationale`, `decision_ref: "DECISIONS.md#accepted-incomplete-2026-07-29"`
(containing the literal `DECISIONS.md`), and a real `DECISIONS.md` present in the run dir — i.e. all
six downgrade conditions (1)-(6) of §2.3 hold.

PROVES: the 2026-07-29 human decision (further verification offered, declined, signed off knowingly)
stays AVAILABLE, and the override converts the hard FAIL into an exit-neutral NOTE **without ever
suppressing the emission**. The pin is the NOTE line, so an implementation that downgrades by
`continue` — silently — fails this row instead of passing it. That is the whole design intent:
legibility, not prohibition.

EXPECTED: exit 0 AND stdout contains
`N-I44 sign-off closure (accepted-incomplete override) (units/U01)`.

DOES NOT COVER: the over-broad-override NOTE (`units` naming an id that is not open — no surplus id
here); the per-unit coverage rule when `units` omits an open unit (see `i44_override_partial`); the
non-`str` element rule from condition (2); conditions (5)/(6) failing independently.

