# Work Graph — amend-ok fixture (revision 3)

## Dependency DAG (edge A→B = B consumes A)
```
U01 → U03
U01 → U04
U01 → U05
```
(no cycles — verified; graph.json is authoritative)

## Amendments
| Amendment | Kind | Origin (trigger) | Fuel cost | Units added | Units retired | DoD refs |
|-----------|------|------------------|-----------|-------------|---------------|----------|
| A01 | add_units | debrief_handoff (U01) | 1 | U03 | — | the coverage gap U01 surfaced is handled by a dedicated unit |
| A02 | split_unit | footprint_breach (U02) | 1 | U04, U05 | U02 | every planned unit is briefable within the 32K budget |

Fuel: initial 2 → remaining 0 (Σ fuel_cost = 2). Revision 3 = 1 + 2 amendments.
