# Fixture: sources_dup_id (NEGATIVE — I26 sources register, check 3 id uniqueness)

A `good/` copy with two `sources[]` rows sharing `id: "S1"` (the I3 dup-unit-id precedent —
duplicates make reference resolution order-dependent). Schema does not enforce uniqueness, so the
register is schema-VALID; the I26 raw-parse predicate is the only layer that bites.

EXPECTED: exit 1, `FAIL I26 sources register (id uniqueness)`.
expectations.tsv pins `I26 sources register (id uniqueness)`.
