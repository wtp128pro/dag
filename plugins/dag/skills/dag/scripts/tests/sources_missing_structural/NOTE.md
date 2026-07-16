# Fixture: sources_missing_structural (NEGATIVE — I26 sources register, check 1 presence)

A verbatim `good/` copy with `sources.json` REMOVED. `good/` carries structural work (graph.json +
units/ + cartography.json), so the I26 presence trigger fires and — fail-closed on absence — a
missing register is a FAIL (NOT archive-silent, the I-dod/I24 posture).

EXPECTED: exit 1, `FAIL I26 sources register (presence)`, no Python traceback.
expectations.tsv pins `I26 sources register (presence)`.
