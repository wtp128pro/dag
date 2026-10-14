# Blast-radius checks: measurement report (dag 1.15.0)

The blast checks inspect declared, visible surfaces: a unit's write footprint, the referencing paths a scan
can see, the commands a run declares, and a whole-run replay. Nothing below shows that they catch every
broken consumer. Integration blindness stays open; Limitation AE in `references/state-machine.md` names
what they cannot see.

**As-of.** A figure without its own as-of was measured on 2026-10-14 between 05:31 and 05:40 -04:00 (`date -Iseconds`).
That window covers the full gate, M1's obligations and per-commit census, M2, and the self-judgement.
Figures measured outside the window carry their own as-of where they appear: the integration dry-run (04:34), the
follow-up's workspace-deletion and I35 deltas (measured before 05:29 by the follow-up's verification), the U11 check
timing (about 05:38), and the figures re-measured for this revision between 05:54 and 05:58 (`date -Iseconds`).
`git rev-parse HEAD` printed `49c9bb50f366…`, the release base. The change set is still an **uncommitted
working tree** (`git status --porcelain | wc -l` printed 99 in the window), so every tip figure below describes that
working tree and not a commit.

Conventions. `S=plugins/dag/skills/dag/scripts`, run from the repository root. `$SCRATCH` is any empty
scratch directory. `<RUN_DIR>` is the directory of the dag run that built this release. No step below
writes to the repository: every checkout is a throwaway `git clone --shared` inside `$SCRATCH`.

Footprint-and-scan recipe for one commit `M`, treated as a single stand-in unit whose frame is the commit's own
changed paths. This is the recipe M1 and M2 use:

```bash
D=$(mktemp -d $SCRATCH/m.XXXXXX); mkdir -p $D/rd/units/U01
printf '{"blast":{"workspace_root":"%s","mode":"git"}}' "$PWD" > $D/rd/fsm-state.json
git diff --no-renames --name-only -z $M^1 $M | python3 -c 'import sys,json;p=sorted(x for x in sys.stdin.read().split(chr(0)) if x);json.dump({"units":[{"id":"U01","wave":1,"frame":{"modifies":p}}],"waves":[{"wave":1,"units":["U01"]}]},open(sys.argv[1],"w"))' $D/rd/graph.json
python3 $S/footprint.py capture $D/rd --unit U01 --pre-tree $M^1 --post-tree $M
git clone -q --shared --no-checkout "$PWD" $D/wt && git -C $D/wt checkout -q --detach $M
# M1 only: mkdir -p $D/wt/.dag && cp .dag/blast.json $D/wt/.dag/   (supplies the project's coupling rules)
python3 $S/impact_scan.py $D/rd --unit U01 --workspace $D/wt
python3 -c 'import sys,json;o=json.load(open(sys.argv[1]))["obligations"];print(len(o),sum(x["hit_count"] for x in o if x["kind"]=="reference"),sum(len(s) for x in o for s in x["sample_hits"])//4,[x["id"] for x in o])' $D/rd/units/U01/impact.json
```

## M1: back-test over commits f547aef..8bdf4d6 as stand-in units

The five commits after `f547aef` stand in for five units. The question is whether per-unit blast would have flagged
the known crash-class regression (iterating straight over a `.get()` result) that `4fb475d` introduced.

| Commit | Obligations (ids) | Command |
|---|---|---|
| 4fb475d | 2: coupling schemas-need-normalizer-self-test, coupling validator-needs-spec-check | `bash recipe above, with .dag/blast.json copied in` |
| c9e5571 | 2: coupling validator-needs-spec-check, a reference obligation on `LABELS` | `bash recipe above, with .dag/blast.json copied in` |
| 6be1073 | 0 | `bash recipe above, with .dag/blast.json copied in` |
| 1585fca | 1: coupling version-files-need-mirror-check | `bash recipe above, with .dag/blast.json copied in` |
| 8bdf4d6 | 3: coupling version-files-need-mirror-check, two generic-word reference obligations | `bash recipe above, with .dag/blast.json copied in` |

