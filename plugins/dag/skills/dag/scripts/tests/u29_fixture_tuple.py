#!/usr/bin/env python3
"""U29 FIXTURE 2 — the TEN members of `_I48_ORCH_FORBIDDEN`, pinned INDIVIDUALLY.

WHICH COPY IS PINNED: the PREDICATE's — the tuple literal at validate_run.py:6453-6456,
read for its size by tools/tuple_check.py.  NOT debrief.schema.json's mirror of the same
ten keys (the `not: {required: [...]}` allOf block on case_set_discharge.items).

U28's I48-3 fixture mutates via `check_form`, one of the FOUR keys registry text already
names, so the SIX it does not name are unpinned and a drop would be silent.  This fixture
mutates via EACH of the ten, one at a time, and asserts the PREDICATE's I48-3 row names it.

Isolation, and the disagreement demonstration, in three columns per key:

  A  pristine schema + pristine predicate   -> BOTH copies speak
  B  PATCHED schema (key removed from the schema's mirror) + pristine predicate
     -> schema SILENT, predicate must still FAIL.  Pins the PREDICATE's copy.
  C  pristine schema + PATCHED predicate (key deleted from the tuple)
     -> predicate SILENT, schema must still reject.  The converse disagreement.

B and C together are the demonstration that the two copies CAN disagree: each is a state
in which one copy rejects the row and the other does not.

  rc 0  control clean; all ten pinned in column B; both disagreement directions shown
  rc 1  otherwise
"""
import json, os, re, shutil, subprocess, sys, tempfile
import u29_fixture_base as mkfix

VR = os.path.join(mkfix.REPO, "plugins/dag/skills/dag/scripts/validate_run.py")
I48_3 = "re-states brief-owned key(s)"
SCHEMA_MSG = re.compile(r"debrief\.json .*(invalid|INVALID)|units/U01/debrief\.json")

WORK = "/private/tmp/u29/work"


