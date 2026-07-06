# Fixture: ao6_no_changes (NEGATIVE — I15 / AO-6)

Exercises the retry **`changes_made` requirement** — schema-enforced since PR-6, formerly the
offline **I15 AO-6 responsive change** check (added in U02): a RETRY (`debrief.iteration > 1`) MUST
record >=1 concrete change made in response to the prior verdict
(`debrief.prior_feedback.changes_made` present and non-empty). An empty/absent `changes_made` on a
retry means the loop re-ran without responding — silent oscillation.

The run is otherwise valid — copied from `good/` — so nothing trips for the wrong reason. Its
**sole** injected defect: `units/U01/debrief.json` is an `iteration:2` retry whose
`prior_feedback` carries `actionable_changes` and `do_not_touch` but **omits `changes_made`**.
`verify.json` stays `verdict: PASS` (defects `[]`).

EXPECTED (since PR-6): exit 1 with the single operative failure
`FAIL units/U01/debrief.json: $.prior_feedback: missing required property 'changes_made'` and no
Python traceback. The "changes_made non-empty on a retry" rule is now **schema-enforced**
(`debrief.schema.json` `allOf`: `iteration>=2 ⇒ prior_feedback.changes_made minItems:1`). Because a
schema-invalid retry debrief is dropped before the per-unit checks, **I15 (the offline AO-6
backstop) is SUBSUMED for this case** and is no longer the reporting layer — it now fires only over
schema-valid retries, which always carry non-empty `changes_made`.

## Documented Limitation (L1) — CLOSED by PR-6
Formerly: I14/I15 failed CLOSED only when the retry data was present, so a retry that OMITTED the
`prior_feedback` block entirely EVADED both. PR-6 closes this **presence** half by making the echo
schema-mandatory on `iteration>1` (`debrief.schema.json` `allOf`); the omit-the-whole-block evader
is now caught at the schema layer — see the `retry_no_echo` fixture. What remains (Limitation F,
narrowed): the echo's *content* stays executor-attested — I14 compares a self-reported
`do_not_touch`, and the genuineness of `changes_made` is not machine-checkable.
