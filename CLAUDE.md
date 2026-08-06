# CLAUDE.md — dag marketplace repo

Guidance for working in this repository.

## Git / PR workflow — always PR, never merge without approval
Every change to this repo lands through a pull request. The maintainer only ever has to say
"merge it."
- **Never commit or push to `main` directly.** Do the work on a branch off `main` and open a PR.
  (`main` is protected by a ruleset — `pull_request` + `non_fast_forward`, empty bypass list — so
  direct pushes and force-pushes are rejected regardless.)
- **Never merge a PR without the maintainer's explicit approval.** Open the PR, say it's ready,
  and wait — *even when the change was explicitly requested*. Merging is the maintainer's call,
  not the assistant's.
- **Stay on the PR's branch until it merges.** After opening a PR, leave the working tree checked
  out on that feature branch — do **not** `git checkout main` to "tidy up." Only return to `main`
  as part of the merge sequence below. (The maintainer's status line shows the current branch and
  its open PR; ending a turn on `main` hides the in-flight work and makes the branch/PR look absent.)
- **When told to merge, do all of this in one go:** merge the PR → sync `main`
  (`git checkout main && git pull --ff-only`) → delete the merged branch → verify the merge commit
  is on `main`, the change is present, and the branch (remote **and** local) is gone.
  (`delete_branch_on_merge` is **disabled** on this repo — measured:
  `gh api repos/wtp128pro/dag --jq .delete_branch_on_merge` → `false` — so **nothing auto-deletes**:
  merge with an explicit `--delete-branch`, then remove the local branch yourself, and if a stale
  remote-tracking ref survives, clear it with `git remote prune origin`.)
- **Never bypass branch protection.** Do not use `--admin` or any bypass to force a merge; if a
  base-branch policy blocks the merge, surface it rather than working around it. (Ruleset gotcha:
  never add the `update` "restrict updates" rule with an empty bypass list — it silently blocks
  **all** PR merges to `main`; `pull_request` alone already blocks direct pushes.)
- **No AI/assistant attribution in git.** Do not add `Co-Authored-By` trailers, "Generated with
  Claude Code" lines, or any AI mention to commit messages or PR bodies. Keep authorship to
  `wtp128pro` only.

## Repository shape
- A Claude Code plugin marketplace. One plugin (`dag`) under `plugins/dag/`.
- Skills live at `plugins/dag/skills/<name>/SKILL.md` and are **auto-discovered** — a new
  skill needs no manifest entry, just the directory + `SKILL.md`.

## Hard-won learnings (when changing the dag skill / its proof-carrying FSM)
Promoted from a dag self-evaluation run of the self-learning loops. Apply when proposing or
making changes to the pipeline's formal machinery.
- **Flag guarantee-touching changes; never make them silently.** When a change touches a formal
  guarantee (the correction-loop termination proof, an AO-1..7 invariant, an I1..I13 invariant),
  explicitly classify it as *preserves* vs *revises* the guarantee, and carry a migration argument
  for any revision. A silently-made guarantee change is a defect, not a bonus.
- **Enforce loop invariants post-hoc, never as a live guard on the only back-edge.** Added
  invariants (e.g. mechanizing the discipline-only AO-2 / AO-6) must be *offline* validator
  predicates over emitted artifacts, with violations routed to `ESCALATE`. A *live* guard on the
  correction loop's sole back-edge `LT7 (RETRY→EXECUTE)` can leave `RETRY` with no enabled
  out-edge → deadlock, breaking Claim D of the termination proof.
