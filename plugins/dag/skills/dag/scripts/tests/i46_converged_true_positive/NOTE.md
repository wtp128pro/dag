# Fixture: i46_converged_true_positive (GREEN / positive-assertion control — spec §4.2)

Phase `DONE`, all five gates true including `signoff_confirmed: true`; `units/U01/verify.json`
`verdict: "PASS"` with `converged: **true**`, iterations matched.

PROVES two things the exit code alone cannot:
1. `converged` identity semantics on the OTHER side of the boundary: `v.get("converged") is False` is
   an identity test (§4.1), so `converged: true` must not arm P4.
2. P4's **adoption-scoped positive assertion** (§4.2) actually EMITS when at least one verify carries
   a `converged` key and no arm fired. Without this row a materialization/adoption-armed predicate is
   indistinguishable from a silently-skipped one.

EXPECTED: exit 0 AND stdout contains
`I46 non-converged PASS (1 verify doc(s) declare converged`.

DOES NOT COVER: the multi-doc count (`N` is 1 here, so an off-by-one in the tally is invisible); the
zero-adoption case where NO verify carries `converged` and P4 must emit nothing at all (see
`i46_no_converged_key`).

