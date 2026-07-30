# Fixture: i45_stamp_raised (spec §3.5 **GREEN P3-G1** — over-fire control, current stamp)

Byte-identical to `i45_g2prime_no_struct/fsm-state.json` except for `run_dir` and the addition of
`"validator_version": "99.0.0"` — a stamp above every registered `SHIP`.

PROVES N-I45's **first functioning over-fire control**. Until this dir landed, the predicate's only
GREEN control was `i45_no_skew_overfire`, whose stated expectation §3.5 has since withdrawn and whose
harness row passed **vacuously** on `RESULT: PASS`. Here the assertion is mechanical: with every arm's
stamp gate satisfied, **no arm is suppressed**, so `len(_SKEW) == 0` and the predicate must print
**nothing at all** — not a zero-count line, not a "0 arms" line.

An implementation that printed the NOTE unconditionally, or that counted arms whose stamp gate passed,
turns this row red.

EXPECTED: exit 0 and stdout does **not** contain `N-I45 version-skew visibility` (the `!`-prefixed
must-NOT-contain pin, `run_tests.sh:104-113`). Measured on both backends.

Paired with `i45_g2prime_no_struct`: the two dirs differ **only** in the presence of the stamp, so
together they isolate the stamp as the cause of the count — 4 arms unstamped, 0 arms at `99.0.0`,
exit 0 both ways (§3's "exit-neutral NOTE, always").

DOES NOT COVER: a stamp that is *high but not above every SHIP* (a partial-suppression count between
1 and 3 is unpinned); `--quiet` (§3.3); the interaction with structural artifacts (raising the stamp on
a `units/`-bearing fixture ARMS the underlying predicates and moves the exit code, which is why this
control is built on the no-structural-work substrate rather than on `i45_no_skew_overfire`'s bytes).
