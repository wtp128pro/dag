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
  (`delete_branch_on_merge` is enabled, so the remote branch auto-deletes — still confirm, and
  remove the local branch.)
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
