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

EXPECTED: exit 0 AND **no** `N-I45` line. An absence is not expressible in `expectations.tsv`, so the
pinned substring is `RESULT: PASS`; the absence is asserted by reading stdout (recorded as a harness
limitation, not as a satisfied assertion).

DOES NOT COVER: the absence itself, mechanically (see above); a run stamped ABOVE every registered
`SHIP` with preconditions holding (§3.5 P3-G1, the raised-stamp control) — raising the stamp on a
fixture with real structural work ARMS the underlying predicates and changes the exit code, so that
control cannot be expressed as a GREEN row in this harness and is recorded as a residual.

