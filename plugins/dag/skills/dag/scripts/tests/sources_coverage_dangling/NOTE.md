# Fixture: sources_coverage_dangling (NEGATIVE — I26 sources register, check 6 coverage linkage)

A `good/` copy whose one coverage claim's `based_on` cites `S9`, an id that appears in no
`sources[]` row. Check 6 (membership) FAILs — a coverage claim cannot rest on a source that was
never registered.

EXPECTED: exit 1, `FAIL I26 sources register (coverage linkage)`.
expectations.tsv pins `I26 sources register (coverage linkage)`.
