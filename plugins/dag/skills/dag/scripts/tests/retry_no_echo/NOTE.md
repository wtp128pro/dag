# Fixture: retry_no_echo (NEGATIVE — IMP-05 / Task 6.2)

Closes the "evasion by omission" half of **Limitation F**. I14/I15 (the offline AO-2/AO-6 checks)
were **presence-gated**: a retry that omitted the whole `prior_feedback` block was *skipped*, not
failed. PR-6 makes the echo **schema-required on retries**: `debrief.schema.json` now carries an
`allOf` clause `iteration>=2 ⇒ required prior_feedback` (with `changes_made` non-empty and
`do_not_touch` present inside it).

Copied from `good/`; its **sole** injected defect: `units/U01/debrief.json` is an `iteration:2`
retry with the entire `prior_feedback` block **removed** (today's evader).

EXPECTED: exit 1 with the single operative failure
`FAIL units/U01/debrief.json: $: missing required property 'prior_feedback'` and no Python
traceback. (A schema-invalid retry debrief is dropped before I14/I15, so this now fails CLOSED at
the schema layer — the load-bearing gate — while I14/I15 remain the semantic backstop over
schema-valid retries.) Companion: `ao6_no_changes` (echo present but `changes_made` omitted).
