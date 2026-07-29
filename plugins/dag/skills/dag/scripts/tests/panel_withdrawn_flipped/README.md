The SECOND legal encoding of a withdrawn dissent: the withdrawing lens records the withdrawal as its
FINAL `panel[]` vote (PASS) rather than leaving a dissenting final row. `panel_withdrawn_note` carries
the other encoding (the final row still dissents).

This fixture exists to make the shipped implementation's `_dis` conjunct in N-I41 VISIBLE and testable
(DIVERGENCE 7 in the U07 debrief): the shipped trigger is
`resolution == "withdrawn" and not repoll and _dis`, one conjunct stronger than spec 2.4's stated
trigger, so on THIS encoding the advisory NOTE is silent. That silence is deliberate (a flipped final
vote is a recorded position change, not the rubber-stamp signature) and it is exit-neutral either way —
which is precisely why expectations.tsv (exit code + required substring only) CANNOT pin it. The pin
lives in artifacts/i41_i42_ablation.py as a FORBID check: drop `_dis` and this fixture starts emitting
`N-I41 (dissent withdrawn`. Everything else is legal, so exit 0 also guards against over-firing.
