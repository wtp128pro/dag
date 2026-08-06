#!/usr/bin/env python3
"""i48_clause_matrix.py — per-clause negative fixtures for the I48 case-set predicate.

CLAUSE ENUMERATION COMES FROM THE PREDICATE'S SOURCE, NOT FROM SPEC.md AND NOT FROM A BRIEF.
`--clauses` walks validate_run.py's AST, collects every `rep.fail(...)` call inside the I48
block, and reports one clause per call site. That is STRICTLY FINER than the 8 `I48-N` marker
comments and itself COARSER than the branch-condition set — a single rep.fail can be reached by
several or-arms, and this matrix does not enumerate them (start with K13's `check_form` arm).
v1 called it "the FINEST enforced granularity"; that was an overstatement and is retracted.

EACH FIXTURE IS A SINGLE MUTATION of one shared base run (`--base` writes it out). RED = run the
mutated base, the clause's own report row appears. GREEN = run the base UNMUTATED, that row is
absent. Because the only difference between the two runs is the one mutation, a fixture that is
RED then GREEN pins ITS clause and not something incidental; the mutation diff is printed with
`--diff <id>` so the "exactly one thing changed" claim is checkable, not asserted.

Every fixture's base run stamps `validator_version: 1.13.0` — the I48 arm (`_I48_SHIP`) was set
ABOVE the 1.12.1 stamp current when these fixtures were written, and 1.13.0 shipped the contract, so
the gate now sits AT the release stamp. An unstamped or archived run still does not arm and no
existing fixture's verdict can move.

USAGE
  python3 i48_clause_matrix.py --clauses     # enumerate enforced clauses from SOURCE
  python3 i48_clause_matrix.py --matrix      # run the red/green grid (the check of record)
  python3 i48_clause_matrix.py --behaviour   # U25's landed loci + the silent-skip counterfactual
  python3 i48_clause_matrix.py --diff F24    # base-vs-mutant diff for ONE fixture
  python3 i48_clause_matrix.py --base DIR    # materialise the unmutated base run

WHAT THIS MATRIX CANNOT DO. Its coverage relation is over `rep.fail` SITES, and a site that
CRASHES emits no row — so no amount of totality here can ever cover the iterate-over-`.get()`
crash class. That class has its own behavioural family: `i48_crash_class.py --survivors`.
"""
import argparse
import ast
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
VR = os.path.join(SCRIPTS, "validate_run.py")
# validate_run.py defaults --schemas to `<dir of the INVOKED script>/../schemas`. A PATCHED COPY
# written into tempfile.mkdtemp() therefore resolves schemas to `$TMPDIR/schemas` — a directory
# this host happened to have (pre-run debris, Jul 5-29) and a clean host does not. Every copy
# invocation below must pass --schemas EXPLICITLY so the copy is judged against the repo's
# schemas, exactly like the uncopied VR. Without it the numbers are true on one machine only.
SCHEMAS = os.path.join(os.path.dirname(SCRIPTS), "schemas")
assert os.path.isdir(SCHEMAS), f"schemas dir not found at {SCHEMAS}"
GOOD = os.path.join(HERE, "good")
LO, HI = 6418, 6730          # the I48 block; re-derived by --clauses from the marker comments


# ---------------------------------------------------------------- clause enumeration (SOURCE)
def clause_block(src):
    """Locate the I48 block by its own marker comment and its terminating invariant comment."""
    lines = src.split("\n")
    lo = hi = None
    for i, ln in enumerate(lines, 1):
        if lo is None and ln.strip().startswith("# I48 case-set contract"):
            lo = i
        elif lo is not None and re.match(r"\s*# I10 ", ln):
            hi = i - 1
            break
    return (lo or LO), (hi or HI)


def enumerate_clauses():
    src = open(VR).read()
    lo, hi = clause_block(src)
    tree = ast.parse(src)
    groups = {}          # line -> "I48-N" marker in force at that line
    cur = None
    for i, ln in enumerate(src.split("\n"), 1):
        m = re.search(r"#\s*(I48-\d+)\b", ln)
        if m:
            cur = m.group(1)
        if lo <= i <= hi:
            groups[i] = cur
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "fail" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "rep" and lo <= n.lineno <= hi):
            msg = ""
            if len(n.args) > 1:
                try:
                    msg = ast.literal_eval(n.args[1])
                except Exception:
                    msg = ast.get_source_segment(src, n.args[1]) or ""
            out.append({"line": n.lineno, "group": groups.get(n.lineno) or "I48-1",
                        "gist": " ".join(str(msg).split())[:88]})
    out.sort(key=lambda x: x["line"])
    for i, c in enumerate(out, 1):
        c["clause_id"] = f"K{i:02d}"
    return (lo, hi), out


