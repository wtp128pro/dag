# Fixture: sources_venue_blank_k (NEGATIVE — I26 sources register, check 5b venue rationale)

A `good/` copy with a `venues[]` entry whose `k_a` is `" "` (a single space). The schema's
`minLength:1` ACCEPTS it; the I26 `.strip()` bar REJECTS it. Check 5b applies to EVERY venue,
admitted or refused — a refusal with blank rationale is as unaccountable as an admission with one.

EXPECTED: exit 1, `FAIL I26 sources register (venue rationale V1)`.
expectations.tsv pins `I26 sources register (venue rationale V1)`.
