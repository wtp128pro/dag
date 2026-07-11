# Fixture: guardrail_block_partial (NEGATIVE — I22 adoption closure)

Exercises the **I22 guardrail compliance adoption-closure clause**: once ANY verdict-bearing
verify carries the `guardrail_compliance` block, EVERY verdict-bearing verify must. Copied
from `good/` and extended (the COPY, never `good/` itself) with a fully-materialized
`units/U02/` (brief + debrief + PASS verify; fsm-state marks both units passed) so I9/I2/G-brief
and the ledger checks stay green and nothing trips for the wrong reason. U01's verify carries a
compliant block (row verbatim + respected). Sole injected defect: U02's verdict-bearing
`verify.json` lacks the block.

EXPECTED: exit 1 with the single operative failure
`FAIL I22 guardrail compliance: adoption closure: verifies missing the block: ['U02']`
and no Python traceback. expectations.tsv pins substring `I22 guardrail compliance`.