# --------------------------------------------------------------------------------- base run
CS_ENTRY = {"id": "C1", "check": "true", "check_form": "command",
            "trigger_ref": "T", "requirement_ref": "R", "requirement_ref_none_reason": "",
            "required_observations": ["obs-a"], "forbidden_observations": ["obs-b"],
            "production_path": True}
CS_ROW = {"id": "C1", "origin": "orchestrator", "outcome": "discharged",
          "evidence": "ran it", "evidence_tier": "executable",
          "non_vacuity": [{"observation_ref": "obs-a", "counterfactual": "cf-a",
                           "counterfactual_result": "red"},
                          {"observation_ref": "obs-b", "counterfactual": "cf-b",
                           "counterfactual_result": "red"}]}


def make_base(dest):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(GOOD, dest)
    fs = json.load(open(os.path.join(dest, "fsm-state.json")))
    fs["validator_version"] = "1.13.0"
    json.dump(fs, open(os.path.join(dest, "fsm-state.json"), "w"), indent=2)
    bp = os.path.join(dest, "units/U01/brief.json")
    b = json.load(open(bp))
    b["case_set"] = [copy.deepcopy(CS_ENTRY)]
    json.dump(b, open(bp, "w"), indent=2)
    dp = os.path.join(dest, "units/U01/debrief.json")
    d = json.load(open(dp))
    d["case_set_discharge"] = [copy.deepcopy(CS_ROW)]
    json.dump(d, open(dp, "w"), indent=2)
    return dest


# ------------------------------------------------------------------------------- mutations
def _b(run):
    return os.path.join(run, "units/U01/brief.json")


def _d(run):
    return os.path.join(run, "units/U01/debrief.json")


def _v(run):
    return os.path.join(run, "units/U01/verify.json")


def _patch(path, fn):
    o = json.load(open(path))
    fn(o)
    json.dump(o, open(path, "w"), indent=2)


def m_drop_caseset(r):
    _patch(_b(r), lambda o: o.pop("case_set"))


def m_unhashable_brief_id(r):
    _patch(_b(r), lambda o: o["case_set"][0].__setitem__("id", ["C1"]))


def m_dup_brief_id(r):
    _patch(_b(r), lambda o: o["case_set"].append(copy.deepcopy(o["case_set"][0])))


def m_no_discharge(r):
    _patch(_d(r), lambda o: o.pop("case_set_discharge"))


def m_unhashable_row_id(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("id", {"a": 1}))


def m_shrink(r):
    _patch(_b(r), lambda o: o["case_set"].append(dict(CS_ENTRY, id="C2")))


def m_extra(r):
    _patch(_d(r), lambda o: o["case_set_discharge"].append(dict(CS_ROW, id="CZ")))


def m_rdup(r):
    _patch(_d(r), lambda o: o["case_set_discharge"].append(copy.deepcopy(CS_ROW)))


def m_zero_orch(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("origin", "executor"))


def m_orch_restates(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("check_form", "command"))


def m_vacuous_no_finding(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].update(
        {"outcome": "vacuous"}) or o["case_set_discharge"][0].pop("non_vacuity", None))


def m_finding_on_nonvacuous(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("vacuity_finding", "x"))


def m_unhashable_tier(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("evidence_tier", ["x"]))


def m_tier_shortfall(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("evidence_tier", "asserted"))


def m_locator_executable(r):
    _patch(_b(r), lambda o: o["case_set"][0].__setitem__("check_form", "locator"))


def m_locator_shape(r):
    _patch(_b(r), lambda o: o["case_set"][0].update({"check_form": "locator"}))
    _patch(_d(r), lambda o: o["case_set_discharge"][0].__setitem__("evidence_tier", "located"))


def m_obs_nonlist(r):        # THE U25 LOCUS — truthy non-iterable in an observation list
    _patch(_b(r), lambda o: o["case_set"][0].__setitem__("required_observations", 5))


def m_no_nonvacuity(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0].pop("non_vacuity"))


def m_multiset(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0]["non_vacuity"].pop())


def m_notrun_on_command(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0]["non_vacuity"][0].update(
        {"counterfactual_result": "not-run", "reason": "n/a"}))


def m_notrun_no_reason(r):
    _patch(_b(r), lambda o: o["case_set"][0].__setitem__("check_form", "locator"))
    _patch(_d(r), lambda o: (o["case_set_discharge"][0].__setitem__("evidence_tier", "located"),
                             o["case_set_discharge"][0]["non_vacuity"][0].__setitem__(
                                 "counterfactual_result", "not-run")))


