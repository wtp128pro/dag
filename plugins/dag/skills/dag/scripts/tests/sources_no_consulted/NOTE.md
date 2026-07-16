# Fixture: sources_no_consulted (NEGATIVE — I26 sources register, check 2 consulted floor)

A `good/` copy whose `sources.json` maps one `queued` row and ZERO `consulted` rows — a listing,
not cartography. Check 2 (consulted floor) FAILs; the coverage row resting on the unopened id also
trips check 6. The register is schema-VALID, so only the I26 raw-parse predicate bites.

EXPECTED: exit 1, `FAIL I26 sources register (consulted floor)`.
expectations.tsv pins `I26 sources register (consulted floor)`.
