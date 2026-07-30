# Fixture: i44_override_quiet_control (GREEN control — the un-gated NOTE does NOT over-fire)

The `i44_override_quiet_visible` spine with the top-level `accepted_incomplete` object **deleted**
and nothing else changed: same phase, same gates (`signoff_confirmed: true`), same open
`units/U01` (executed debrief, NO `verify.json`), same `DECISIONS.md`. The single-variable contrast
is the point — the only difference from the RED row is the presence of the override key, so any
`N-I44 (accepted-incomplete override)` line here would be an over-fire attributable to the
un-gating itself rather than to a recorded human decision.

PROVES (mechanically, not by narration): with no override recorded, the un-gated
`_vc_override_note` emits NOTHING, and I44-a is still a hard FAIL under `--quiet` — un-gating is an
emission-channel change, not a downgrade of arming, severity or scope. The row uses the harness's
NEGATIVE pin (column 3 prefixed with `!`), so it cannot pass vacuously on `RESULT: FAIL` alone.

EXPECTED: exit **1** AND stdout (under `--quiet`) does NOT contain
`(accepted-incomplete override)`. (The `I44 sign-off closure (units/U01)` FAIL row is pinned
positively by the sibling `i44_absent_verify_any_phase`; `rep.fail` was never quiet-gated.)

DOES NOT COVER: a malformed-but-present override (`i44_override_malformed`); an override that omits
an open unit (`i44_override_partial`); a run with no sign-off antecedent at all
(`i44_no_signoff_antecedent`).