def m_reason_on_red(r):
    _patch(_d(r), lambda o: o["case_set_discharge"][0]["non_vacuity"][0].__setitem__(
        "reason", "why"))


def m_finding_unrouted(r):
    _patch(_d(r), lambda o: (o["case_set_discharge"][0].__setitem__("outcome", "violated"),
                             o["case_set_discharge"][0].pop("non_vacuity", None)))
    _patch(_v(r), lambda o: o.__setitem__("defects", []))


def m_unhashable_criterion(r):
    # LABEL CORRECTED (iteration 2). v1 commented this "SURVIVOR LOCUS 6698" and it is NOT:
    # appending a list TO A LIST leaves acceptance_criteria ITERABLE, so L6698 never fires and
    # the row that actually emits is K24's UNHASHABLE-member row at L6701 — 6698's GUARDED
    # NEIGHBOUR. This fixture pins K24 (the hash guard) and is counted against K24 only.
    # The survivors at L6698/L6705 are UNREACHABLE from this matrix by construction: its
    # coverage relation is over rep.fail SITES and a crash site emits no row. They are covered
    # by the separate behavioural family `i48_crash_class.py --survivors`.
    _patch(_b(r), lambda o: o["acceptance_criteria"].append(["nested"]))


def m_miscited(r):
    _patch(_v(r), lambda o: o.__setitem__(
        "defects", [{"criterion": "C1", "severity": "major", "evidence": "e"}]))


def m_unhashable_defect_criterion(r):
    _patch(_v(r), lambda o: o.__setitem__(
        "defects", [{"criterion": ["x"], "severity": "major", "evidence": "e"}]))


def m_bespoke_block(r):
    _patch(_v(r), lambda o: o.__setitem__("case_set_findings", [{"id": "C1"}]))


MUTANTS = [
    ("F01", "I48-1", "absence of case_set[] on a gated run", m_drop_caseset,
     "neither case_set[] nor a non-blank case_set_none_reason"),
    ("F02", "I48-1", "unhashable brief id", m_unhashable_brief_id,
     "UNHASHABLE id(s)"),
    ("F03", "I48-1", "duplicate brief ids", m_dup_brief_id,
     "ids not unique"),
    ("F04", "I48-1", "brief entries but no case_set_discharge[]", m_no_discharge,
     "has no case_set_discharge[]"),
    ("F05", "I48-2", "unhashable discharge-row id", m_unhashable_row_id,
     "row(s) carry UNHASHABLE id(s)"),
    ("F06", "I48-2", "shrink: frozen entry undischarged", m_shrink,
     "is a SHRINK"),
    ("F07", "I48-2", "extra orchestrator row", m_extra,
     "match no frozen brief entry"),
    ("F08", "I48-2", "duplicate orchestrator rows", m_rdup,
     "more than one origin='orchestrator' row"),
    ("F09", "I48-2", "zero orchestrator rows", m_zero_orch,
     "ZERO origin='orchestrator' rows"),
    ("F10", "I48-3", "orchestrator row re-states a brief key", m_orch_restates,
     "re-states brief-owned key(s)"),
    ("F11", "I48-4", "vacuous without vacuity_finding", m_vacuous_no_finding,
     "without a non-blank vacuity_finding"),
    ("F12", "I48-4", "vacuity_finding on a non-vacuous row", m_finding_on_nonvacuous,
     "vacuity_finding present on outcome="),
    ("F13", "I48-5", "unhashable evidence_tier", m_unhashable_tier,
     "UNHASHABLE evidence_tier"),
    ("F14", "I48-5", "tier below the derived floor", m_tier_shortfall,
     "is below the floor"),
    ("F15", "I48-6", "locator claiming executable", m_locator_executable,
     "with evidence_tier='executable'"),
    ("F16", "I48-6", "locator whose check is a command string", m_locator_shape,
     "does not fullmatch"),
    ("F17", "I48-7", "observation list is a truthy non-iterable (U25 LOCUS)", m_obs_nonlist,
     "not an array"),
    ("F18", "I48-7", "discharged without non_vacuity[]", m_no_nonvacuity,
     "without a non_vacuity[] array"),
    ("F19", "I48-7", "non_vacuity multiset != observations", m_multiset,
     "observation_ref multiset"),
    ("F20", "I48-7", "command-form check recording not-run", m_notrun_on_command,
     "counterfactual_result='not-run'"),
    ("F21", "I48-7", "not-run without a reason", m_notrun_no_reason,
     "without a non-blank reason"),
    ("F22", "I48-7", "reason present on a red counterfactual", m_reason_on_red,
     "reason present on counterfactual_result='red'"),
    ("F23", "I48-8", "non-discharge outcome, empty verify.defects[]", m_finding_unrouted,
     "empty defects[]"),
    ("F24", "I48-8", "unhashable acceptance_criteria member (K24 @L6701, the GUARDED neighbour)",
     m_unhashable_criterion, "UNHASHABLE member(s)"),
    ("F25", "I48-8", "defect filed under a case id", m_miscited,
     "are case_set ENTRY IDS"),
    ("F26", "I48-8", "bespoke case_set_findings block", m_bespoke_block,
     "bespoke case_set_findings block"),
    ("F27", "I48-8", "verify defect with an unhashable criterion", m_unhashable_defect_criterion,
     "UNHASHABLE criterion"),
]

