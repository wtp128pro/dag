# Fixture: sources_ok (POSITIVE — I26 sources register, the canonical floor register)

A `good/` copy whose `sources.json` is VERBATIM the PLAN §5.1 canonical floor register (LIGHT tier):
presence + consulted floor + linked coverage — one consulted T-LOCAL row, one coverage claim resting
on it. So the documented floor and the positive-control fixture can never drift apart (PR-5). No
venues, no external tiers, one coverage row — every I26 check and NOTE stays silent-or-green.

EXPECTED: exit 0, `PASS I26 sources register`, no FAIL/NOTE line. expectations.tsv pins the empty substring.
