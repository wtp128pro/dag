# Fixture: resolution_missing (NEGATIVE — I25 resolution present, the F7 defect)

Exercises the **I25 resolution-present mirror + the U05 schema conditional**: a `material`
register item with `resolved: true` and NO `resolution` key. The rest of the register is
untouched from the `good/` copy (items 1-2 stay resolved-with-text), so nothing trips for the
wrong reason. The injected doc is schema-INVALID once the U05 conditional lands, so which
layer reports first differs by backend; per the plan's stability convention the pinned
substring is the backend-stable FIELD TOKEN `resolution` — jsonschema says
`'resolution' is a required property`, the mini backend says `missing required property
'resolution'`, and the I25 mirror line
`FAIL I25 resolution present (3): material item marked resolved carries no resolution text`
contains it too.

Because the doc is schema-invalid, two inherent companion lines accompany the mirror on a
full run: the schema-layer FAIL naming `resolution` and the pre-existing I-dod line ("no VALID
clarifications.json ..."). All three problems root in the ONE injected item — nothing else in
the run is defective.

EXPECTED: exit 1, substring `resolution` under BOTH backends, no Python traceback.
