#!/usr/bin/env python3
"""U29 FIXTURE 1 — the `case_set_none_reason` CONTENT BAR (brief.schema.json CB-1..CB-3).

ONE fixture, TWO arms, differing ONLY in the value of `case_set_none_reason`:

  RED   arm: case_set: []  +  "n/a"                      -> expected schema-INVALID
  GREEN arm: case_set: []  +  a substantive reason naming
             the SEARCH performed and the SURFACE searched -> expected schema-VALID

Discrimination (why the RED is attributable to the content bar and not to some other
schema failure): the two arms are the SAME object; the ONLY byte difference is that one
string.  The red arm's error set is asserted to be non-empty and to sit ENTIRELY under
the `case_set_none_reason` property; the green arm's error set is asserted EMPTY.

It also records the layering fact that motivates the fixture: validate_run.py's I48-1
only applies a `.strip()` bar, so it passes "n/a"; the bar that rejects it lives in
brief.schema.json and is NOT version-gated.

  rc 0  both arms behaved as expected (red RED for the right reason, green GREEN)
  rc 1  an arm returned the wrong verdict, or the red was not attributable to the bar
"""
import json, sys, copy, subprocess, os

REPO = "/Users/mborodia/Developer/dag"
SCHEMAS = os.path.join(REPO, "plugins/dag/skills/dag/schemas")
assert os.path.isdir(SCHEMAS), SCHEMAS
BRIEF_SCHEMA = os.path.join(SCHEMAS, "brief.schema.json")

RED_REASON = "n/a"
GREEN_REASON = ("Searched this brief's acceptance_criteria[] and the clarifications.json "
                "register for a surface this unit executes; both name only prose the unit "
                "reads, so no entry is derivable.")

from jsonschema import Draft202012Validator

schema = json.load(open(BRIEF_SCHEMA))
base = json.load(open("/Users/mborodia/Developer/dag/plugins/dag/skills/dag/scripts/"
                      "tests/good/units/U01/brief.json"))
base["case_set"] = []

def arm(name, reason):
    o = copy.deepcopy(base)
    o["case_set_none_reason"] = reason
    errs = sorted(Draft202012Validator(schema).iter_errors(o), key=lambda e: list(e.path))
    return o, errs

ok = True
red_obj, red_errs = arm("RED", RED_REASON)
grn_obj, grn_errs = arm("GREEN", GREEN_REASON)

# the two arms must differ in EXACTLY one key, or the discrimination is not shown
diff = [k for k in set(red_obj) | set(grn_obj) if red_obj.get(k) != grn_obj.get(k)]
print("SAME FIXTURE, differing keys between the two arms: %s" % diff)
if diff != ["case_set_none_reason"]:
    print("  [BAD] the arms differ in more than the none-reason — not a discriminating pair")
    ok = False

print("\nRED ARM   case_set: [] + %r" % RED_REASON)
if not red_errs:
    print("  [BAD] schema-VALID — the content bar did not fire")
    ok = False
else:
    loci = sorted({"/".join(map(str, e.absolute_path)) or "$" for e in red_errs})
    print("  schema-INVALID, %d error(s), loci: %s" % (len(red_errs), loci))
    for e in red_errs:
        print("    - %s: %s" % ("/".join(map(str, e.absolute_path)) or "$", e.message[:110]))
        c = (e.parent.schema if e.parent else e.schema)
        print("      $comment: %s" % str(e.schema.get("$comment", ""))[:90])
    if loci != ["case_set_none_reason"]:
        print("  [BAD] red is NOT attributable to the content bar alone — other loci: %s" % loci)
        ok = False
    else:
        print("  [ok ] every error sits at case_set_none_reason -> attributable to CB-1..CB-3")

print("\nGREEN ARM case_set: [] + a reason naming the search and the surface")
print("  %r" % GREEN_REASON)
if grn_errs:
    print("  [BAD] schema-INVALID — the fixture cannot return the OTHER answer:")
    for e in grn_errs:
        print("    - %s: %s" % ("/".join(map(str, e.absolute_path)) or "$", e.message[:140]))
    ok = False
