I41-2(c), the `minimal_repro` DISJUNCT. The `DISAGREE` member carries **no `summary` at all**; it
substantiates its dissent through a `defects[]` entry whose `minimal_repro` is non-blank. Expected exit 0.

Why it exists: (c) is a DISJUNCTION — "a non-blank `summary` OR a `defects[]` entry with a non-blank
`minimal_repro`" — and `panel_dissent_disagree_ok` satisfies only the FIRST disjunct. Drop the
`minimal_repro` disjunct from the predicate and every negative fixture stays red (a dropped disjunct
over-fires, it does not under-fire), so the suite's negative half is structurally blind to it; **this
fixture is the only thing in the tree that turns RED.** It is the same over-fire blindness the green
controls exist for, one level down inside a single clause.

It also demonstrates the spec's "welcome to, never obliged to": the member DOES name a criterion here, and
that is legal — the criterion is simply not what (c) reads.

Note this fixture is green under the pre-CR-1 predicate too (which accepted the non-blank criterion), so it
is not a regression test for the narrowing; it pins the disjunct against ablation, and the ablation harness
arm `I41-2c-repro` records that pin.
