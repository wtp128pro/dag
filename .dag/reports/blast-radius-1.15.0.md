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
The follow-up iteration (D66) section and the re-run Full gate carry their own as-of, 2026-10-14 between 10:45 and 10:51 -04:00 (`date -Iseconds`).
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
- In that dry-run (same as-of), I63-1 found that unit U07's frozen check C3 ends in a diff against the **run base** rather than U07's own window. A later unit legitimately appended to the file it checks, so the check can no longer go green (`python3 $S/integrate.py <COPY_OF_RUN_DIR>` replay row for U07/C3, exit 1). The follow-up decision D66 resolved that I63-1 row: the check was rescoped to U07's own window and U07 was re-verified at iteration 2 (see "Follow-up iteration (D66)" below). It does not stay open.

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

## Follow-up iteration (D66), 2026-10-14

At the run's final sign-off gate the maintainer chose to iterate (decision D66): small fixes made inside the frames of
the units that last wrote each file, each footprinted, impact-scanned and independently re-verified.
As-of 2026-10-14T10:45:36-04:00 (`date -Iseconds`), HEAD was `bf37baf…` with the change set committed on the branch and the follow-up's edits uncommitted on top (`git rev-parse HEAD`; `git status --porcelain | wc -l` printed 8 before this revision of the report).
Each item below names the command that shows it in that working tree, run between 10:48 and 10:52 (`date -Iseconds`).

- R5 Conduct guidance: executors are not given worktree isolation and write in the one shared working tree; disjoint
  frames are checked by I61 (`grep -n "Do not give executors" plugins/dag/skills/dag/references/orchestrator-conduct.md` prints line 349).
- Root README blast clause: the plugin-table cell describes the blast-radius checks as "checks over declared, visible
  surfaces only" and leaves Limitation AE open (`grep -c "checks over declared, visible surfaces only" README.md` prints 1).
- integrate.py `--replay-timeout SECONDS`: a finite number greater than 0 that sets the replay window, default 300 s (`grep -n "DEFAULT_REPLAY_TIMEOUT = " $S/integrate.py` prints `109:DEFAULT_REPLAY_TIMEOUT = 300.0`).
  The same window bounds each census command, and regression commands keep their own `timeout_s`. A bad value such as 0 is refused with a one-line reason and exit 2 (`python3 $S/integrate.py /nonexistent --replay-timeout 0`).
  This replaces the fixed 300 s cap with no CLI option that the first version of this report listed as a design gap.
  The measurement behind it stays dated: U11's check C4 takes 6 min 17 s on a near-idle host (load about 0.9), measured on 2026-10-14 at about 05:38 with `time` over the command recorded for U11's case C4, and not re-run (`python3 -c 'import json,sys;print([c["check"] for c in json.load(open(sys.argv[1]+"/units/U11/brief.json"))["case_set"] if c["id"]=="C4"][0])' <RUN_DIR>` prints that command).
- Superseded statement: the first version of this report said the final integration "replays through the module API
  with a 900 s per-check window". It is replaced by the shipped CLI, `python3 $S/integrate.py <RUN_DIR> --replay-timeout 900`.
  The final integration runs after this report, and its result is recorded in the PR description's final-validation section, not here.
- `templates/blast.md` documents the replay window and the option (`grep -n "replay-timeout" plugins/dag/skills/dag/templates/blast.md` prints line 230).
- `templates/brief.md` gains a left-alone scoping rule: a check that asserts something was left alone is scoped to the
  unit's own window (its footprint, or its window snapshots), with base scope kept only for a file no other unit may change (`grep -n "Scope a left-alone check" plugins/dag/skills/dag/templates/brief.md` prints line 124).
  Its verifiers' residuals are under Known issues.
- U07's check C3 was rescoped to U07's own footprint: it asserts that U07's footprint lists no change to `expectations.tsv`, instead of diffing against the run base.
  `python3 -c 'import json,sys;print([c["check"] for c in json.load(open(sys.argv[1]+"/units/U07/brief.json"))["case_set"] if c["id"]=="C3"][0])' <RUN_DIR>` prints `python3 <RUN_DIR>/checks/u07_fallback.py && python3 <RUN_DIR>/checks/u07_window.py`, which exits 0 at 10:48:29.
  U07 was re-verified at iteration 2 (`python3 -c 'import json,sys;v=json.load(open(sys.argv[1]+"/units/"+sys.argv[2]+"/verify.json"));print(sys.argv[2],v["verdict"],v["converged"],v["iteration"],len(v["defects"]))' <RUN_DIR> U07` prints `U07 PASS True 2 5` at 10:52:08).

Round 2 of the follow-up fixed shipped-doc slips that the first version of this report listed as open:
- `templates/blast.md` says init_run.sh writes mode `git` or `snapshot` only, and exits 7 when it cannot determine one (`grep -n "snapshot. only" plugins/dag/skills/dag/templates/blast.md` prints line 15).
- The plugin CHANGELOG says the graph schema's `deliverable` key is unchanged, places the I60–I64/N-I65 rows in §4 of `state-machine.md`, and words I49–I59 as documentation of rows that already existed (`grep -n "deliverable. key is\|§4 gains the I60\|Documentation, not a new predicate" plugins/dag/CHANGELOG.md` prints lines 54, 71 and 73).
- The plugin README lead says the verifier's guardrail lens settles consumers and integrate.py re-runs the checks (`grep -n "guardrail lens settles" plugins/dag/README.md` prints line 219).

