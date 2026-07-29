I41-2(c): stamped 1.11.0, panel `[DISAGREE, PASS, PASS]` on an aggregate PASS (I16 forces the PASS), and
the `DISAGREE` member records NOTHING — no `summary`, no `defects[]`. AO-3 lets a `DISAGREE` name no
acceptance criterion; it does not let it say nothing. Deliberately SATISFIES I41-1 (a legal
`panel_adjudication` IS present) so I41-1 cannot mask it, carries no `blocker`/`major` so I41-3 cannot,
and is `resolution: "withdrawn"` so 4a-e are all legal. Exit 1 on `bare disagree`, exactly one FAIL.

Removing arm (c) ⇒ exit 0 ⇒ pinned. No other fixture in the tree carries a `DISAGREE` panel member, so
the still-RED set is EMPTY: with (c) gone, nothing else detects it. Paired with
`panel_dissent_disagree_ok`, which is the regression test for the narrowing (see its README).
