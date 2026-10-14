<!-- BLAST.md — the blast-radius artifacts (1.15.0): footprint.json, impact.json, blast-config.json, integration.json. -->

# Blast-radius artifacts — `footprint.json`, `impact.json`, `blast-config.json`, `integration.json`

The blast-radius machinery records which repository paths each unit actually changed, lists the known
references to what changed that sit outside the unit's `frame`, and re-runs the run's checks once at the
end. **It checks declared, visible surfaces**: the paths a capture recorded against the patterns a frame
declared, the names the extractors pull out of a change, the consumers a whole-word text search can see,
and the commands a blast config declares. A consumer the search cannot see, or a semantic conflict
between two files that never share a path, stays outside what these records show. Every artifact here is
written by a script (stdlib only) and judged offline, post-hoc, by `validate_run.py` (`I60`–`I64`, plus
the exit-neutral `N-I65` summary); none of them is hand-written by an executor.

## The flow, in order (what the orchestrator runs)
1. **Bootstrap** — `init_run.sh` writes `fsm-state.blast` once: `mode` (`git` | `snapshot` | `none`),
   `base_sha` (HEAD, or null with no first commit), `base_tree_digest` (from `tree_digest`, below),
   `workspace_root`, `dirty_at_start` (paths `git status` already showed at scaffold time, minus `.wip/**`
   and the run dir) and `tool_version`. The validator arms the blast predicates when the run's stamp is
   1.15.0 or later and `graph.json` lists a unit; `init_run.sh --restamp` refuses (exit 6, file left
   byte-identical) to raise a stamp across 1.15.0 while `fsm-state.blast` is absent.
2. **Frame** — Phase 4 freezes each unit's `frame` (`modifies`, `immutable`, `intended_changes`,
   `modifies_none_reason`) in `graph.json` and mirrors it into `brief.json` (templates/graph.md,
   templates/brief.md). `python3 frame_match.py overlap <graph.json>` prints every pair of units with no
   dependency path either way whose `modifies` patterns can match a common path (exit 1 if any).
3. **Wave pre snapshot** — `footprint.py snapshot <RUN_DIR> --wave N` before the wave's first dispatch.
4. **Per-unit pre snapshot** — `footprint.py snapshot <RUN_DIR> --wave N --label <U>-i<k>
   [--window-units <ids>]`, taken EXACTLY ONCE when unit U is dispatched at iteration k (iteration 1
   included). Re-taking it mid-run silently moves the window start, and its hash is not recorded in
   `footprint.json`.
5. **Capture** — `footprint.py capture <RUN_DIR> --wave N` (whole wave) or `--wave N --unit U` (one unit,
   e.g. a retry) writes `units/<U>/footprint.json` + `footprint.json.sha256`.
6. **Impact** — `impact_scan.py <RUN_DIR> --unit U` writes `units/<U>/impact.json` + `impact.json.sha256`
   (`--preview` prints the same JSON and writes nothing).
7. **Audit** — the existing guardrail lens writes `blast_audit` on the aggregated `verify.json`
   (templates/verify.md): one disposition per obligation.
8. **Integration** — once all waves are done, `integrate.py <RUN_DIR>` writes `integration.json` +
   `integration.json.sha256`; `integrate.py <RUN_DIR> --explain <mapping.json>` cites a unit's frozen
   `intended_changes` entry for a recorded difference.
9. **Override** — the only sanctioned way past a blast FAIL is the per-item `blast_accepted` record in
   `fsm-state.json` (`items`, `rationale`, a `DECISIONS.md` ref): it downgrades each finding it names to a
   greppable `N-I64` NOTE and fails closed when malformed. It never turns a check off.

Every sidecar is in `shasum -a 256` format: `<hex>  <file name>`.

## Snapshot file — `blast/wave<N>[.<LABEL>].<pre|post>.json` (format `dag-blast-snapshot/1`)
The snapshot is an internal record with no schema under `schemas/`; its keys are "format", "mode",
"wave", "label", "phase", "head", "tree", "workspace_root", "excludes", "entries" (path → "xy",
"from_path", "sha256", and "stored" in snapshot mode), "tool_version" and "taken_at"; a per-unit pre
snapshot also records "window_units".
- **Workspace and excludes.** The root and mode come from `fsm-state.blast` when present, else
  `git rev-parse --show-toplevel` (git mode), else snapshot mode. The excludes are always `.wip/**` and
  `<run dir>/**`, matched with `frame_match.py` (`match_any_pattern`) — never a private matcher. A `[`,
  `*` or `?` in the run-dir path is written as a one-character class so it matches only itself.