- **Verification is currency: never end a run with verification open or superseded.** A unit is
  verified only while its aggregated `verify.json` adjudicates the debrief on disk *now*
  (`verify.iteration == debrief.iteration`). An executor repair **invalidates** its prior panel, so
  a retry must re-verify; persist new panel members as `verify_p<N+1>…`, **continuing** the numbering
  across iterations rather than overwriting an earlier iteration's members (precedent: run
  `2026-07-18_101631`'s U01 holds `verify_p1..p9` — three rounds across iterations 1–3 — and no
  predicate reads `verify_p*`, precisely because those files are a per-iteration audit trail that
  legitimately lags). Mid-loop staleness is legal; staleness once `gates.signoff_confirmed: true`
  claims the run is finished is not (`I43`/`I44`/`I46`). Signing off with units knowingly open stays
  **available but loud**: record `fsm-state.json.accepted_incomplete` naming **every** open unit plus
  a rationale and a `DECISIONS.md` ref, which downgrades each named FAIL to a greppable `N-I44` NOTE
  — never suppresses it, never covers a unit it does not name, and fails closed if malformed.
  Honesty boundary (**Limitation AA**): these predicates make completeness *legible*, never *true* —
  a loop that bumps both iterations without re-verifying satisfies `I43` exactly, and panel
  independence and human-gate reality stay attestations. Do not let a doc claim otherwise.

## Authoring a check that can fail — and can pass (`case_set[]` discipline)
From run `2026-08-02_235310_independent-test-authorship`, which froze a `case_set[]` on every unit and
then measured its own checks. **Every figure below ships with the command that produced it; re-measure
before citing it rather than inheriting it.** Read `<RUN>` as that run's directory.

- **A check that cannot go RED is the default outcome, not the edge case.** At admission the rate was
  **10 of 13 orchestrator-frozen checks vacuous — 77%** (measured over the first four units to carry a
  case set: `python3 -c "import json,collections;c=collections.Counter(x['outcome'] for u in
  ['U24','U25','U26','U27'] for x in json.load(open('<RUN>/units/%s/debrief.json'%u))
  ['case_set_discharge'] if x.get('origin')=='orchestrator');print(c)"` → `{'vacuous': 10,
  'discharged': 3}`). The recurring shape is a command whose **exit status is constant** — a pipeline
  ending in `head`/`tail`, a bare `sed -n`, a `grep -c` whose count is read by a human rather than by
  the shell. Derive the check from the **failure**: write the input that makes the criterion false
  first, then the command that goes non-zero on it, then confirm it reaches zero on the real input.
  Where the check is a **proxy**, falsify it against the repair that would defeat the proxy, not merely
  against the defect. A locator-form check honestly capped at `located` beats a command-form check that
  cannot fail.
- **A check that cannot go GREEN is worse: it pays the executor to damage a correct artifact.** Seen at
  **three layers** in one run. *Check layer* — four orchestrator rows have come back `violated`, all
  because the only route to green was a move the check's own `forbidden_observations` barred (`python3
  -c "import json,glob;[print(p.split('/')[-2],x['id']) for p in
  glob.glob('<RUN>/units/*/debrief.json') for x in (json.load(open(p)).get('case_set_discharge') or [])
  if x['outcome']=='violated' and x.get('origin')=='orchestrator']"` → **as of 2026-08-06 11:50 EDT at
  worktree `6be1073`**, rc 0, printing four rows in glob order: `U15 C2`, `U13 C1`, `U13 C2`, `U18 C4`
  — three when this section was first drafted, four once `units/U15/debrief.json` landed at 11:40:29,
  which is exactly why a figure over a growing glob ships with its as-of). **The `.get(…) or []` guard
  is load-bearing, not style.** Nine of the 22 debriefs in that glob carry no `case_set_discharge` key
  at all (`U01`–`U06`, `U19`, `U22`, `U23`), so the bare `[…]` subscript raises `KeyError` at rc 1 on
  the first of them: a published command that had never run, next to output it could not have produced.
  Iterating a `for`-clause straight over a subscript is the crash class `.dag/learnings/L29.json`
  documents, and a probe that greps each bullet for a command **token** cannot see it — assert the
  command's **exit status and output**, never its presence.
  *Criterion layer* — a criterion narrower than the convention it polices. *Budget layer* — a cap the
  unit cannot meet however well it works: U20's mandatory reads cost **~129% of its cap before a line
  was written** (79,642 B ÷ 2.46 B/tok ≈ 32,400 tok against a 32,000 cap, plus ~8,950). So falsify
  every command-form check in **both** directions, and cost the reads the **criteria mandate** — not
  the files the unit happens to touch — while the unit is still unexecuted, where it costs no fuel.
  When an executor reports `violated` while declining a forbidden move, treat that first as evidence
  about the **check**.
