# panel_missing — NEGATIVE (RESULT: FAIL, I16 clause (a))

`U01` is tagged `high-stakes` but its `verify.json` carries **no `panel[]`**. I16 requires a panel on
a high-stakes unit.

Expected: **exit 1**, with
`FAIL  I16 panel discipline (units/U01): unit is tagged high-stakes but verify.json carries no panel[]`.