- **git mode — the tree id, written through a temporary index.** Copy the real index (keeping its
  mtime), then under `GIT_INDEX_FILE=<copy>`: `git add -A .`, `git rm -r -q --cached --ignore-unmatch` of
  each excluded directory, `git write-tree`; delete the copy. HEAD, the real index and the working tree
  are never touched; gitignored paths stay invisible by git's own rules. Every git call runs with
  `GIT_OPTIONAL_LOCKS=0` (the real index's stat cache is never rewritten) and `LC_ALL=C`.
  "entries" lists every path `git status --porcelain=v1 -z --untracked-files=all` shows, minus excludes,
  with the sha256 of the current bytes (a symlink: its link text; null when absent); a staged rename
  yields the new path with its old "from_path" and the old path with xy `R-`.
- **snapshot mode (no git)** — "head" and "tree" are null; "entries" covers every regular file under the
  root minus excludes, and every hashed file is stored write-once in the **content store**
  `blast/objects/<sha256>` (files over 5 MiB are not stored and carry `"stored": false`). The content
  store is the only source of BEFORE content without git.
- A per-unit pre snapshot (`--label <U>-i<k>`) records the window units — U plus every `--window-units`
  id — as "window_units". U must be a unit of wave N and each window unit a `graph.json` unit id, else
  exit 2 and nothing is written.

## Capture — `units/<U>/footprint.json`
- **Content-based.** git mode: `git diff-tree -r -z -M --raw <pre tree> <post tree>`, so a HEAD move or
  a commit with no content change yields no change; `sha256_before` / `sha256_after` are sha256 of the blob
  bytes (`git cat-file`). Snapshot mode compares entry hashes (A, M, D only).
- **Whole-wave capture** (`--wave N`): pre = `blast/wave<N>[.<L>].pre.json`; post = the matching
  `.post.json` if it exists, else a fresh snapshot written there. A changed path belongs to every unit of
  THAT wave (`graph.json` waves) whose `frame.modifies` matches it (for a rename, the `from_path` too). A
  path no unit claims is listed in `unattributed` in every footprint the capture writes.
- **Per-unit capture** (`--wave N --unit U`, iteration k = U's debrief iteration, else 1): needs the
  `<U>-i<k>` pre snapshot of U's CURRENT iteration; without it the capture writes `capture_error` with
  `changes: []` and never falls back to the wave window. `changes` stay cumulative from the wave's
  original pre snapshot (`base_ref` = its tree), filtered to U's frame; `unattributed` covers only the
  window, from the `<U>-i<k>` pre snapshot to now, where a path is claimed only by U or a recorded window
  unit. A retry must never run inside another wave's window: a wave capture attributes only to its own
  wave's units, so those writes would read as unattributed there.
- **Tree mode** (`capture <RUN_DIR> --unit U --pre-tree X --post-tree Y`, for stand-ins and commit
  ranges): no snapshot files (`pre_snapshot_sha256` and `post_snapshot_sha256` null), every non-excluded
  change belongs to U, `base_ref` = X as given.
- **`base_ref`** is where BEFORE content is read from: the pre tree id (git wave mode), the pre tree-ish
  (tree mode), null (snapshot mode).
- **Fail-closed.** A git error; a git timeout (`DAG_BLAST_GIT_TIMEOUT` seconds, default 120; a value that
  is not a finite number above 0 is itself an error); any stderr line from `git status` or the temporary-index
  `git add -A` outside a small allowlist (advisory `hint:` lines, line-ending conversion notices, the
  embedded-repository notice), because git reports an unreadable path on stderr and still exits 0 — so a
  `GIT_TRACE*` variable or a clean filter that writes to stderr also yields an error; a missing per-unit
  pre snapshot; an unsafe path (absolute, `..`, NUL, empty); an unreadable or forged snapshot; any other
  I/O error. Each sets `capture_error` to a one-line reason and `changes` to `[]` (never a partial list),
  and the command exits 1. A snapshot that hits one refuses with exit 2 and writes nothing.

## Digest — `footprint.py digest <WORKSPACE_ROOT> [--run-dir RD]` (function `tree_digest`)
Prints `{"mode", "head", "tree", "digest": "sha256:<hex>"}`. git mode: sha256 of `tree:<tree id>` plus a
newline — a function of content only (a HEAD move with no content change leaves it unchanged). Snapshot
mode: sha256 over the sorted `<path>\t<sha256>` lines of every file minus excludes. `init_run.sh` uses it
for `base_tree_digest`; `integrate.py` uses footprint.py's own tree ids, exclusions and change list (no
second copy) and recomputes both digests as a guard against the formulas drifting.

## Before/after content read by `impact_scan.py`
- BEFORE: git mode `git cat-file blob <base_ref>:<path>` (the `from_path` for a rename) — the pre-wave
  content, so a file already dirty when the wave began is compared with that, never with HEAD; snapshot
  mode the content store `blast/objects/<sha256_before>`. The bytes must hash to `sha256_before`.
- AFTER: the file in the scanned workspace (snapshot mode may also use the content store); the bytes must
  hash to `sha256_after`. A missing blob or a hash mismatch is never skipped: it becomes a `scan-error`
  symbol plus a reference obligation naming it, and the exit status is 1.

## `units/<U>/footprint.json` (schema `footprint.schema.json`, closed)
The FILE footprint — unrelated to the token-usage `footprint` object in `debrief.json`, which only shares
the word. `mode` is `git`, `snapshot` or `none`; `changes[]` rows carry `path`, `status` (A, M, D, R, T),
`from_path` (the old path of an R, null otherwise), `sha256_before` (null on A) and `sha256_after` (null
on D); `iteration` is the unit's debrief iteration (1 when none exists yet). Judged by `I60`
(schema-valid, sidecar match, unit and iteration match, no `capture_error`, every changed path inside
`frame.modifies` and outside `frame.immutable`, an `informs` unit changes nothing) and `I61` (no two
same-wave units share a captured path; `unattributed` empty).

<!-- schema: footprint.schema.json -->
```json
{
  "unit_id": "U07",
  "iteration": 1,
  "mode": "git",
  "base_ref": "081b3bbbc244693f20cf87f9de45db666faa4dc8",
  "pre_snapshot_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
  "post_snapshot_sha256": "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
  "changes": [
    {"path": "src/parser.py", "status": "M", "from_path": null,
     "sha256_before": "2e7d2c03a9507ae265ecf5b5356885a53393a2029d241394997265a1a25aefc6",
     "sha256_after": "18ac3e7343f016890c510e93f935261169d9e3f565436429830faf0934f4f8e4"},
    {"path": "docs/parsing.md", "status": "R", "from_path": "docs/parser.md",
     "sha256_before": "3f79bb7b435b05321651daefd374cdc681dc06faa65e374e38337b88ca046dea",
     "sha256_after": "252f10c83610ebca1a059c0bae8255eba2f95be4d1d7bcfa89d7248a82d9f111"},
    {"path": "src/tokens.py", "status": "A", "from_path": null, "sha256_before": null,
     "sha256_after": "cd0aa9856147b6c5b4ff2b7dfee5da20aa38253099ef1b4a64aced233c9afe29"}
  ],
  "unattributed": [],
  "capture_error": null,
  "tool_version": "footprint.py/1"
}
```

## `units/<U>/impact.json` (schema `impact.schema.json`, closed)
Written by `impact_scan.py` from the unit's footprint; `footprint_sha256` binds it to that footprint's
bytes. `symbols[]` are the changed names (Python via ast, JSON-schema `properties` keys and `enum` values,
Markdown headings, shell functions, argparse options, and a removed-identifier fallback); added names alone
never create an obligation. `obligations[]`: one `reference` obligation per changed name with hits outside
the frame (git mode: `git grep -w -F` over tracked and untracked files; ignored files stay invisible),
filtered by the frame, `scan_excludes`, `.wip/**` and the run dir; one `coupling` obligation per
`coupling_rules` entry whose `when_paths` the footprint touches, unless it also touches one of
`require.touch_any` (a `require.command` rule always raises it). `sample_hits`, `referencing_paths` and
the obligation list are capped per `caps`; hits found but omitted by the caps are counted in
`truncated_hits`. Judged by `I62` together with the
`blast_audit` that dispositions every obligation id.

<!-- schema: impact.schema.json -->
```json
{
  "unit_id": "U07",
  "iteration": 1,
  "footprint_sha256": "aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123",
  "symbols": [
    {"id": "src/parser.py#function:parse_row", "name": "parse_row", "kind": "function",
     "change": "removed", "source_path": "src/parser.py"}
  ],
  "obligations": [
    {"id": "coupling:parser-needs-changelog", "kind": "coupling", "symbol_ids": [],
     "rule_id": "parser-needs-changelog", "referencing_paths": ["src/parser.py"], "hit_count": 1,
     "sample_hits": ["touch one of: CHANGELOG.md"]},
    {"id": "ref:parse_row", "kind": "reference", "symbol_ids": ["src/parser.py#function:parse_row"],
     "rule_id": null, "referencing_paths": ["tools/report.py"], "hit_count": 2,
     "sample_hits": ["tools/report.py:3:from src.parser import parse_row",
                     "tools/report.py:41:    rows = [parse_row(l) for l in lines]"]}
  ],
  "truncated_hits": 0,
  "caps": {"obligations": 200, "referencing_paths": 50, "sample_hits": 5},
  "scanner": {"version": "impact_scan.py/1",
              "extractors": ["argparse", "fallback-identifiers", "json-schema", "markdown-headings",
                             "python-ast", "shell-functions"]}
}
```

## `blast-config.json` / `.dag/blast.json` (schema `blast-config.schema.json`, closed)
What the scanner and the integration step run and scan for a repository. Resolution order (both
`impact_scan.py` and `integrate.py`): `--config`, else the run-dir `blast-config.json` (`source: run`),
else the repository's `.dag/blast.json` (`source: project`); `impact_scan.py` falls back to built-in
defaults (no coupling rules), while `integrate.py` records a missing or unreadable config as an `errors`
row. Exactly one of a non-empty `regression_commands` (`id`, `command`, `timeout_s`, `compare` — what is
compared between the base and tip runs, e.g. `exit` or `exit+stdout`) or a stated `regression_none_reason`.
A `coupling_rules` entry's `require` holds exactly one of `command` or `touch_any`. A `censuses` entry's
`command_template` gets `{root}` replaced by the shell-quoted path of the tree measured, so the template
must not quote it. `test_surfaces` kinds are `expectations-tsv` and `test-glob`.

<!-- schema: blast-config.schema.json -->
```json
{
  "source": "project",
  "regression_commands": [
    {"id": "unit-tests", "command": "python3 -m unittest discover -s tests -q", "timeout_s": 600, "compare": "exit"}
  ],
  "coupling_rules": [
    {"id": "parser-needs-changelog", "when_paths": ["src/parser.py"], "require": {"touch_any": ["CHANGELOG.md"]}},
    {"id": "schemas-need-self-test", "when_paths": ["schemas/*.schema.json"],
     "require": {"command": "python3 tools/check_schemas.py"}}
  ],
  "censuses": [
    {"id": "todo-markers", "command_template": "grep -rc TODO {root}/src | awk -F: '{s+=$2} END {print s+0}'",
     "must_not_increase": true}
  ],
  "test_surfaces": [
    {"id": "unit-tests", "kind": "test-glob", "path": "tests/test_*.py"}
  ],
  "scan_excludes": ["vendor/**"]
}
```

## `integration.json` (schema `integration.schema.json`, closed)
Written once by `integrate.py` after the last wave. START state = `fsm-state.blast` (`base_sha`,
`base_tree_digest`); END state = the current working tree. `union_changes[]` lists every changed path (a
rename split into D of the old path plus A of the new); `unowned_writes[]` = changed paths in no unit's
footprint; `multi_writer_paths[]` = paths in two or more footprints. `replay[]` re-runs, from the
workspace root, every command-form `case_set` check whose orchestrator-origin row in the unit's current
debrief is `discharged` (300 s timeout). `differential[]` runs each regression command at the start state
(a detached `git worktree` of `base_sha` in the system temp directory, hooks off, always removed) and at
the end state; no rows means `differential_none_reason` is stated. `test_weakening[]` compares each test
surface between `base_sha` and the workspace; `censuses[]` publishes the gross `added`, `closed` and
`shipped` next to `base` and `tip`. Anything that could not run is an `errors[]` row (exit 1) — never a
silent skip. `--explain` fills `intended_change_ref` with a verbatim `frame.intended_changes` entry.
Judged by `I63` (every replayed check exited 0; a file a unit wrote keeps its hash unless a later-wave
unit also wrote it) and `I64` (start state matches, base and tip digests differ when a ships footprint
changed a file, no unowned write, every recorded difference cites an intended change). `N-I65` prints a
summary and judges nothing.

<!-- schema: integration.schema.json -->
```json
{
  "base_sha": "ec0b4f0b5c90ed0fa911a2972ccc452641b31563",
  "base_tree_digest": "sha256:ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
  "tip_tree_digest": "sha256:3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
  "union_changes": [
    {"path": "src/parser.py", "status": "M",
     "sha256_base": "2e7d2c03a9507ae265ecf5b5356885a53393a2029d241394997265a1a25aefc6",
     "sha256_tip": "18ac3e7343f016890c510e93f935261169d9e3f565436429830faf0934f4f8e4"}
  ],
  "unowned_writes": [],
  "multi_writer_paths": [],
  "replay": [
    {"unit_id": "U07", "case_id": "C1", "command": "python3 -m unittest tests.test_parser -q", "exit_code": 0}
  ],
  "differential": [
    {"regression_id": "unit-tests", "base_exit": 1, "tip_exit": 0,
     "base_stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
     "tip_stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
     "intended_change_ref": "parse_row() is replaced by parse_rows(), which accepts a trailing comma"}
  ],
  "test_weakening": [],
  "censuses": [
    {"id": "todo-markers", "base": 12, "tip": 11, "added": 0, "closed": 1, "shipped": 0}
  ],
  "errors": []
}
```
