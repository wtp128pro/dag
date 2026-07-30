I42-3, the PHASE conjunct of the transient window. The owning unit's status IS `verifying` — the half of
the I9 window that would excuse a digest drift — but the phase is `P7_DISAGREEMENT_GATE`, not
`P6_EXECUTE_VERIFY`. Spec 3.3: a mismatch is a hard FAIL "at every other phase, every other status, and
ALWAYS at P8/DONE". Drop the `phase == "P6_EXECUTE_VERIFY"` conjunct and this fixture is downgraded to a
NOTE and goes green. Paired with `digest_mismatch_p6_terminal` (which pins the status conjunct) and
`digest_mismatch_p6_note` (which pins the window itself). Exit 1 on `digest mismatch`.
