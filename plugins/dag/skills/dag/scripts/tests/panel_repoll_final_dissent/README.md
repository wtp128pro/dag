I41-4c, the FINAL-panel-verdict disjunct (the sibling of panel_repoll_dissenter, which pins the
`pre_verdict` disjunct). The re-poll names the correctness lens, whose FINAL `panel[]` verdict is FAIL;
its `pre_verdict` is PASS and `tested_defect` is false, so NEITHER of the other two disjuncts of
"cast a dissenting vote" can fire. Dropping `panel[lens].verdict in {FAIL, DISAGREE}` from the
implementation therefore turns this fixture GREEN — which is exactly what it pins. The two fixtures
together pin the UNION reading spec 2.4-4c mandates; neither alone does.

Isolation: I41-4d holds in both arms (`panel[correctness].verdict == post_verdict == FAIL`, and the
discrete majority recomputed over [FAIL, PASS, PASS] is PASS == the top verdict), I41-4e holds
(`verify_rounds: 2`), I41-2 holds (the dissenter carries a defect), and the member defect is `minor`
so I41-3 is silent. Exit 1 on `repoll of dissenter`.
