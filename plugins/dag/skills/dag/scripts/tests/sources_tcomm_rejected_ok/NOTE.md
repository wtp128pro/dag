# Fixture: sources_tcomm_rejected_ok (POSITIVE — I26 sources register, RT-7 honest path)

A `good/` copy with a REJECTED `T-COMM` row referencing an `admitted:false` venue — the honest
failed-admission record the §4 overturn path depends on. Check 5 requires only a resolvable
`venue_ref` for a rejected row (admitted:true NOT required), so I26 PASSes. The advisory
`N-I26 (external tiers unconsulted)` NOTE fires (an external tier present, none consulted) — it
never changes the exit.

EXPECTED: exit 0, `PASS I26 sources register`, no FAIL line. expectations.tsv pins the empty substring.
