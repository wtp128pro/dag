# Fixture: graph_socratic_blank (NEGATIVE — D-07(b): I13 enforces the planner's counter too)

The graph.json twin of `cartography_socratic_blank`: proves the OPTIONAL `socratic` block added to
`graph.schema.json` (the planner/architect's landing place) is also I13-checked.

Copy of `good` with a `socratic` block on `graph.json` whose `counter` is `"tbd"` (a placeholder).

EXPECTED: exit 1 with `FAIL  I13 socratic counter (graph): counter 'tbd' records no OUTCOME
(blank/'n/a'); mechanical sentinel = 'unit is mechanical; no material premise to break'`, no traceback.
