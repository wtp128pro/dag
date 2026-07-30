# Fixture: i45_g2prime_no_struct (spec §3.5 **GREEN P3-G2′** — count COMPOSITION discriminates suppression from lowness)

The whole run dir is **one file**: `fsm-state.json` with `phase: "P0_BOOTSTRAP"`, `gates: {}` and
**no `validator_version`**. Deliberately no `cartography.json`, no `CARTOGRAPHY.md`, no
`graph.json`/`GRAPH.md`, **no `units/` subdirectory**, no `SYNTHESIS.md` — i.e. `_i27_struct` is
`False`. (`NOTE.md` is not a structural artifact; the count was re-measured with this file present
and is unchanged at 4.)

PROVES the §3.2/L16 discriminator that nothing else in the suite pins: the N-I45 count is composed
of *the arms whose non-version preconditions actually held*, not of every registered arm and not of
nothing.

- An implementation that counts every registered version-gated arm regardless of its conjunct prints
  **6** here and fails this row.
- An implementation that never counts the stamp-only arms prints nothing (or 2) and also fails it.

The pin is the **arm-id LIST**, not the bare count, exactly as §3.5 P3-G2′ directs, so an off-by-two
cannot satisfy it.

EXPECTED: exit 0 and stdout contains
`suppressed 4 version-gated arm(s) whose other preconditions HELD: ['I38-T1v', 'I39-4-semver1', 'I41-T1', 'I42-1b-T1']`
— `I27-T1` and `I35-I40-T1` **absent**. Measured on both backends (jsonschema Draft202012Validator
and `DAG_FORCE_MINI=1`), identical output.

HISTORY: §3.5's original **P3-G2** ("no structural work, no adoption ⇒ **no** N-I45 line") was
**WITHDRAWN in iteration 2** as not simultaneously satisfiable with §3.1(2). Its witness fixture
`i45_no_skew_overfire` is retained; this dir is P3-G2′, the clause that replaced it. The iteration-1
fixture author's claim that P3-G1/P3-G2′ "cannot be expressed as a GREEN row in this harness" was
**refuted by construction** — the premise (raising the stamp on a fixture with real structural work
arms the underlying predicates and moves the exit code) is true, but P3-G2′/P3-G1 need no structural
work at all, which is the point of this one-file dir.

DOES NOT COVER: the `--quiet` posture (§3.3 / P3-R2 — `run_tests.sh` now has a flags column, but a
`--quiet` variant of the N-I45 row is not shipped here); the count on a run that is *stamped low but
non-zero* (`i45_skew_note` covers that); §3.1(4)'s dev-time recorder-completeness assertion (that is
`spec_check.py` SC8's job, and SC8 is green).