- **One check frozen against a two-directional obligation is a coverage violation the schema already
  forbids and no predicate enforces.** `brief.schema.json`'s COVERAGE RULE requires that a check be
  able to observe **every** declared required/forbidden observation and that an entry which cannot be
  **SPLIT** — and says in the same breath that it is discipline only. Measured: `/usr/bin/grep -c
  "COVERAGE RULE" plugins/dag/skills/dag/schemas/brief.schema.json` → `1`; the same grep over
  `plugins/dag/skills/dag/scripts/validate_run.py` → `0`. The reliable smell is a forbidden observation
  about **omission** or about **leaving something alone** paired with a **diff-scoped** command, which
  can never see the leave-alone direction. Prefer splitting to strengthening.
- **Control against the run's BASE commit, never HEAD, and assert the two sides are not identical.**
  Once a run commits its own work, *"it is broken at HEAD too"* stops distinguishing pre-existing from
  self-inflicted; here that control compared a file **with itself** and returned 2 == 2 by
  construction. Re-measured for this entry: `for c in f547aef 4fb475d c9e5571 8bdf4d6; do git show
  $c:plugins/dag/skills/dag/scripts/validate_run.py > /private/tmp/vr_$c.py; python3
  plugins/dag/skills/dag/scripts/tests/i48_crash_class.py --census --file /private/tmp/vr_$c.py; done`
  → **190 / 194 / 192 / 192** — a **dated snapshot**, not a claim to be current: all four points are
  sha-pinned (the fourth read a bare `HEAD` until 2026-08-06; a commit ref cannot date a working
  tree), re-measured 2026-08-06 at `1188a8a` and unchanged. With `git rev-parse 4fb475d^` → `f547aef` confirming the base is the
  direct parent. Before publishing a control, prove the sides can differ (`sha256`/`cmp`) and treat an
  empty diff as an **invalid** control, not a passing one. Publish the **gross** — this run *added
  four, closed two, shipped two* — never the net `+2`, which answers "did it get worse" and hides
  "what did we do". Treat an **inherited** provenance claim (*"pre-existing"*, in a brief or a prior
  debrief) as unmeasured.
- **The standing rate — re-measured here, and dated.** **As of 2026-08-06, worktree at `6be1073`, and
  EXCLUDING this record's own unit (U31, whose debrief was not yet on disk): 40 orchestrator-frozen
  case rows across 11 debriefs — 16 discharged / 21 vacuous / 3 violated = 60% not discharged.**
  Measured with `python3 -c "import json,glob,collections;c=collections.Counter(x['outcome'] for p in
  glob.glob('<RUN>/units/*/debrief.json') for x in (json.load(open(p)).get('case_set_discharge') or [])
  if x.get('origin')=='orchestrator');print(c,sum(c.values()))"`. **This number is computed by globbing
  a corpus every new unit adds to, so it is dated the instant it is written** — the identical query one
  wave earlier returned **32 rows, 59% not discharged** (the figure frozen into `Limitation AC`
  boundary (iii) in `references/state-machine.md`, already stale on arrival). Any figure of this shape
  ships with its **as-of** and its **exclusion of self**, or it is not a measurement. Every one of
  these was caught by a unit or a verification lens, never by the orchestrator that froze the check.
  **State the buckets, because the outcome enum is open-ended.** The denominator is every
  orchestrator-origin row whatever its `outcome`, and *not discharged* means every value that is not
  `discharged` — at the as-of that was `vacuous` + `violated`, but the same query run at 11:50 the same
  morning returns a **fourth** value, `infeasible` (`U15 C4`), which the one-liner counts in the total
  and which a two-bucket reading would silently drop. A percentage over an enum you did not enumerate
  is not well defined for whoever re-runs it.
- **What none of this closes.** A discharged case set is evidence about **declared** observations
  inside **one** unit — never that the case set is complete or adequate, never that a
  red-under-mutation result says anything about correctness, and never that cross-unit/integration
  blindness is closed. That class stays open and is recorded as `.dag/learnings/L29.json`, alongside
  `Limitation AC` boundary (iv) in `plugins/dag/skills/dag/references/state-machine.md`.

