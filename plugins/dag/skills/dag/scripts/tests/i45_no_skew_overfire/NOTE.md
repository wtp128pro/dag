# Fixture: i45_no_skew_overfire (GREEN over-fire control — P3 counts SUPPRESSION, not lowness; spec §3.5 P3-G2)

Byte-clone of `signoff_ok/` — a minimal single-unit `DONE` run with **no** `validator_version` key at
all and no structural work for any version-gated arm (no `panel[]`, no dialogue transcript, no
ask-first register, no anchor governance, no evidence digest, no I41 adjudication).

PROVES: the count is of arms whose non-version PRECONDITION HELD and were suppressed — not of arms
whose ship version merely exceeds the stamp. With `validator_version` absent,
`_i27_semver_ge(None, ship)` is `False` for EVERY arm, so an implementation that counts every
registered arm (rather than only those whose precondition held) prints an N-I45 line here and fails
this row. This is the exact discriminator between "the stamp is low" and "the stamp suppressed
something".

EXPECTED (per spec §3.5 P3-G2): exit 0 AND **no** `N-I45` line.

**OBSERVED, 2026-07-29 — THIS CONTROL IS CURRENTLY VIOLATED, AND THE FIXTURE IS RETAINED AS THE
WITNESS RATHER THAN WEAKENED.** The shipped implementation emits, on these exact bytes:

    NOTE  N-I45 version-skew visibility: validator_version=None suppressed 6 version-gated arm(s)
    whose other preconditions HELD: ['I27-T1', 'I35-I40-T1', 'I38-T1v', 'I39-4-semver1', 'I41-T1',
    'I42-1b-T1'] ...

`I41-T1` and `I42-1b-T1` are counted even though this run has **no** `panel[]` and **no** evidence
digest — i.e. no adoption of the feature those arms police. The likely cause is that §3.1(2)
("pass that site's ALREADY-COMPUTED non-version conjunct") and §3.5 P3-G2 ("a run with no structural
work / no adoption must emit NOTHING") are not simultaneously satisfiable at those call sites,
because the conjunct already computed there is coarser than adoption. One of the two clauses must
give; that is an adjudication for the spec author / integrator, not something a fixture may paper
over. Consequence today: the `i45_skew_note` RED row still discriminates a *present* NOTE, but
nothing in the suite discriminates *suppression* from *stamp-lowness*, so §3.2's honesty constraint
(L16 — a right number with a wrong mechanism is a defect) is UNPINNED for P3.

The harness row for this fixture passes VACUOUSLY on `RESULT: PASS`. An absence is not expressible in `expectations.tsv`, so the
pinned substring is `RESULT: PASS`; the absence is asserted by reading stdout (recorded as a harness
limitation, not as a satisfied assertion).

DOES NOT COVER: the absence itself, mechanically (see above); a run stamped ABOVE every registered
`SHIP` with preconditions holding (§3.5 P3-G1, the raised-stamp control) — raising the stamp on a
fixture with real structural work ARMS the underlying predicates and changes the exit code, so that
control cannot be expressed as a GREEN row in this harness and is recorded as a residual.

