# Fixture: sources_coverage_unread_basis (NEGATIVE — I26 sources register, check 6 coverage linkage)

A `good/` copy with a consulted row (S1) plus a `queued` row (S2), where the coverage claim's
`based_on` cites ONLY S2. Every id is a valid member, but the claim rests on no CONSULTED row — an
all-unopened basis. Check 6's second clause FAILs (you cannot claim coverage via sources you never
opened). Membership, not relevance (RT-1): a consulted member would pass.

EXPECTED: exit 1, `FAIL I26 sources register (coverage linkage)`.
expectations.tsv pins `I26 sources register (coverage linkage)`.
