# Fixture: unit_dir_unreadable (CRASH GUARD — per-unit scan block)

Pins the readability probe at the **top** of the per-unit scan loop in `validate_run.py`
(`for uid in sorted(os.listdir(units_dir))`, immediately after the `os.path.isdir` entry test).
A `units/<id>/` directory the process cannot read used to fail that block **two** ways, and the
quieter one arrived first:

| probe | on a mode-000 `units/U01/` | consequence |
|---|---|---|
| `os.path.isdir(udir)` | **True** (stat only needs the parent) | the loop enters a directory it cannot read |
| `os.path.exists(udir/…)` | **silent False** | the unit reads as EMPTY and is dropped — no row, no signal |
| `os.listdir(udir)` (the `verify_p*` scan) | **raises `PermissionError`** | `main()` aborts **before any `RESULT:` line**, silently disabling every predicate after it |

So a guard on the raising line alone would have traded a loud crash for a quiet lie. The probe
attempts the read (`os.listdir`) at the top of the loop and catches **`OSError`** — the class, not
just `PermissionError` — emits a FAIL row **naming the unit**, and `continue`s, so neither the
`os.path.exists` probes nor the `verify_p*` `os.listdir` is reachable for such a directory. That
listing is then **reused** by the `verify_p*` scan, so the old crash locus performs no read at all.

## Why this fixture has two halves

**A mode-000 directory cannot be committed to git** — git records no directory modes whatsoever
(only the executable bit on blobs), so a checkout can never *be* in the state under test. The
fixture is therefore split:

- **the committed run dir** (a copy of `good/`) is the **GREEN CONTROL**, swept by
  `run_tests.sh` via the `expectations.tsv` row
  `unit_dir_unreadable ⇥ 0 ⇥ !unit directory could not be read`. The `!` is a **negative** pin: it
  proves the guard does **not** fire on a readable unit dir. (`unreadable` alone would be a
  useless pin — it occurs in the fixture's own path, which the validator echoes.)
- **`reproduce.sh`** is the **RED** half. It copies this directory to a `mktemp -d`, `chmod 000`s
  the copy's `units/U01`, validates it, and restores the mode before `rm -rf` (a mode-000 dir
  cannot be recursed into, so the restore is load-bearing, not tidiness). The committed tree is
  never chmod'ed. `run_tests.sh` invokes it, and its exit folds into the suite's `fail_total`.

## What a failing result looks like

`bash reproduce.sh` prints one PASS/FAIL line per property and exits non-zero if any failed:

```
  FAIL  FAIL row NAMES the unreadable unit (U01)
  FAIL  exactly one RESULT: line (summary reached; saw 0)
  FAIL  no Python traceback
  PASS  non-zero exit (rc=1) — LOUD, not silently skipped
```

That is the **measured pre-guard output** (`bash reproduce.sh --validator <a git-show copy of the
pre-guard validator>`), and it is the whole point of the `--validator` flag: the red and green
sides are *demonstrated* to differ rather than asserted to. Post-guard, all four lines are PASS.

**Read the exit code with care: it does NOT distinguish the two sides.** An uncaught
`PermissionError` exits 1 and a clean `RESULT: FAIL` also exits 1, so a control that compares only
`$?` across the guard returns "same" on a fixture that genuinely regressed. The distinguishing
observations are the **naming row**, the **`RESULT:` count** (0 → 1), and the **traceback**.

## Honest limits

- If the host does not enforce mode 000 — running as `uid 0`, or some FUSE/container mounts —
  the condition cannot be produced. `reproduce.sh` self-checks (`ls` on the chmod'ed copy) and
  prints a **loud SKIP** saying nothing was verified, rather than passing vacuously.
- `os.access()` was deliberately **not** used as the probe: it consults the mode bits and lies
  under several mount and container configurations, which would re-introduce the silent path this
  guard exists to remove. The probe attempts the actual read.
- The guard reports and **skips**: `uid` stays in `unit_subdirs` (so the structural DoD trigger
  keeps firing fail-closed), but that unit's artifacts are **unvalidated**. A run with an
  unreadable unit dir is *unchecked* for that unit — the FAIL row says so in those words. No
  predicate has been added, re-graded or weakened.
