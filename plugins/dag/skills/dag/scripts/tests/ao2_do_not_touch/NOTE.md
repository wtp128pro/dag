# Fixture: ao2_do_not_touch (NEGATIVE — I14 / AO-2)

Exercises the **I14 AO-2 do_not_touch disjointness** check (added in U02, post-hoc/offline in
`validate_run.py`): on a RETRY (`debrief.iteration > 1`) no defect may name a criterion the
prior iteration marked correct / off-limits. The prior-iteration `do_not_touch` set is read from
the debrief echo `debrief.prior_feedback.do_not_touch` (the validator retains only the latest
`verify.json`, so per-iteration verify files are NOT assumed — see CARTOGRAPHY R5).

The run is otherwise valid — copied from `good/` (persona gate, gate ordering, I3, I-dod, I12 all
PASS) — so it does not trip anything for the wrong reason. Its **sole** injected defect:
`units/U01/debrief.json` is an `iteration:2` retry whose `prior_feedback.do_not_touch` contains
the acceptance criterion `"each with >=1 dated primary source"`, and `units/U01/verify.json`
(`verdict: FAIL`) files a defect against that **same** criterion — the retry re-opened what the
prior iteration accepted. (The criterion is a real member of `brief.acceptance_criteria`, so I6
PASSes; `prior_feedback.changes_made` is non-empty, so I15 PASSes — isolating I14.)

EXPECTED: exit 1 with the single operative failure
`FAIL I14 AO-2 do_not_touch disjointness (units/U01): defect criteria ['each with >=1 dated
primary source'] intersect prior_feedback.do_not_touch …` and no Python traceback.

## Documented Limitation (L1) — presence half CLOSED by PR-6
Formerly a retry that **OMITTED the `prior_feedback` block entirely** (or omitted `do_not_touch`)
EVADED this check. PR-6 makes the echo — including the `do_not_touch` field — schema-mandatory on
`iteration>1` (`debrief.schema.json` `allOf`), so the omit-the-block evader now fails CLOSED at the
schema layer (see `retry_no_echo`). What remains (Limitation F, narrowed): I14 still compares the
executor's **self-reported** `do_not_touch` against the single retained `verify.json` — a post-hoc
validator has no per-iteration verify history to reconstruct the authoritative prior set, so the
*content*'s genuineness stays verifier/human judgment.