## Dogfooding — validate self-runs with the REPO's validator, not the installed plugin
When a dag run is executed **inside this repo** (its run dir lands under `.wip/`), validate it with the
repo's own checker — `bash plugins/dag/skills/dag/scripts/validate_run.sh <RUN_DIR>` — **never** the
installed plugin's copy at `${CLAUDE_PLUGIN_ROOT}/skills/dag/scripts/`. The installed plugin can lag the
repo, so a run may falsely "PASS" a stale validator while the current repo validator would fail it (F3:
the 2026-07-06 remediate run "PASSed" the installed v1.1.1 while the contemporaneous repo validator
failed it 7×). Archived `.wip/` runs are judged against their contemporaneous validator; current-validator
findings on older/unstamped runs are **expected version-skew, not defects** (see
`references/state-machine.md` §5 "Version-skew policy"; `fsm-state.json.validator_version` records which
validator scaffolded each run).

**Retracted in part — incomplete at this tree, not false.** The clause "`fsm-state.json.validator_version`
records which validator scaffolded each run" still holds for any run on which `--restamp` was never
invoked, but it no longer covers every case: the field records the validator that **scaffolded** the run
**or** the one that **last re-stamped** it. `init_run.sh --restamp <RUN_DIR>` shipped in **1.12.0** as a
**flag plus the orchestrator protocol that calls it** (the phase-advance step in `SKILL.md`); the
**automatic** re-stamp-on-phase-advance form is **unbuilt** (precedent: the 1.12.0 entry in
`plugins/dag/CHANGELOG.md`, which states it in exactly those terms). So re-stamping is opt-in and
unenforced — measured: nothing in the validator executes `init_run.sh`
(`grep -c subprocess plugins/dag/skills/dag/scripts/validate_run.py` → `0`), so no predicate checks
whether a run re-stamped. Read an unrefreshed stamp as the scaffolding validator; read
a refreshed one as the most recent `--restamp`, never as evidence the run was re-validated.

## Editing `plugins/dag/skills/dag/schemas/*.json` — re-run the normalizer's self-test
`scripts/normalize_artifacts.py` hand-mirrors both artifact schemas (enums, closed-key sets,
`required` lists, scalar types) and **deletes** under `--write`, so **any** edit to
`debrief.schema.json` / `verify.schema.json` must be followed by
`python3 plugins/dag/skills/dag/scripts/normalize_artifacts.py --self-test` (exit 0) in the same
change. Nothing invokes it automatically and no validator depends on it. Precedent: the 1.11.0
`panel_adjudication` (I41) addition landed eleven minutes after the normalizer and left the mirror
rotten — `--self-test` went red (T7b/T7f) *and* the script began advising orchestrators that
`panel_adjudication` was "outside verify.schema.json" and should be folded into `audit_notes`,
which would have destroyed an object I41-1 requires.

## Versioning / releases — keep every mirror in sync
The plugin version is mirrored in **six** places; a bump must update all of them together
(precedent: commit 4b19c47):
1. `plugins/dag/.claude-plugin/plugin.json` — plugin `version`
2. `plugins/dag/CHANGELOG.md` — new plugin entry
3. `plugins/dag/README.md` — the `Current version:` line
4. `.claude-plugin/marketplace.json` — plugin entry `version` **and** top-level catalog `version`
5. `README.md` (root) — the plugin-table version cell
6. `CHANGELOG.md` (root) — new catalog entry
Convention: a new skill/feature = **minor** plugin bump; each catalog release = **patch** bump
of the marketplace top-level version.

### Changelog guardrail (append, never relabel)
When bumping a version in an append-only `CHANGELOG.md`, **add a new top entry** and leave the
prior top entry intact — never relabel the existing top header to the new version. Relabeling
both destroys history and mis-attributes the old body to the new version. Recover an original
entry with `git show HEAD:<file>`. A changelog entry must describe **only** what that version
actually shipped.