- Total 8 per-unit obligations, and **none names the crash class or the census** (`python3` printer at the end of the recipe, ids listed above).
- Without the project config in the scanned checkout, only the reference obligations remain, giving 0/1/0/0/2 (`bash recipe above, without the cp line`).
  The coupling rules come from `.dag/blast.json` alone.

Crash-class census of `validate_run.py` at each point:

```bash
for c in f547aef 4fb475d c9e5571 6be1073 1585fca 8bdf4d6; do git show $c:$S/validate_run.py > $SCRATCH/vr_$c.py; python3 $S/tests/i48_crash_class.py --census --file $SCRATCH/vr_$c.py --json | python3 -c "import json,sys;print('$c',json.load(sys.stdin)['total'])"; done
# gross: multiset difference over the (kind, src) site pairs between adjacent commits
python3 -c 'import json,sys,subprocess as sp,collections as C;m=[C.Counter((s["kind"],s["src"]) for s in json.loads(sp.run(["python3",sys.argv[1]+"/tests/i48_crash_class.py","--census","--file",sys.argv[2]+"/vr_"+c+".py","--json"],capture_output=True,text=True,check=True).stdout)["sites"]) for c in sys.argv[3:]];a=[m[i]-m[i-1] for i in range(1,len(m))];k=[m[i-1]-m[i] for i in range(1,len(m))];A=sum(a,C.Counter());print("added",sum(A.values()),"closed",sum(sum(x.values()) for x in k),"still present",sum((A&m[-1]).values()))' $S $SCRATCH f547aef 4fb475d c9e5571 6be1073 1585fca 8bdf4d6
```
- Output of the loop: f547aef 190, 4fb475d 194, c9e5571 192, 6be1073 192, 1585fca 192, 8bdf4d6 192 (the census loop above, run on each commit).
- Gross over the five commits: **4 added** (all in 4fb475d), **2 closed** (in c9e5571), **2 still present** at 8bdf4d6. The net figure, +2, hides the closures. The `python3 -c` multiset line above prints `added 4 closed 2 still present 2` (re-run at 2026-10-14T05:54:48-04:00); "still present" counts the added sites that remain at the last commit.
- The whole-run layer is the only place the regression surfaces, at sign-off and only through I64-7. With the census template as configured, the census tool is absent at the f547aef base, so the census cannot run and I64-7 **fails closed** ("no integration censuses[] row"). That signal is loud but carries no count. With a base-independent tool path, I64-7 reports "added 2 != 0". Neither form sees the gross 4 added and 2 closed; only a per-commit census does (`python3 $S/integrate.py <STANDIN_RUN_DIR>` then `bash $S/validate_run.sh <STANDIN_RUN_DIR>` on two sign-off variants of the stand-in. This was taken from the verified back-test and was **not** re-run for this report).
- I60 to I62 were vacuous on the stand-in because its units carry no debriefs. The I64-4 and I64-6 rows there come from the stand-in itself, not from the crash class (same `validate_run.sh` run).

## M2: noise over PRs #30 to #37

The same recipe was run on each PR's merge commit with no project config in the scanned checkout, so the figures count
reference obligations only. #37 was squash-merged as `49c9bb5`.

| PR | Merge | Changed paths | Obligations | Reference hits | Read-cost estimate (tokens) | Command |
|---|---|---|---|---|---|---|
| #30 | 55d1c73 | 882 | 3 | 47 | 340 | `bash recipe above, M=55d1c73` |
| #31 | 07600ba | 19 | 0 | 0 | 0 | `bash recipe above, M=07600ba` |
| #32 | 0462f2e | 510 | 2 | 17 | 196 | `bash recipe above, M=0462f2e` |
| #33 | 2dee92a | 35 | 0 | 0 | 0 | `bash recipe above, M=2dee92a` |
| #34 | 0318108 | 1007 | 1 | 6 | 299 | `bash recipe above, M=0318108` |
| #35 | f547aef | 13 | 0 | 0 | 0 | `bash recipe above, M=f547aef` |
| #36 | 85d2591 | 80 | 1 | 13 | 132 | `bash recipe above, M=85d2591` |
| #37 | 49c9bb5 | 577 | 2 | 17 | 196 | `bash recipe above, M=49c9bb5` |