# The fixture -> clause mapping, stated against the SOURCE enumeration `--clauses` prints.
# `--matrix` asserts this mapping is TOTAL: every clause id K01..KNN has a fixture. A clause with
# no fixture is reported by name rather than rounded away.
CLAUSE_MAP = {f"F{i:02d}": f"K{i:02d}" for i in range(1, 25)}
CLAUSE_MAP.update({"F25": "K26", "F26": "K27", "F27": "K25"})


def run_validator(run):
    p = subprocess.run([sys.executable, VR, run], capture_output=True, text=True,
                       env=dict(os.environ, HOME=tempfile.mkdtemp()))
    return p.returncode, p.stdout + p.stderr


def matrix():
    tmp = tempfile.mkdtemp(prefix="i48mx-")
    base = make_base(os.path.join(tmp, "base"))
    brc, bout = run_validator(base)
    has_result = "RESULT:" in bout
    print(f"BASE (unmutated, validator_version 1.13.0): rc={brc} RESULT:line={has_result}")
    (lo, hi), clauses = enumerate_clauses()
    covered = set(CLAUSE_MAP.values())
    uncovered = [c["clause_id"] for c in clauses if c["clause_id"] not in covered]
    print(f"clause enumeration from SOURCE (lines {lo}-{hi}): {len(clauses)} enforced clauses")
    print(f"fixture->clause mapping TOTAL: {not uncovered}"
          + (f"   UNCOVERED: {uncovered}" if uncovered else ""))
    ok = not uncovered
    print(f"{'id':4} {'clause':7} {'RED':5} {'GREEN':6} {'crash':6} description")
    for fid, grp, desc, fn, pin in MUTANTS:
        grp = CLAUSE_MAP[fid]
        run = os.path.join(tmp, fid)
        make_base(run)
        fn(run)
        rc, out = run_validator(run)
        red = pin in out
        crash = "RESULT:" not in out          # uncaught TypeError => no RESULT: line at all
        green = pin not in bout               # the SAME pin against the unmutated base
        row_ok = red and green and not crash
        ok = ok and row_ok
        print(f"{fid:4} {grp:7} {str(red):5} {str(green):6} {str(crash):6} {desc}"
              + ("" if row_ok else "   <-- NOT PINNED"))
    return 0 if ok else 1


def diff_fixture(fid):
    """Print the base-vs-mutant JSON diff for ONE fixture, so 'exactly one thing changed' is
    CHECKABLE rather than asserted. v1's docstring promised this flag and argparse rejected it."""
    import difflib
    hit = [m for m in MUTANTS if m[0] == fid]
    if not hit:
        print(f"unknown fixture {fid!r}; known: {', '.join(m[0] for m in MUTANTS)}")
        return 2
    _, _, desc, fn, pin = hit[0]
    tmp = tempfile.mkdtemp(prefix="i48df-")
    base = make_base(os.path.join(tmp, "base"))
    mut = make_base(os.path.join(tmp, "mut"))
    fn(mut)
    print(f"{fid} -> {CLAUSE_MAP[fid]}   {desc}\n  RED pin: {pin!r}")
    changed = 0
    for rel in ("fsm-state.json", "units/U01/brief.json", "units/U01/debrief.json",
                "units/U01/verify.json"):
        a, b = os.path.join(base, rel), os.path.join(mut, rel)
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        da = json.dumps(json.load(open(a)), indent=1, sort_keys=True).split("\n")
        db = json.dumps(json.load(open(b)), indent=1, sort_keys=True).split("\n")
        d = list(difflib.unified_diff(da, db, f"base/{rel}", f"mutant/{rel}", lineterm="", n=1))
        if d:
            changed += 1
            print("\n".join("  " + L for L in d))
    if not changed:
        print("  NO DIFF — the mutation is a NO-OP. That is a defect in the fixture, not a pass.")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if changed else 1


