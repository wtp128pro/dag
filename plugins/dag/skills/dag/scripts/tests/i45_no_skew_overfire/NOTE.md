# Fixture: i45_no_skew_overfire (RETAINED WITNESS, re-annotated to spec §3.5 **P3-G2′** per §9-R15)

**Re-annotated 2026-07-29 (iteration 2), discharging §9-R15.** The original stated expectation
("exit 0 AND **no** `N-I45` line", spec §3.5 **P3-G2**) was **WITHDRAWN by the spec** in its own
iteration 2: P3-G2 is not simultaneously satisfiable with §3.1(2), and §3.5 credits this fixture's
author with finding the conflict before the implementer did. The reporting behaviour is KEPT, P3-G2
is replaced by **P3-G2′** (count *composition*, asserted as the arm-id LIST), and the re-annotation
was assigned to whoever owns fixtures because U01 authors no fixture files (L11/L14). This is that
re-annotation. **The bytes are unchanged and must stay unchanged** — they are the witness.

WHAT THE BYTES ACTUALLY ARE. A minimal single-unit `DONE` run with **no** `validator_version` key at
all, and no *adoption* of any version-gated feature (no `panel[]`, no dialogue transcript, no
ask-first register, no anchor governance, no evidence digest, no I41 adjudication). **Correction to
iteration 1's description:** this dir is *not* a structure-free clone. It carries `cartography.json`,
`graph.json`, `GRAPH.md` and a `units/U01/` subtree, so `_i27_struct` **HOLDS** — which is why
`I27-T1` and `I35-I40-T1` are counted here alongside the two stamp-only arms. The earlier sentences
"byte-clone of `signoff_ok/`" and "no structural work for any version-gated arm" were factually
wrong and are deleted; §3.5's adjudication says the same thing ("`i45_no_skew_overfire` has a
`units/` subtree, so `_i27_struct` holds … P3-G2 was written against a mental model of the conjuncts
that the source text does not support").

WHAT IT NOW PROVES: that a `units/`-bearing **unstamped** run counts **all six** registered
version-gated arms, with `_i27_struct`'s two arms included *for a coarser reason than adoption*. Read
against its sibling `i45_g2prime_no_struct` — identical in being unstamped, different in having **no**
structural artifact at all, and counting exactly **four** — the pair is the real §3.2/L16
discriminator: the count tracks *which arms' non-version preconditions held*, not the number of
registered arms and not zero.

EXPECTED (P3-G2′ count-composition form): exit 0 AND stdout contains
`suppressed 6 version-gated arm(s) whose other preconditions HELD: ['I27-T1', 'I35-I40-T1', 'I38-T1v', 'I39-4-semver1', 'I41-T1', 'I42-1b-T1']`
— the arm-id LIST, so an off-by-two cannot satisfy the row. Measured on both backends. The row is no
longer pinned on `RESULT: PASS` and **no longer passes vacuously**; §9-R15's "passes vacuously"
sentence no longer describes it.

VERBATIM RECORD OF THE ORIGINAL OBSERVATION, kept because it is what changed the normative spec:

    NOTE  N-I45 version-skew visibility: validator_version=None suppressed 6 version-gated arm(s)
    whose other preconditions HELD: ['I27-T1', 'I35-I40-T1', 'I38-T1v', 'I39-4-semver1', 'I41-T1',
    'I42-1b-T1'] ...

`I41-T1` and `I42-1b-T1` are counted even though this run has no `panel[]` and no evidence digest.
§3.5's adjudication accepts this: those two are **stamp-only** arms whose structural/adoption tests
live *inside* the arm body behind the stamp gate, so a recorder cannot consult a conjunct that does
not exist outside the arm; and the emission carries the normative sentence *"Suppressed arms are an
UPPER BOUND on suppressed FAILs — an armed clause may have passed."*

DOES NOT COVER: the raised-stamp over-fire control (§3.5 **P3-G1**) — raising the stamp on *these*
bytes ARMS the underlying predicates and moves the exit code, so P3-G1 cannot be built here. It is
now shipped as `i45_stamp_raised/`, on the structure-free substrate where no arm has any body to
reach. **Iteration 1's broader claim — that P3-G1 "cannot be expressed as a GREEN row in this
harness" — was WRONG and is deleted: the premise about *these* bytes is true, the generalisation is
false, and the counterexample was constructed and measured.** Also not covered: `--quiet` (§3.3 /
P3-R2); a partial-suppression count on a stamp that is low but non-zero (`i45_skew_note`).
