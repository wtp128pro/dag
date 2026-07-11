# Fixture: legacy_prefeature_ok (POSITIVE — legacy-shape run, no retro-fail)

Version-skew negative control for the whole guardrails-1.8.0 family (DoD5 / Non-Goal 6): a
minimal PRE-FEATURE run — a verbatim `good/` copy carrying NONE of the new fields (no
`dod_refs`, no `non_goal_refs`, no `guardrail_compliance` block anywhere) — stamped
`validator_version: "1.7.0"` in `fsm-state.json` (the last pre-guardrails release; the stamp
is schema-legal and NEVER gates a check). All six new invariants are presence/adoption-
triggered, so on this old-shape run they must stay literally silent: no I20/I21/I22/I23/I24/
I25 line of any kind, and the run stays green exactly as it did under the 1.7.0 validator.

EXPECTED: exit 0, `RESULT: PASS`, zero lines matching any guardrails-1.8.0 stem, no Python
traceback. expectations.tsv row has the empty substring per the header convention.