# --------------------------------------------------------- the BEHAVIOURAL check (C3's real form)
def behaviour():
    """U25's landed loci, verified not trusted — plus the silent-skip counterfactual.

    The property: a truthy non-iterable in an observation list must produce a NAMING report row
    AND a real `RESULT:` line. Neither an uncaught TypeError nor a SILENT SKIP satisfies it.
    """
    tmp = tempfile.mkdtemp(prefix="i48bh-")
    verdicts = []

    run = make_base(os.path.join(tmp, "landed"))
    m_obs_nonlist(run)
    rc, out = run_validator(run)
    naming = "not an array" in out
    result = "RESULT:" in out
    verdicts.append(("U25 landed locus: naming row", naming))
    verdicts.append(("U25 landed locus: RESULT: line reached", result))

    # Counterfactual A — the RAW DEFECT restored (`list(x or [])`). Must crash: no RESULT: line.
    src = open(VR).read()
    defect = src.replace(
        '                    if not isinstance(_fv, list):', '                    if False:')
    defect = defect.replace('                    _obs.extend(_fv)',
                            '                    _obs.extend(list(_fv or []))')
    verdicts.append(("counterfactual A applied (raw defect)", defect != src))
    dpath = os.path.join(tmp, "vr_defect.py")
    open(dpath, "w").write(defect)
    p = subprocess.run([sys.executable, dpath, run, "--schemas", SCHEMAS],
                       capture_output=True, text=True,
                       env=dict(os.environ, HOME=tempfile.mkdtemp()))
    verdicts.append(("counterfactual A: crashes (no RESULT: line)",
                     "RESULT:" not in p.stdout + p.stderr))

    # Counterfactual B — THE MUTANT THAT DEFEATED U25's C4: the SILENT-SKIP repair. It removes the
    # AST pattern, so a `list(<BoolOp>)` census goes GREEN — while the malformed field reaches NO
    # report row. A check that cannot separate B from the landed repair is VACUOUS.
    lines = src.split("\n")
    start = next(i for i, L in enumerate(lines) if "_obs_bad = True" in L)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "continue")
    # delete ONLY the naming rep.fail(...) between the flag and the `continue` -> a SILENT SKIP
    skip = "\n".join(lines[:start + 1] + lines[end:])
    verdicts.append(("counterfactual B applied (silent-skip repair)", skip != src))
    spath = os.path.join(tmp, "vr_skip.py")
    open(spath, "w").write(skip)
    p = subprocess.run([sys.executable, spath, run, "--schemas", SCHEMAS],
                       capture_output=True, text=True,
                       env=dict(os.environ, HOME=tempfile.mkdtemp()))
    sout = p.stdout + p.stderr
    verdicts.append(("counterfactual B: NO naming row (the defeat)", "not an array" not in sout))
    verdicts.append(("counterfactual B: still reaches RESULT: (looks fine)", "RESULT:" in sout))
    # And the AST proxy C3 goes GREEN on B — which is precisely why C3 is not the check of record.
    t = ast.parse(skip)
    proxy = [x.lineno for x in ast.walk(t) if isinstance(x, ast.Call)
             and isinstance(x.func, ast.Name) and x.func.id == "list"
             and x.args and isinstance(x.args[0], ast.BoolOp) and 6418 <= x.lineno <= 6760]
    verdicts.append(("counterfactual B: C3-shaped AST proxy sees NOTHING in the I48 block",
                     not proxy))

    ok = True
    for name, v in verdicts:
        print(f"  [{'ok ' if v else 'BAD'}] {name}")
        ok = ok and v
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clauses", action="store_true")
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--behaviour", action="store_true")
    ap.add_argument("--diff", metavar="ID", help="print the base-vs-mutant diff for one fixture")
    ap.add_argument("--base")
    a = ap.parse_args()
    if a.diff:
        return diff_fixture(a.diff)
    if a.base:
        print(make_base(a.base))
        return 0
    if a.clauses:
        (lo, hi), cs = enumerate_clauses()
        print(f"I48 block located from SOURCE markers: lines {lo}-{hi}")
        print(f"enforced clauses (rep.fail call sites): {len(cs)}")
        for c in cs:
            print(f"  {c['clause_id']}  {c['group']:7} L{c['line']}  {c['gist']}")
        return 0
    if a.behaviour:
        return behaviour()
    if a.matrix:
        return matrix()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
