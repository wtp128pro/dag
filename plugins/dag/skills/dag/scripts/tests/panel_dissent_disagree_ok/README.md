I41-2(c) COMPLIANT-PATH control — not an ordinary green control. The `DISAGREE` member substantiates its
dissent with a non-blank `summary` and names NO criterion anywhere; under AO-3
(`self-learning-loops.md:299-302`, `:601-604`) that is the MANDATED route for a critique that cannot name
one, so this artifact MUST be legal. Expected exit 0.

This is the regression test for the AO-3 `DISAGREE`-route narrowing (invariant-spec §2.7 / §10 CR-1): under
the pre-narrowing predicate — where the criterion obligation read `_I41_DISSENT = ("FAIL","DISAGREE")` —
this fixture exits **1** with `bare dissent`, because the only compliant artifact would have been the
criterion the panelist could not produce. It exits 0 only once the obligation is scoped to
`_I41_CRITERION_BOUND = ("FAIL",)` and I41-2(c) takes over. Restore the wider tuple and this fixture turns
RED — that is what it pins.
