# Fixture: cartography_socratic_blank (NEGATIVE — D-07(b): I13 enforces the cartographer's counter)

Proves the I13 enforcement half of D-07(b): a `socratic` block present in `cartography.json` must have a
`counter` that records an OUTCOME (not blank/'n/a'/placeholder) — exactly as I13 requires for
debrief/verify.

Copy of `good` with a `socratic` block on `cartography.json` whose `counter` is `"n/a"`.

EXPECTED: exit 1 with `FAIL  I13 socratic counter (cartography): counter 'n/a' records no OUTCOME
(blank/'n/a'); mechanical sentinel = 'unit is mechanical; no material premise to break'`, no traceback.
