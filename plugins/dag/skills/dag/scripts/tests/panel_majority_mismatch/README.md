# panel_majority_mismatch — NEGATIVE (RESULT: FAIL, I16 clause (b) — anti-softmax)

`U01`'s `panel[]` is all-`PASS` (discrete majority = `PASS`) but the top-level `verdict` is `FAIL`.
The aggregate must be the DISCRETE majority, never a softmaxed/overridden score — so this is rejected.

Expected: **exit 1**, with
`FAIL  I16 panel discipline (units/U01): top-level verdict='FAIL' != DISCRETE panel majority='PASS' — the aggregate must be the discrete majority (no softmax)`.
