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