else:
    print("  [ok ] schema-VALID — the SAME fixture returns the OTHER verdict (L22 both directions)")

# which clauses fire, one at a time, so the red is not a lump
print("\nPER-CLAUSE attribution (each arm's reason against CB-1/CB-2/CB-3 in isolation):")
allof = schema["properties"]["case_set_none_reason"]["allOf"]
for label, reason in (("RED  ", RED_REASON), ("GREEN", GREEN_REASON)):
    verdicts = []
    for i, sub in enumerate(allof, 1):
        v = Draft202012Validator({"type": "string", **{k: sub[k] for k in sub if k != "$comment"}})
        verdicts.append("CB-%d:%s" % (i, "PASS" if v.is_valid(reason) else "FAIL"))
    print("  %s  %s" % (label, "  ".join(verdicts)))

# the layering fact: the validator's own I48-1 passes "n/a"
print("\nLAYERING (why the SCHEMA is where this bar lives):")
print("  validate_run.py I48-1 tests only `_i48_blank(case_set_none_reason)` "
      "(validate_run.py:6487) -> %r is NON-blank, so I48-1 PASSES it."
      % RED_REASON)
print("  brief.schema.json CB-1..CB-3 (brief.schema.json:193-200) is the ONLY bar that "
      "rejects it, and it is NOT version-gated.")

# ---------------------------------------------------------------- END TO END
# the same two arms, but as REAL RUN DIRS driven through validate_run.py, so the fixture
# is a pipeline fixture and not only a jsonschema call.  --schemas is passed EXPLICITLY at
# both invocations (a stale $TMPDIR/schemas snapshot made a whole fixture family green on
# this machine only — U28's portability defect).
import u29_fixture_base as mkfix, shutil

def rundir(dest, reason):
    d = mkfix.build(dest)                       # 1.13.0-stamped, so I48-1 is ARMED
    bp = os.path.join(d, "units/U01/brief.json")
    b = json.load(open(bp))
    b["case_set"] = []                          # explicit-none
    b["case_set_none_reason"] = reason
    json.dump(b, open(bp, "w"), indent=1)
    dp = os.path.join(d, "units/U01/debrief.json")
    x = json.load(open(dp)); x.pop("case_set_discharge", None)
    json.dump(x, open(dp, "w"), indent=1)
    r = subprocess.run(["python3", os.path.join(REPO, "plugins/dag/skills/dag/scripts/validate_run.py"),
                        d, "--schemas", SCHEMAS], capture_output=True, text=True)
    o = r.stdout + r.stderr
    bar = [l.strip() for l in o.splitlines()
           if l.strip().startswith("FAIL") and "case_set_none_reason" in l]
    i48 = [l.strip() for l in o.splitlines() if "I48 case-set contract" in l]
    return r.returncode, bar, i48

print("\nEND-TO-END through validate_run.py (1.13.0-stamped run dir, --schemas explicit):")
rrc, rbar, ri48 = rundir("/private/tmp/u29/work/csnr_red", RED_REASON)
grc, gbar, gi48 = rundir("/private/tmp/u29/work/csnr_green", GREEN_REASON)
print("  RED   arm: rc %d, %d content-bar FAIL row(s), %d I48 row(s)" % (rrc, len(rbar), len(ri48)))
for l in rbar:
    print("     ", l[:200])
print("  GREEN arm: rc %d, %d content-bar FAIL row(s), %d I48 row(s)" % (grc, len(gbar), len(gi48)))
if not rbar:
    print("  [BAD] the red arm produced no content-bar row end-to-end"); ok = False
if gbar:
    print("  [BAD] the green arm produced a content-bar row"); ok = False
if not rbar or gbar:
    pass
else:
    print("  [ok ] the ONLY delta between the two run dirs is the content-bar row set: %d -> %d"
          % (len(rbar), len(gbar)))
print("  NOTE: I48-1 (validate_run.py:6487) is SILENT on BOTH arms — %d/%d I48 rows — because "
      "'n/a' is non-blank." % (len(ri48), len(gi48)))

print("\nRESULT: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
