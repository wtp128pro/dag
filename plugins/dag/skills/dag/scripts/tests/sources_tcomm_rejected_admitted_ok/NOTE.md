# Fixture: sources_tcomm_rejected_admitted_ok (POSITIVE — I26 check 5 one-directional reading)

A `good/` copy with a REJECTED `T-COMM` row referencing an `admitted:true` venue. Pins check 5 as
ONE-directional, never a biconditional: a rejected row referencing an admitted venue is legal
(the venue is sound; this particular source was rejected as off-topic). I26 PASSes. The advisory
`N-I26 (external tiers unconsulted)` NOTE fires and never changes the exit.

EXPECTED: exit 0, `PASS I26 sources register`, no FAIL line. expectations.tsv pins the empty substring.