- Totals: 9 obligations and 100 reference hits across 8 PRs, and 3 of the 8 PRs raise none (`python3` sum over the table rows above).
- The read-cost column is an estimate: the summed length of the sample hits divided by 4. It is not a tokenizer count (the `python3` printer in the recipe).
- Not measured: the extra coupling obligations that `.dag/blast.json` would add to these PRs. M1 shows 0 to 2 coupling obligations per commit (`bash recipe above, with the cp line`).

## M3: dogfood

### M3 follow-up: a throwaway-clone run

An ordinary light-tier dag run at 1.15.0, in automatic mode, inside a throwaway clone of the base. Its task was to rename
the census tool's `--census` flag to `--count` and update the live consumers. One shipping unit was executed and verified
by separate agents. The clone was then deleted and the run directory archived.

- Archived copy under the repository validator: exit 1, 75 checks passed, 7 problems (`bash $S/validate_run.sh <ARCHIVE_DIR> --quiet`; re-run unchanged at 2026-10-14T05:57:30-04:00).
  The problems are G-personas, I28, I35 and I39 (gates of a run that was automatic from the start), plus three I64-5 rows (no blast config is reachable, and the run-tests and spec-check base/tip differentials).
- Deleting the workspace changed the verdict, gross: **+3 I64-5 rows and −1 I64-7 row**, and checks passed fell from 109 to 75 (`bash $S/validate_run.sh <ARCHIVE_DIR>` before and after the workspace was deleted; measured by the follow-up run's verification on 2026-10-14 before 05:29, and not re-run for this report, because the workspace no longer exists).
  The second effect is location: the archive no longer sits where the validator looks for the project learnings store, two directories up.
- Of the automatic-from-start failures, G-personas, I28 and I39 have no machine-closed arm. **I35 does not need one**: an honest empty `{"dialogues": []}` file clears it, and the problem count dropped from 5 to 4 when the file was added (`bash $S/validate_run.sh <LIVE_RUN_DIR> --quiet` with and without that file; measured by the follow-up run's verification on 2026-10-14 before 05:29, and not re-run for this report).
- integrate.py exited 1 with one errors[] row. It replays the tip's census command against the base tree, so renaming the census tool's own flag disables that census (exit 2, then an I64 FAIL: fail-closed and unquantified) (`python3 $S/integrate.py <LIVE_RUN_DIR>`; run by the follow-up itself on 2026-10-14 before 05:17, while its workspace still existed, and not re-run for this report).
- The impact scan raised 2 obligations. The removed-identifier fallback made the generic word `census` an obligation with 86 hits across 21 referencing paths, below the cap of 50 (`python3 -c 'import json;[print(o["id"],o["hit_count"],len(o["referencing_paths"])) for o in json.load(open("<ARCHIVE_DIR>/units/U01/impact.json"))["obligations"]]'`).

### M3 self-judgement: this run, judged by the repository validator at 1.15.0

The run that built this release is stamped 1.15.0, carries a seeded blast record, and is judged by the invariants it ships.

- As-of 2026-10-14T05:34:33-04:00 (`date -Iseconds`), HEAD 49c9bb5 plus the uncommitted working tree (`git rev-parse HEAD`). The run phase was P6_EXECUTE_VERIFY (`python3 -c 'import json;print(json.load(open("<RUN_DIR>/fsm-state.json"))["phase"])'`).
- `bash $S/validate_run.sh <RUN_DIR> --quiet` exited 0 with 871 checks passed and 0 problems. The run without `--quiet` gave the same summary, with 0 FAIL rows and 53 advisory NOTE rows (`grep -cE '^\s*(FAIL|NOTE)'` over its output).
- Blast rows: I60 judged 34 units and 32 footprints, I61 judged 18 waves, and I62 judged 30 executed shipping units, all PASS (`grep -E '^\s*PASS\s+I6[0-2]'` over the same output).
  I63 arms only at P8_SYNTHESIS and I64 only at sign-off, so **neither has judged this run yet**. This self-judgement is therefore partial.
- A **labelled dry-run** of the whole-run integration step was run over a copy of the run, as of 2026-10-14T04:34:37-04:00 (before the window above, and not re-run for this report). It is not the final record: the final integration and sign-off happen after this report. It replayed 134 rows against base 49c9bb5 and found crash-class census base 207 and tip 207, with 0 added and 0 closed. It also found 10 multi-writer paths, all written by sequential waves (`python3 $S/integrate.py <COPY_OF_RUN_DIR>`).
- In that dry-run (same as-of), I63-1 found that unit U07's frozen check C3 ends in a diff against the **run base** rather than U07's own window. A later unit legitimately appended to the file it checks, so the check can no longer go green. That I63-1 row is open and goes to the maintainer at the final gate (`python3 $S/integrate.py <COPY_OF_RUN_DIR>` replay row for U07/C3, exit 1).

## Crash-class census across this run (gross)

The points are the base `49c9bb5` plus the `tree` recorded in every `<RUN_DIR>/blast/wave*.post.json` wave-boundary
snapshot, retry snapshots included and `.pre` snapshots excluded. The command reads each point's `validate_run.py`
with `git show`, counts it with the census tool, and compares each point's multiset of `(kind, src)` sites with the base:

```bash
python3 -c 'import json,glob,sys,hashlib,subprocess as sp,collections as C;S,R,O=sys.argv[1:4];ts=["49c9bb5"]+[json.load(open(p))["tree"] for p in sorted(glob.glob(R+"/blast/wave*.post.json"))];bs=[sp.run(["git","show",t+":"+S+"/validate_run.py"],capture_output=True,check=True).stdout for t in ts];[open(O+"/vr_%d.py"%i,"wb").write(b) for i,b in enumerate(bs)];m=[C.Counter((s["kind"],s["src"]) for s in json.loads(sp.run(["python3",S+"/tests/i48_crash_class.py","--census","--file",O+"/vr_%d.py"%i,"--json"],capture_output=True,text=True,check=True).stdout)["sites"]) for i in range(len(bs))];print("points",len(ts),"blobs",len({hashlib.sha256(b).digest() for b in bs}),"sites",sorted({sum(x.values()) for x in m}),"added",sum(sum((x-m[0]).values()) for x in m),"closed",sum(sum((m[0]-x).values()) for x in m),"still present",min(sum((m[0]&x).values()) for x in m))' $S <RUN_DIR> $SCRATCH
```
- Output at 2026-10-14T05:56:44-04:00: `points 31 blobs 8 sites [207] added 0 closed 0 still present 207` (the command above). The base and 30 recorded snapshots hold 8 distinct `validate_run.py` blobs, and every point counts 207 sites. The snapshot set grows as a run records waves, so a later re-run sees more points; within this report's first window it held the base plus 29 snapshots, with the same result.
- Gross across the run: **added 0, closed 0, still present 207** against the base at every point (all base sites remain; the command above). The working tree also counts 207: `python3 $S/tests/i48_crash_class.py --provenance --base 49c9bb5 --file $S/validate_run.py` printed `census(worktree) = 207   census(49c9bb5) = 207   delta = +0`, with ADDED and REMOVED both `(none)`, at 2026-10-14T05:56:27-04:00. That command exits 1 whenever the two counts are equal, so its exit status is not a pass/fail signal here; read its printed delta and lists.
- The control can tell the two sides apart: the base and working-tree `validate_run.py` hash differently, `64b7f1b85983…` against `1dfc4d8b7a43…` (`sha256sum`). An identical census is therefore a real result and not a file compared with itself. "Relocated rather than added" is untested, because nothing was added.

## Full gate (working tree, as-of above)

| Gate | Command | Result |
|---|---|---|
| Harness | `bash $S/run_tests.sh` | exit 0, "RESULT: PASS" |
| Spec | `python3 $S/spec_check.py` | exit 0, PASS 8, NOTE 1, FAIL 0 |
| Normalizer mirror | `python3 $S/normalize_artifacts.py --self-test` | exit 0, "self-test: 0 failure(s)" |
| Version mirrors | `python3 $S/mirror_check.py 1.15.0 1.0.19` | exit 0 |
| Formal | `bash $S/run_formal.sh` | exit 0, "8/8 commands as-expected" |
| Validator never runs git | `grep -c subprocess $S/validate_run.py` | prints 0 (grep exits 1 on no match) |

## Known issues found by this run (a selection; not fixed in this PR)

This list is a selection, not the full record. The run's unit verifications recorded 369 defects, all minor, across the 32 aggregated unit verdicts other than this report's own unit, U27, which is excluded as self: `python3 -c 'import json,glob,sys,collections as C;ps=[p for p in glob.glob(sys.argv[1]+"/units/*/verify.json") if "/U27/" not in p];c=C.Counter(d.get("severity") for p in ps for d in (json.load(open(p)).get("defects") or []));print(len(ps),dict(c))' <RUN_DIR>` printed `32 {'minor': 369}` at 2026-10-14T05:56:00-04:00. The glob grows as units are verified, so the figure is dated. The full findings are in each `<RUN_DIR>/units/*/verify.json`.

Verification that did not converge: the panels for U06 (`impact_scan.py`), U09 (`integrate.py`) and U31 (the
retry-window and fail-closed repairs to `footprint.py`, `impact_scan.py` and `integrate.py`) each still found a new
minor defect in their final round, and none found a blocker or a major. Each verdict is PASS with `converged` false,
carrying 21, 29 and 12 minor defects (`python3 -c 'import json,sys,collections as C;[print(u,(lambda v:(v["verdict"],v["converged"],dict(C.Counter(d["severity"] for d in v["defects"]))))(json.load(open(sys.argv[1]+"/units/"+u+"/verify.json")))) for u in ("U06","U09","U31")]' <RUN_DIR>`, at the same as-of).
Sign-off is to name these three units in `fsm-state.json` `accepted_incomplete`, which downgrades each named I44 or
I46 FAIL to a printed, greppable N-I44 NOTE; it suppresses nothing and covers no unit it does not name.

Shipped-doc slips that verifiers recorded:
- `templates/blast.md` says init_run.sh may write blast mode "none"; it writes only `git` or `snapshot`.
- `templates/blast.md` says every blast artifact is written by a script; the project blast config is written by the project or the orchestrator.
- `templates/blast.md` presents `blast_accepted` as the general way past a blast FAIL. Only I62-4 and I64-3..I64-7 items are acceptable, never I60, I61 or I63.
- `templates/blast.md` examples are inconsistent: a frame example names a source path outside its graph, and an integration example's union of changes misses the renamed or added file. No shipped check validates these examples.
- `templates/brief.md` "Known consumers" lacks the consumer map and per-read cost that SKILL.md's cartography phase describes.
- `orchestrator-conduct.md` R5's Conduct sentence, unchanged from the base, still describes worktree isolation for executors. An isolated executor's writes never reach the captured workspace, so its footprint is empty and its blast audit is vacuously green.
- The plugin CHANGELOG lists a `deliverable` schema field that this release did not add.
- The plugin CHANGELOG places the I60–I64/N-I65 rows in the wrong section of `state-machine.md`. It also overstates the I49–I59 backfill: those rows existed, and only the version enumeration is new.
- The plugin README lead says the predicates "settle" and "re-run". In fact integrate.py re-runs commands and verifiers settle obligations.
- Line-number citations of SKILL.md in the wiki and references have drifted. The drift predates this release and the release widened it; the impact scan has no rule for line-offset consumers of a document.
- The `spec/invariants.json` title for I63 says "On a signed-off armed run", but the validator arms I63 at P8_SYNTHESIS/DONE and I64 at sign-off.
- `state-machine.md` wording: the Limitation AB bullet omits the I63-2 later-wave exemption, and the no-config bullet omits the I64-5 differential rule. Limitation AE says "I63 replays" (integrate.py replays; I63 judges), and the N-I45 PRESERVES and BLAST-T1 REVISES statements disagree.
- SKILL.md's cartography phase omits errors[] as a second I64-5 no-config FAIL, and its impact-scan "no frame" wording is copied from the script's epilog.
- Wiki wording: there are arming gaps for I51/I52/I53 and in the confirmed-gate wording. I54 is described as blocking only at sign-off, but I54-1 and I54-2 fail at any phase. Some invariant counts are stale, and one schema list omits the directive and blast rows.
- `graph.schema.json` describes a validator rule that no predicate enforces.

Design gaps:
- I63-1 cannot tell a regression from a frozen check scoped to the run base instead of the unit's own window. Such a check turns permanently red once a later unit legitimately edits the file. This run's own I63-1 row on unit U07's check C3 is open for that reason.
- The blast `base_sha` field accepts SHA-1 object names only. In a SHA-256 repository, init_run.sh writes a longer name and the run fails its schema.
- I60-2 coverage uses an un-normalised prefix match, so a brief output path that climbs out through `..` escapes it.
- An archived run's verdict depends on its workspace, because integrate.py does not copy the blast config into the run directory.
- integrate.py runs the tip's census command against the base tree, so renaming the census tool's own flag disables its census (fail-closed, unquantified).
- A run that is automatic from its very first phase cannot pass G-personas, I28 or I39, which have no machine-closed arm. I35 passes only with an honest empty dialogues file.
- The impact scan's removed-identifier fallback turns a generic word into a high-hit obligation, and its obligation cap keeps references by hit count.
- The run-level `verify.json` fails its own schema (a non-unit id, and an extra key), and no row flags it.
- integrate.py replays each check under a fixed cap (`grep -n DEFAULT_REPLAY_TIMEOUT $S/integrate.py` prints 300.0 seconds) with no CLI option and no config key, so the shipped command can never replay a frozen check slower than 300 s, and I63-1 fails it as "no replay row". This is not a load effect: this run's U11 check C4 takes 6 min 17 s and passes on a near-idle host (load about 0.9), measured on 2026-10-14 at about 05:38 with `time` over the command recorded for U11's case C4 in `<RUN_DIR>/units/U11/brief.json`, and not re-run for this report.
- So the final integration of this run, after this report, replays through the module API with a 900 s per-check window, the same replay set and judging as the CLI with only the window longer: `python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import integrate as I;I.write_doc(sys.argv[2],I.integrate(sys.argv[2],None,timeout=900))' $S <RUN_DIR>`. This is disclosed here and at sign-off.
- A replay that times out cannot be recorded with a null exit code: `integration.schema.json` types `replay[].exit_code` as an integer (`grep -n '"exit_code"' plugins/dag/skills/dag/schemas/integration.schema.json`), so integrate.py writes an errors[] row and no replay row (`grep -n 'timed out' $S/integrate.py`).
- impact_scan.py passes no `--no-color` to `git grep`, so under a user git config of `color.ui = always` every scan with a hit crashes with a ValueError and exit 1. Reproduced on 2026-10-14 between 05:54 and 05:56 by running the M2 recipe at `M=85d2591` with the scan prefixed by `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=color.ui GIT_CONFIG_VALUE_0=always`; without the prefix it exits 0. `run_tests.sh` stubs HOME, so the harness cannot see it.
- The impact schema has no errors[] field, so scan errors are encoded as a scan-error symbol plus an error obligation.
- In snapshot mode, or without a base commit, every declared test surface becomes an errors[] row.
- N-I45 under-counts suppressed arms on runs that never adopted blast.
- The exact-literal survival rule hides an old key that survives word for word, or as an f-string fragment or docstring, in any changed Python file.
- footprint.py fails loud on an embedded repository added during a wave and on git trace variables in the environment. A per-unit capture taken before a retry's debrief is rewritten records a stale footprint.
