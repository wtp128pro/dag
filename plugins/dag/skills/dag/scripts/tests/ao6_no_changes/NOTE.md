# Fixture: ao6_no_changes (NEGATIVE — I15 / AO-6)

Exercises the **I15 AO-6 responsive change** check (added in U02, post-hoc/offline in
`validate_run.py`): a RETRY (`debrief.iteration > 1`) that records a `prior_feedback` echo MUST
also record >=1 concrete change made in response to the prior verdict
(`debrief.prior_feedback.changes_made` present and non-empty). An empty/absent `changes_made` in a
populated `prior_feedback` block means the loop re-ran without responding — silent oscillation.

The run is otherwise valid — copied from `good/` — so nothing trips for the wrong reason. Its
**sole** injected defect: `units/U01/debrief.json` is an `iteration:2` retry whose
`prior_feedback` carries `actionable_changes` and `do_not_touch` but **omits `changes_made`**.
`verify.json` stays `verdict: PASS` (defects `[]`), so I14 is a trivial disjoint PASS — isolating
I15.

EXPECTED: exit 1 with the single operative failure
`FAIL I15 AO-6 responsive change (units/U01): iteration>1 with a prior_feedback echo but
changes_made is absent/empty …` and no Python traceback.

## Documented Limitation (L1)
Like I14, I15 fails **CLOSED only when the retry data is present** — it is gated on the presence
of the `prior_feedback` echo. A retry that OMITS the `prior_feedback` block entirely currently
EVADES BOTH I14 and I15 (there is no responsive-change record for this post-hoc check to audit).
Closing it requires making the `prior_feedback` echo mandatory on `iteration>1` (a schema/
discipline change outside U07's tests-only scope).
