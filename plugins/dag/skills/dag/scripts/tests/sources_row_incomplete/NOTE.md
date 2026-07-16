# Fixture: sources_row_incomplete (NEGATIVE — I26 sources register, check 4 row completeness)

A `good/` copy whose one `consulted` row has `yielded: " "` (a single space). The schema's
`minLength:1` ACCEPTS the whitespace; the I26 raw-parse `.strip()` bar REJECTS it (the I25/G11
two-layer precedent — whitespace-only text the schema admits is still a blank).

EXPECTED: exit 1, `FAIL I26 sources register (row S1 completeness)`.
expectations.tsv pins `I26 sources register (row S1 completeness)`.
