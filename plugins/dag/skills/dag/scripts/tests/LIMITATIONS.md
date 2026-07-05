# tests/ — reachability limitations of the new store checks (U07)

The fixtures added in U07 cover every new invariant that a **self-contained mini run-dir** can
exercise. Two of the U04/U05 additions read a **fixed real path under `$HOME`** (via
`os.path.expanduser`), NOT a path resolvable inside the fixture tree, so an in-tree fixture cannot
stage them without mutating the real `~/.claude`. Per the brief we DOCUMENT this rather than
fabricate a pass.

## Reachable in-tree (covered by fixtures)
- **I14 / AO-2** — `ao2_do_not_touch/` (neg), `ao2_disjoint/` + `good/` (pos).
- **I15 / AO-6** — `ao6_no_changes/` (neg), `ao2_disjoint/` + `good/` (pos).
- **03/P3 expiry** — `expiry_excluded/` (in-tree `.dag/learnings/` project store; the loader reads
  `<run_dir>/.dag/learnings/`).
- **03/P5 supersedes** — `supersedes/` (in-tree project store).
- **04/G4 scope.model narrowing** — `scope_model_match/` (neg), `scope_model_narrow/` (pos)
  (schema field on the run-local `learnings.json` + `fsm-state.json.model` — no store needed).

## NOT reachable by an in-tree fixture (documented, not faked)
- **04/G1 global tag registry** — read from `~/.claude/dag/tags.json` (`os.path.expanduser`). The
  path is fixed to the real HOME; a fixture cannot supply it without writing to the user's real
  `~/.claude`. It was exercised LIVE by U04 via a stubbed/staged HOME (then cleaned up); see the
  U04 debrief evidence rows (`I11 global tag registry (G1) loaded …` / `V_tag_eff … +N global`).
- **04/G2 user-global learnings store** — read from `~/.claude/dag/learnings/*.json`
  (`os.path.expanduser`). Same fixed-HOME constraint; exercised LIVE by U05 via an ISOLATED temp
  HOME (`export HOME=<tmp>`), then removed — see the U05 debrief `learnings user-store …` rows.
- **04/G3 promotion advisory** and **04/G5 idle-decay** — both surface off entries that in practice
  arrive via the user/global store; G3 is a non-gating `NOTE` and G5's decidable case
  (`max_idle_runs==0`) applies to a store-loaded entry. They do not change a run's verdict, so
  there is no exit-code assertion to make in a fixture; exercised live in U05.

### Why not stub HOME inside a fixture run
A fixture is executed by `python3 validate_run.py tests/<name>` with no environment control, and
U07's scope is edit-ONLY under `scripts/tests/` (no changes to `validate_run.py` and no test
harness). Overriding `$HOME` requires a runner/wrapper the fixture pattern does not have; writing
to the real `~/.claude` would be destructive and non-reproducible. Handoff to U08: if a HOME-stub
harness is desired, add a wrapper that sets `HOME` to a temp dir seeded with `tags.json` /
`learnings/` and asserts the `G1`/`G2` PASS lines — that is the honest way to close this gap.