def run(rundir, vr=VR, schemas=mkfix.SCHEMAS):
    r = subprocess.run(["python3", vr, rundir, "--schemas", schemas],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def i48_3_rows(out):
    return [l.strip() for l in out.splitlines() if I48_3 in l]


from jsonschema import Draft202012Validator

def schema_rejects(rundir, key, schemas=mkfix.SCHEMAS):
    """TRUE iff debrief.schema.json's OWN mirror rejects the row FOR THIS KEY.
    Attribution is exact: the offending subschema must be {"not": {"required": [key]}}."""
    s = json.load(open(os.path.join(schemas, "debrief.schema.json")))
    o = json.load(open(os.path.join(rundir, "units/U01/debrief.json")))
    for e in Draft202012Validator(s).iter_errors(o):
        if e.schema == {"not": {"required": [key]}}:
            return True
    return False


def patched_schemas(drop_key):
    """copy the schema dir, removing ONE key from debrief.schema.json's own mirror"""
    d = tempfile.mkdtemp(dir="/private/tmp", prefix="u29sch.")
    shutil.rmtree(d)
    shutil.copytree(mkfix.SCHEMAS, d)
    p = os.path.join(d, "debrief.schema.json")
    s = json.load(open(p))
    items = s["properties"]["case_set_discharge"]["items"]
    for blk in items["allOf"]:
        th = blk.get("then")
        if isinstance(th, dict) and isinstance(th.get("allOf"), list) and \
           any("not" in x for x in th["allOf"]):
            before = len(th["allOf"])
            th["allOf"] = [x for x in th["allOf"]
                           if x.get("not", {}).get("required") != [drop_key]]
            if len(th["allOf"]) == before - 1:
                json.dump(s, open(p, "w"), indent=1)
                return d, before, len(th["allOf"])
    raise SystemExit("could not patch schema mirror for %r" % drop_key)


def patched_vr(drop_key):
    """copy validate_run.py, deleting ONE member from the predicate's tuple literal"""
    src = open(VR).read()
    m = re.search(r'_I48_ORCH_FORBIDDEN\s*=\s*\((.*?)\)\n', src, re.S)
    assert m, "tuple literal not found"
    body = m.group(1)
    new = re.sub(r'"%s",?\s*' % re.escape(drop_key), "", body, count=1)
    assert new != body, drop_key
    out = src[:m.start(1)] + new + src[m.end(1):]
    d = tempfile.mkdtemp(dir="/private/tmp", prefix="u29vr.")
    p = os.path.join(d, "validate_run.py")
    open(p, "w").write(out)
    return p, d


ok = True

# ---------------------------------------------------------------- CONTROL
ctl = mkfix.build(os.path.join(WORK, "control"))
rc, out = run(ctl)
rows = i48_3_rows(out)
print("CONTROL  clean origin='orchestrator' row, no brief-owned key re-stated")
print("  I48-3 rows: %d   (expected 0)   %s" % (len(rows), "[ok ]" if not rows else "[BAD]"))
if rows:
    ok = False
    for r in rows:
        print("   ", r[:200])

# the block is ARMED — prove it, so 'no rows' is not 'no test'
armed = mkfix.build(os.path.join(WORK, "armed"))
p = os.path.join(WORK, "armed/units/U01/debrief.json")
d = json.load(open(p)); d["case_set_discharge"] = d["case_set_discharge"][:1]
json.dump(d, open(p, "w"), indent=1)
rc, out = run(armed)
shrink = [l.strip() for l in out.splitlines() if "SHRINK" in l]
print("  ARMED-CHECK: dropping the C2 row makes the block speak: %d SHRINK row(s) %s"
      % (len(shrink), "[ok ]" if shrink else "[BAD]"))
if not shrink:
    ok = False
else:
    print("   ", shrink[0][:180])

# ---------------------------------------------------------------- per key
print("\nPER-KEY, one key re-stated at a time on the C1 orchestrator row.")
print("  col A = pristine schema + pristine predicate")
print("  col B = PATCHED schema (key removed from schema mirror) + pristine predicate  <-- pins the PREDICATE")
print("  col C = pristine schema + PATCHED predicate (key removed from tuple)          <-- converse")
print()
print("  %-36s %-16s %-24s %-24s" % ("key", "named?", "A sch/pred", "B sch/pred   C sch/pred"))

results = {}
for key in mkfix.NAMED + mkfix.UNNAMED:
    rd = mkfix.build(os.path.join(WORK, "k_" + key), extra_on_C1={key: mkfix.VALUES[key]})

    rcA, outA = run(rd)
    A_pred = len(i48_3_rows(outA)) > 0 and key in " ".join(i48_3_rows(outA))
    A_sch = schema_rejects(rd, key)

    sd, n0, n1 = patched_schemas(key)
    rcB, outB = run(rd, schemas=sd)
    B_pred = len(i48_3_rows(outB)) > 0 and key in " ".join(i48_3_rows(outB))
    B_sch = schema_rejects(rd, key, schemas=sd)
    B_sch = schema_rejects(rd, key, schemas=sd)
    shutil.rmtree(sd)

    vp, vd = patched_vr(key)
    rcC, outC = run(rd, vr=vp)
    C_pred = len(i48_3_rows(outC)) > 0 and key in " ".join(i48_3_rows(outC))
    C_sch = schema_rejects(rd, key)
    shutil.rmtree(vd)

    results[key] = (A_sch, A_pred, B_sch, B_pred, C_sch, C_pred)
    good = (B_pred and not B_sch) and (C_sch and not C_pred)
    if not good:
        ok = False
    print("  %-36s %-10s %s/%s              %s/%s          %s/%s   %s"
          % (key, "NAMED" if key in mkfix.NAMED else "unnamed",
             "R" if A_sch else "-", "R" if A_pred else "-",
             "R" if B_sch else "-", "R" if B_pred else "-",
             "R" if C_sch else "-", "R" if C_pred else "-",
             "[ok ]" if good else "[BAD]"))

print("\n  (R = rejects the row, - = silent)")
print("  col B: schema silent, predicate rejects  -> the copies DISAGREE, predicate strictly stronger")
print("  col C: schema rejects, predicate silent  -> the copies DISAGREE, schema strictly stronger")
print("  A DROP FROM THE PREDICATE'S TUPLE IS THEREFORE NOT COVERED BY THE SCHEMA'S MIRROR,")
print("  and column B is the arm that would go green if the key were dropped.")

# a sample of the actual predicate row, for one UNNAMED key
rd = mkfix.build(os.path.join(WORK, "sample"),
                 extra_on_C1={"production_path": mkfix.VALUES["production_path"]})
sd, _, _ = patched_schemas("production_path")
_, out = run(rd, schemas=sd)
print("\nSAMPLE predicate row (unnamed key 'production_path', schema mirror patched silent):")
for r in i48_3_rows(out):
    print("   ", r[:230])
shutil.rmtree(sd)

print("\nRESULT: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
