I41-3, the non-blank-rationale arm. A member `major` on a PASS IS named by a `dispositions[]` entry
with an EXCUSED disposition (`withdrawn`) — but its rationale is whitespace only. Spec 2.4 requires the
rationale to be non-blank UNDER `.strip()`, so `"   "` must not excuse the major; an unreasoned
disposition is the laundering surface the clause exists to close.

The rationale is deliberately `"   "` and not `""`: `""` is rejected by the schema
(`dispositions.items.rationale.minLength: 1`), which would make this a schema fixture rather than an
I41-3 fixture, and it would not pin `.strip()` — a presence-only check (`"rationale" in x`) passes on
`"   "` and fails only here. Every other clause is satisfied (see panel_upheld_on_pass for the same
isolation argument). Exit 1 on `unexplained major`.