## Full gate (re-run after the D66 follow-up)

The same six commands were re-run on 2026-10-14 from 10:45:41 to 10:48:03 -04:00 (`date -Iseconds` before and after), after the follow-up's edits, at HEAD `bf37baf` plus those edits (`git rev-parse HEAD`).
The earlier column is this report's first window and is kept only as that earlier as-of; no result changed (`bash $S/run_tests.sh` and the rest, as listed).

| Gate | Command | Result at the earlier as-of (05:31–05:40) | Result after D66 (10:45:41–10:48:03) |
|---|---|---|---|
| Harness | `bash $S/run_tests.sh` | exit 0, "RESULT: PASS" | exit 0, "RESULT: PASS" |
| Spec | `python3 $S/spec_check.py` | exit 0, PASS 8, NOTE 1, FAIL 0 | exit 0, PASS 8, NOTE 1, FAIL 0 |
| Normalizer mirror | `python3 $S/normalize_artifacts.py --self-test` | exit 0, "self-test: 0 failure(s)" | exit 0, "self-test: 0 failure(s)" |
| Version mirrors | `python3 $S/mirror_check.py 1.15.0 1.0.19` | exit 0 | exit 0 |
| Formal | `bash $S/run_formal.sh` | exit 0, "8/8 commands as-expected" | exit 0, "8/8 commands as-expected" |
| Validator never runs git | `grep -c subprocess $S/validate_run.py` | prints 0 (grep exits 1 on no match) | prints 0 (grep exits 1 on no match) |

## Known issues found by this run (a selection; not fixed in this PR)

This list is a selection, not the full record. The run's unit verifications recorded 369 defects, all minor, across the 32 aggregated unit verdicts other than this report's own unit, U27, which is excluded as self: `python3 -c 'import json,glob,sys,collections as C;ps=[p for p in glob.glob(sys.argv[1]+"/units/*/verify.json") if "/U27/" not in p];c=C.Counter(d.get("severity") for p in ps for d in (json.load(open(p)).get("defects") or []));print(len(ps),dict(c))' <RUN_DIR>` printed `32 {'minor': 369}` at 2026-10-14T05:56:00-04:00. The glob grows as units are verified, so the figure is dated. The full findings are in each `<RUN_DIR>/units/*/verify.json`.

Verification that did not converge, re-measured at 2026-10-14T10:48:11-04:00 (`date -Iseconds`): three unit verdicts
are PASS with `converged` false. They are U06 (`impact_scan.py`), U09 (`integrate.py`) and U21 (the templates, at its
iteration-3 sweep, which found the left-alone paragraph's self-contradiction below). Each still found a new minor defect in its final round, none found a blocker or a major, and they carry 21, 29 and 10 minor defects (`python3 -c 'import json,glob,sys,collections as C;[print(p.split("/")[-2],v["verdict"],v["converged"],dict(C.Counter(d["severity"] for d in v["defects"]))) for p in sorted(glob.glob(sys.argv[1]+"/units/*/verify.json")) for v in [json.load(open(p))] if v.get("verdict")=="PASS" and v.get("converged") is False]' <RUN_DIR>`).
That is the earlier fixed-list command widened to every unit. This report's own unit, U27, is in the glob at its iteration-2 verdict, which converged, so it is not listed.
U31, listed here before, was re-verified at iteration 3 and converged with 11 minor defects (the one-unit `python3 -c` command under "Follow-up iteration (D66)" with `U31` prints `U31 PASS True 3 11` at 10:52:08).
A sign-off that accepts these units names each in `fsm-state.json` `accepted_incomplete`, which downgrades each named I44 or
I46 FAIL to a printed, greppable N-I44 NOTE; it suppresses nothing and covers no unit it does not name.

Shipped-doc slips that verifiers recorded (the second-round fixes are under "Follow-up iteration (D66)"):
- `templates/blast.md` says every blast artifact is written by a script; the project blast config is written by the project or the orchestrator.
- `templates/blast.md` presents `blast_accepted` as the general way past a blast FAIL. Only I62-4 and I64-3..I64-7 items are acceptable, never I60, I61 or I63.
- `templates/blast.md` examples are inconsistent: a frame example names a source path outside its graph, and an integration example's union of changes misses the renamed or added file. No shipped check validates these examples.
- `templates/brief.md` "Known consumers" lacks the consumer map and per-read cost that SKILL.md's cartography phase describes.
- Line-number citations of SKILL.md in the wiki and references have drifted. The drift predates this release and the release widened it; the impact scan has no rule for line-offset consumers of a document.
- The `spec/invariants.json` title for I63 says "On a signed-off armed run", but the validator arms I63 at P8_SYNTHESIS/DONE and I64 at sign-off.
- `state-machine.md` wording: the Limitation AB bullet omits the I63-2 later-wave exemption, and the no-config bullet omits the I64-5 differential rule. Limitation AE says "I63 replays" (integrate.py replays; I63 judges), and the N-I45 PRESERVES and BLAST-T1 REVISES statements disagree.
- SKILL.md's cartography phase omits errors[] as a second I64-5 no-config FAIL, and its impact-scan "no frame" wording is copied from the script's epilog.
- Wiki wording: there are arming gaps for I51/I52/I53 and in the confirmed-gate wording. I54 is described as blocking only at sign-off, but I54-1 and I54-2 fail at any phase. Some invariant counts are stale, and one schema list omits the directive and blast rows.
- `graph.schema.json` describes a validator rule that no predicate enforces.

Residuals of the follow-up itself (D66), as its verifiers recorded them:
- `templates/brief.md`'s left-alone paragraph is inexact in three cases (U21's verifier). In tree mode `changes[]` lists
  every change, so its sentence that a write outside the frame appears only in `unattributed[]` is false there. Across
  retry iterations, a `<U>-i<k>` window cannot see an earlier iteration's out-of-frame write that was never reverted.
  And a unit's first-iteration per-unit capture also uses a `<U>-i1` pair, not only a retry.
