# I53-4 — the arm that was DEAD CODE, and the fixture that proves it is not any more

`units/U01` is EXECUTED (it holds a debrief), its `graph.json` entry carries no `priority_class` —
which the graph schema stipulates means `normal` — and its **frozen** `brief.json` claims
`"directive"`. That is precisely the drift I53-4 exists to catch: a unit quietly acquiring priority
provenance after dispatch.

**Before this fixture the arm could never fire.** `brief.schema.json` is `additionalProperties: false`
and did not declare `priority_class`, so a brief carrying the key was schema-INVALID, never entered
`unit_docs`, and I53-4's own `"priority_class" not in _b` guard skipped every unit on every run —
while the invariant text advertised it as riding the existing I17 content anchor and **STRENGTHENING**
the frozen prefix. It strengthened nothing, and no fixture covered it. The key is now a declared
OPTIONAL property (a widening: no archived brief becomes invalid).

Its green twin is `directive_ok`, identical but for this one key.
