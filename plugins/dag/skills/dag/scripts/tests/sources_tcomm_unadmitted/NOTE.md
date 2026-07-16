# Fixture: sources_tcomm_unadmitted (NEGATIVE — I26 sources register, check 5 venue linkage)

A `good/` copy with a CONSULTED `T-COMM` row whose `venue_ref` resolves to a venue with
`admitted: false`. Check 5's one-directional rule: a consulted/queued T-COMM row must link to an
`admitted:true` venue. (The converse is legal and is pinned by sources_tcomm_rejected_admitted_ok.)

EXPECTED: exit 1, `FAIL I26 sources register (venue linkage S1)`.
expectations.tsv pins `I26 sources register (venue linkage S1)`.