- The same paragraph contradicts itself (U21's convergence sweep, `verify_p4`): it says a left-alone check "is never
  scoped to the run's base commit", and then that base scope "stays right" for a file no other unit may change. U21's
  own check C4 is such a check.
- The blast-radius-sentinel persona's probe of undeclared writes diffs against the run base, the hazard that paragraph warns about: in a late wave that diff holds earlier units' legitimate writes (U21's verifier; `grep -n "Probe 6" plugins/dag/skills/dag/references/personas/blast-radius-sentinel.json` prints line 16).
- `integrate.py --replay-timeout -inf`, and any other value starting with '-', is refused by argparse with a usage error instead of the one-line reason; it still exits 2 and reads nothing (U31's verifier; `python3 $S/integrate.py /nonexistent --replay-timeout -inf` printed the usage block and "expected one argument", exit 2, at 10:48:29).
- The plugin CHANGELOG's schemas bullet omits `fsm-state.blast_accepted`, which 1.15.0 also added; the entry names it
  under I64 (U26's verifier).
- The follow-up's own frozen checks (`checks/d66_check.py` in the run directory) are keyword proxies with recorded blind
  spots. Each blind spot is covered by an executor check or by the verifier's direct reading (the verifiers of U21, U24,
  U26 and U31).

Design gaps:
- I63-1 cannot tell a regression from a frozen check scoped to the run base instead of the unit's own window. Such a check turns permanently red once a later unit legitimately edits the file. This run's instance of it, the I63-1 row on unit U07's check C3, was resolved by the follow-up decision D66, which scoped the check to U07's own footprint; the general gap stays open.
- The blast `base_sha` field accepts SHA-1 object names only. In a SHA-256 repository, init_run.sh writes a longer name and the run fails its schema.
- I60-2 coverage uses an un-normalised prefix match, so a brief output path that climbs out through `..` escapes it.
- An archived run's verdict depends on its workspace, because integrate.py does not copy the blast config into the run directory.
- integrate.py runs the tip's census command against the base tree, so renaming the census tool's own flag disables its census (fail-closed, unquantified).
- A run that is automatic from its very first phase cannot pass G-personas, I28 or I39, which have no machine-closed arm. I35 passes only with an honest empty dialogues file.
- The impact scan's removed-identifier fallback turns a generic word into a high-hit obligation, and its obligation cap keeps references by hit count.
- The run-level `verify.json` fails its own schema (a non-unit id, and an extra key), and no row flags it.
- A replay that times out cannot be recorded with a null exit code: `integration.schema.json` types `replay[].exit_code` as an integer (`grep -n '"exit_code"' plugins/dag/skills/dag/schemas/integration.schema.json`), so integrate.py writes an errors[] row and no replay row (`grep -n 'timed out' $S/integrate.py`).
- impact_scan.py passes no `--no-color` to `git grep`, so under a user git config of `color.ui = always` every scan with a hit crashes with a ValueError and exit 1. Reproduced on 2026-10-14 between 05:54 and 05:56 by running the M2 recipe at `M=85d2591` with the scan prefixed by `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=color.ui GIT_CONFIG_VALUE_0=always`; without the prefix it exits 0. `run_tests.sh` stubs HOME, so the harness cannot see it.
- The impact schema has no errors[] field, so scan errors are encoded as a scan-error symbol plus an error obligation.
- In snapshot mode, or without a base commit, every declared test surface becomes an errors[] row.
- N-I45 under-counts suppressed arms on runs that never adopted blast.
- The exact-literal survival rule hides an old key that survives word for word, or as an f-string fragment or docstring, in any changed Python file.
- footprint.py fails loud on an embedded repository added during a wave and on git trace variables in the environment. A per-unit capture taken before a retry's debrief is rewritten records a stale footprint.
