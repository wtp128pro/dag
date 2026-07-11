# Fixture: register_empty_structural (NEGATIVE — I24 register floor)

Exercises the **I24 register floor**: once structural work exists (the I-dod trigger union —
here `graph.json` and the `units/` tree from the `good/` copy), an empty `ambiguity_register`
is a FAIL — the F8 finding's evasion stub reproduced VERBATIM from the audit:
`{"ambiguity_register": [], "definition_of_done": ["done"], "non_goals": ["none"]}`.
Copied from `good/` with `clarifications.json` replaced by that stub; no other artifact
touched, no unit adopts any guardrail field, so families A/B stay otherwise silent and
nothing trips for the wrong reason.

EXPECTED: exit 1 with the operative failure
`FAIL I24 register floor: ambiguity_register is empty after structural work exists; record real ambiguities or an explicit none-found item`
and no Python traceback. expectations.tsv pins substring `I24 register floor`.
