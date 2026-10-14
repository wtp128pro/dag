#!/usr/bin/env python3
"""i48_crash_class.py — AST census of the iterate-over-`.get()` crash class, BY NODE KIND.

WHAT THE CLASS IS  (NARROWED IN v2 — see KNOWN GAPS bullet 2)
    A site where the value returned by a `<expr>.get(...)` call — possibly laundered through
    `or <default>` — is consumed by an ITERATION context. Gate state is NOT part of the
    definition and is NOT measured. When the artifact supplies a truthy non-iterable
    (`required_observations: 5`) the site raises an uncaught `TypeError` and aborts `main()`
    BEFORE any `RESULT:` line, which is indistinguishable from a legitimate FAIL (both rc 1)
    and takes every later armed invariant down with it.

    The class is enumerated HERE BY NODE KIND, from source, across the whole file. It is NOT a
    hand-written list of loci: the file measures hundreds of sites, so a per-site list is not a
    fix and is not offered as one.

CONSUMER KINDS RECOGNISED (this is the node-kind enumeration; `--kinds` prints it)
    for-iter, comprehension-iter, call-arg-iterable (list/set/tuple/sorted/any/all/sum/len/
    enumerate/reversed/dict/frozenset/max/min/zip/map/filter/"".join), starred-splat,
    tuple-unpack-rhs, method-arg-iterable (.extend/.update/.issubset/.union/...), membership-rhs.

WHY THE FROZEN C3 PROBE IS ONLY A PROXY  (READ THIS BEFORE TRUSTING A GREEN)
    C3 censuses `list(<BoolOp>)` — ONE syntactic shape of ONE consumer kind. A repair that
    deletes the shape turns C3 green WITHOUT the behaviour holding: replacing
    `list(x or [])` with `if not isinstance(x, list): continue` removes the pattern and
    SILENTLY SKIPS the malformed field, producing neither a naming report row nor a defect.
    That is exactly the mutant that defeated U25's C4. The BEHAVIOURAL property is therefore
    the check of record — tested by `i48_clause_matrix.py --behaviour` at U25's landed locus and
    by `--survivors` HERE at the two shipped survivor loci:

        a non-iterable at an I48 observation-list locus MUST produce a naming report row
        AND a real `RESULT:` line — never an uncaught TypeError, and never a silent skip.

KNOWN GAPS (disclosed, not defended — all four MEASURED, none merely asserted)
    * Static and syntactic. A `.get()` bound to a name and iterated three statements later is
      NOT counted (no dataflow). The census is therefore a LOWER bound on the class.
    * NO GATE DETECTION AT ALL. v1 of this docstring claimed `isinstance`-gating "is detected"
      in the dominating-statement form. That was FALSE — `census()` has no gate logic and every
      `isinstance` in this module is ast-node dispatch. The claim is RETRACTED, not narrowed:
      a gated site and an ungated site are counted alike, so the census is "sites in the class,
      GATE-STATE UNMEASURED" and must never be restated as "sites that remain UNGATED".
      Direction of the resulting bias, measured on validate_run.py: implementing the literal
      dominating-`isinstance` detector removes 3 of 192 (1.6%); the loosest possible gate credit
      removes at most 6 (3.1%). Against the under-counts below, 192 stays a strict LOWER bound.
    * Consumer kinds are a closed list, and the list is ITERATION consumers only. HASH consumers
      are NOT enumerated — measured on validate_run.py, membership-LHS 53 + subscript-key 8 +
      set-method(.add/.discard/.remove) 7 = 68 further crash-capable sites this instrument does
      not see. Reproduce with `--hashprobe`.
    * `or`/`and` laundering is unwrapped; TERNARY (`ast.IfExp`) laundering is NOT. Measured:
      teaching `_unwrap` about `ast.IfExp` alone moves the census 192 -> 210 (+18); restored
      control 192. Reproduce with `--hashprobe`.

USAGE
    python3 i48_crash_class.py --census [--file F] [--lo N --hi N] [--json]
    python3 i48_crash_class.py --kinds
    python3 i48_crash_class.py --hashprobe                # size the two disclosed under-counts
    python3 i48_crash_class.py --survivors                # the BEHAVIOURAL family, one per survivor
    python3 i48_crash_class.py --provenance --base <ref>  # L27 control: census vs the run's BASE
NOT HERE: `--behaviour` (U25's landed locus + the silent-skip counterfactual) lives in the
    sibling `i48_clause_matrix.py`. v1 of this USAGE advertised it here; it never existed here.
"""
import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TARGET = os.path.join(os.path.dirname(HERE), "validate_run.py")
# validate_run.py defaults --schemas to `<dir of the INVOKED script>/../schemas`. survivors()
# writes PATCHED COPIES into tempfile.mkdtemp(), so an invocation without --schemas resolves to
# `$TMPDIR/schemas` — present on this host as pre-run debris (Jul 5-29, `grep -c case_set` -> 0
# against the repo's 12) and ABSENT on a clean host, where the GREEN ARM then reads "harness BUG:
# property unsatisfiable". Pass it EXPLICITLY at every invocation so the arms are comparable and
# the figures are not machine-local.
# NB the level: HERE is scripts/tests, so the schemas dir is TWO up (skills/dag/schemas), not one
# — scripts/schemas does not exist, and pointing there reproduces the same defect with a different
# empty directory (measured: CONTROL itself goes RED, "NO RESULT: line").
SCHEMAS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "schemas")
assert os.path.isdir(SCHEMAS), f"schemas dir not found at {SCHEMAS}"

ITER_BUILTINS = {"list", "set", "tuple", "sorted", "any", "all", "sum", "len", "enumerate",
                 "reversed", "dict", "frozenset", "max", "min", "zip", "map", "filter"}
ITER_METHODS = {"extend", "update", "join", "issubset", "issuperset", "union", "intersection",
                "difference", "symmetric_difference"}
KINDS = ("for-iter", "comprehension-iter", "call-arg-iterable", "starred-splat",
         "tuple-unpack-rhs", "method-arg-iterable", "membership-rhs")


def _unwrap(node):
    """Strip `or`/`and` laundering; return the leaf operands that could be the .get() value."""
    if isinstance(node, ast.BoolOp):
        out = []
        for v in node.values:
            out.extend(_unwrap(v))
        return out
    return [node]


def _is_get_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get")


def _get_sites(node):
    """True if any leaf under `or`/`and` laundering is a `.get(...)` call."""
    return [n for n in _unwrap(node) if _is_get_call(n)]


def census(path, lo=None, hi=None):
    src = open(path).read()
    tree = ast.parse(src)
    hits = []

    def add(kind, node, expr):
        for g in _get_sites(expr):
            if lo is not None and not (lo <= node.lineno <= hi):
                return
            hits.append({"kind": kind, "line": node.lineno,
                         "src": ast.get_source_segment(src, expr) or "",
                         "get_line": g.lineno})

    for n in ast.walk(tree):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            add("for-iter", n, n.iter)
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for c in n.generators:
                add("comprehension-iter", n, c.iter)
        elif isinstance(n, ast.Starred):
            add("starred-splat", n, n.value)
        elif isinstance(n, ast.Assign) and any(isinstance(t, (ast.Tuple, ast.List))
                                               for t in n.targets):
            add("tuple-unpack-rhs", n, n.value)
        elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn))
                                                for o in n.ops):
            for cmp_ in n.comparators:
                add("membership-rhs", n, cmp_)
        elif isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id in ITER_BUILTINS:
                for a in n.args:
                    add("call-arg-iterable", n, a)
            elif isinstance(n.func, ast.Attribute) and n.func.attr in ITER_METHODS:
                for a in n.args:
                    add("method-arg-iterable", n, a)
    hits.sort(key=lambda h: (h["line"], h["kind"]))
    return hits


# ------------------------------------------------------- the SURVIVOR behavioural family (L6698/L6705)
# The 27-fixture clause matrix CANNOT cover the crash class: its coverage relation is over
# `rep.fail` SITES, and a crash site is BY DEFINITION NOT a rep.fail site — a site that crashes
# emits no row at all. So the crash class needs THIS separate behavioural family instead, in the
# shape of CX1: one member per known survivor, asserting the property directly.
#
#     PROPERTY: a truthy non-iterable at a survivor locus MUST produce a NAMING report row
#               AND a real `RESULT:` line — never an uncaught TypeError.
#
# S1 exercises L6698; S2 exercises L6705, which is SHADOWED by L6698 on the shipped tree (both
# iterate the same expression, so the first crash pre-empts the second). S2 therefore runs against
# a tempdir copy with L6698 ALONE guarded, which proves L6705 is an INDEPENDENT survivor rather
# than a second reading of the same site. The GREEN arm (both guarded) proves the assertion is
# SATISFIABLE — without it a family that is red on every input would prove nothing.
_AC = '_b.get("acceptance_criteria")'
_G6698 = f'_cunh = [repr(c) for c in ({_AC} or [])'
_G6705 = f'_crit = {{c for c in ({_AC} or []) if _i48_hashable(c)}}'
_SAFE = f'({_AC} if isinstance({_AC}, list) else [])'
_NAMING = ('                if _b.get("acceptance_criteria") is not None and not isinstance(\n'
           '                        _b.get("acceptance_criteria"), list):\n'
           '                    rep.fail(_lbl, "brief.acceptance_criteria is "\n'
           '                             f\'{type(_b.get("acceptance_criteria")).__name__} \'\n'
           '                             f\'{_b.get("acceptance_criteria")!r}, not an array\')\n')


def _patch_vr(src, guard_6698, guard_6705, naming):
    out = src
    if guard_6698:
        out = out.replace(_G6698, f'_cunh = [repr(c) for c in {_SAFE}', 1)
    if guard_6705:
        out = out.replace(_G6705, f'_crit = {{c for c in {_SAFE} if _i48_hashable(c)}}', 1)
    if naming:
        out = out.replace("                _cunh = [repr(c)", _NAMING + "                _cunh = [repr(c)", 1)
    return out


def survivors():
    sys.path.insert(0, HERE)
    import i48_clause_matrix as M
    import shutil
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp(prefix="i48sv-")
    # validate_run.py imports frame_match from ITS OWN directory and exits 3 without it, so the
    # patched copies written into tmp need the matcher beside them — or S2/GREEN judge the import.
    shutil.copy2(os.path.join(os.path.dirname(DEFAULT_TARGET), "frame_match.py"), tmp)
    src = open(DEFAULT_TARGET).read()

    def run(vr, run_dir):
        p = subprocess.run([sys.executable, vr, run_dir, "--schemas", SCHEMAS],
                           capture_output=True, text=True,
                           env=dict(os.environ, HOME=tempfile.mkdtemp()))
        return p.stdout + p.stderr

    def write(name, text):
        assert text != src, f"{name}: patch was a NO-OP — refusing a green that proves nothing"
        path = os.path.join(tmp, name)
        open(path, "w").write(text)
        return path

    def mutate(run_dir):                       # the single mutation: a TRUTHY NON-ITERABLE
        M.make_base(run_dir)
        b = os.path.join(run_dir, "units/U01/brief.json")
        o = json.load(open(b))
        o["acceptance_criteria"] = 5
        json.dump(o, open(b, "w"), indent=2)
        return run_dir

    rows, ok = [], True
    ctl = run(DEFAULT_TARGET, M.make_base(os.path.join(tmp, "control")))
    rows.append(("CONTROL   unmutated base, shipped validate_run.py",
                 "RESULT:" in ctl and "Traceback" not in ctl,
                 "one RESULT: line, no traceback" if "RESULT:" in ctl else "NO RESULT: line"))

    s1 = run(DEFAULT_TARGET, mutate(os.path.join(tmp, "s1")))
    s1_ok = "not an array" in s1 and "RESULT:" in s1
    rows.append(("S1        L6698, shipped validate_run.py", s1_ok,
                 "naming row + RESULT:" if s1_ok else
                 f"CRASH: {'line 6698' if 'line 6698' in s1 else '?'} "
                 f"TypeError={'TypeError' in s1} RESULT:line={'RESULT:' in s1}"))

    vr2 = write("vr_6698_guarded.py", _patch_vr(src, True, False, False))
    s2 = run(vr2, mutate(os.path.join(tmp, "s2")))
    s2_ok = "not an array" in s2 and "RESULT:" in s2
    rows.append(("S2        L6705, with L6698 ALONE guarded", s2_ok,
                 "naming row + RESULT:" if s2_ok else
                 f"CRASH: {'line 6705' if 'line 6705' in s2 else '?'} "
                 f"TypeError={'TypeError' in s2} RESULT:line={'RESULT:' in s2}"))

    vr3 = write("vr_both_guarded.py", _patch_vr(src, True, True, True))
    g = run(vr3, mutate(os.path.join(tmp, "green")))
    g_ok = "not an array" in g and "RESULT:" in g
    rows.append(("GREEN ARM both guarded + naming row (satisfiability)", g_ok,
                 "naming row + RESULT:" if g_ok else "harness BUG: property unsatisfiable"))

    print("SURVIVOR behavioural family — property: naming row AND a real RESULT: line")
    for name, good, note in rows:
        print(f"  [{'ok ' if good else 'RED'}] {name}: {note}")
        ok = ok and good
    if not ok:
        print("\nRED is the CORRECT and HONEST outcome on the shipped tree: L6698/L6705 are")
        print("UNGUARDED, so the property does not hold.")
        # The satisfiability claim is a claim ABOUT THE GREEN ARM, so it may only be printed when
        # the GREEN ARM actually passed. Printed unconditionally (as it was), a run whose GREEN ARM
        # is RED asserts the property is satisfiable in the same breath as disproving it.
        if g_ok:
            print("The GREEN ARM above shows the assertion is satisfiable, so this family is a")
            print("live test and not a check that can only fail.")
        else:
            print("The GREEN ARM above is ALSO RED, so satisfiability is NOT shown by this run and")
            print("is NOT claimed. A red GREEN ARM indicts the HARNESS, not validate_run.py:")
            print("the expected reading is S1/S2 RED with the GREEN ARM ok.")
        print("U28 did not edit validate_run.py (byte-identical to HEAD); the guard is wave 7's.")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


# ------------------------------------------------------------------- L27: control against the BASE
def _sha(path):
    import hashlib
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def provenance(target, base_ref):
    """Census `target` against `git show <base_ref>:<target>` — with a NON-IDENTITY assertion.

    L27: a control is only a control if the two sides CAN differ. An empty diff is an INVALID
    control (rc 2), never a passing one. Controlling against HEAD once a run has committed its
    own work compares a file WITH ITSELF and returns equality by construction.
    """
    import subprocess
    import tempfile
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                          text=True, cwd=os.path.dirname(target)).stdout.strip()
    rel = os.path.relpath(os.path.abspath(target), repo)
    blob = subprocess.run(["git", "show", f"{base_ref}:{rel}"], capture_output=True, text=True,
                          cwd=repo)
    if blob.returncode:
        print(f"INVALID: `git show {base_ref}:{rel}` failed: {blob.stderr.strip()}")
        return 2
    bp = os.path.join(tempfile.mkdtemp(prefix="i48pv-"), "base.py")
    open(bp, "w").write(blob.stdout)
    st, sb = _sha(target), _sha(bp)
    print(f"target {rel}\n  sha256(worktree) = {st}\n  sha256({base_ref})   = {sb}")
    if st == sb:
        print("INVALID CONTROL: the two sides are BYTE-IDENTICAL. This comparison cannot return")
        print("a different answer, so it proves the identity and not the property (L27). rc 2.")
        return 2
    # BYTE non-identity is NOT census non-identity. It rules out only the degenerate control (a
    # file compared with itself); it does not license "the control CAN return a different answer",
    # which is a claim about the CENSUS. Measured falsification: a whitespace-only base differs in
    # bytes and still gives census 192 vs 192, delta +0. The census property is decided below, by
    # the delta, which is also this function's exit code — so state the byte fact and stop there.
    print("  -> sides differ IN BYTES: not the degenerate self-comparison. Whether the CENSUS can")
    print("     differ is a separate question, decided by the delta below (whitespace-only edits")
    print("     differ in bytes at delta +0).")
    h, b = census(target), census(bp)
    import collections
    ch = collections.Counter((x["kind"], x["src"]) for x in h)
    cb = collections.Counter((x["kind"], x["src"]) for x in b)
    print(f"census(worktree) = {len(h)}   census({base_ref}) = {len(b)}   delta = {len(h) - len(b):+d}")
    print("  ADDED by this run   (worktree minus base):")
    for k, n in sorted((ch - cb).items()):
        print(f"    +{n}  {k[0]:20s} {k[1]}")
    if not (ch - cb):
        print("    (none)")
    print("  REMOVED             (base minus worktree):")
    for k, n in sorted((cb - ch).items()):
        print(f"    -{n}  {k[0]:20s} {k[1]}")
    if not (cb - ch):
        print("    (none)")
    # "pure addition" needs BOTH sides: something added AND nothing removed. With an empty ADDED
    # set the old line refuted nothing — it printed "pure addition" over no addition at all.
    if (ch - cb) and not (cb - ch):
        print("    -> ADDED non-empty and REMOVED empty: PURE ADDITION, so 'relocated rather than")
        print("       added' is refuted.")
    elif not (ch - cb) and not (cb - ch):
        print("    -> both sides empty: the two censuses are IDENTICAL as multisets. Nothing is")
        print("       added, so 'relocated rather than added' is NOT refuted — it is untested.")
    return 0 if len(h) != len(b) else 1


def hashprobe(path):
    """Size the two disclosed under-counts: HASH consumers, and ast.IfExp laundering."""
    src = open(path).read()
    tree = ast.parse(src)
    hits = []

    def add(kind, node, expr):
        for _ in _get_sites(expr):
            hits.append((kind, node.lineno))
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops):
            add("membership-lhs-hash", n, n.left)     # `x in <set>` HASHES x
        elif isinstance(n, ast.Subscript):
            add("subscript-key-hash", n, n.slice)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("add", "discard", "remove"):
            for a in n.args:
                add("setmethod-hash", n, a)
    by = {}
    for k, _ in hits:
        by[k] = by.get(k, 0) + 1
    print(f"HASH consumers NOT enumerated by --census in {os.path.basename(path)}: {len(hits)}")
    for k in sorted(by):
        print(f"  {k:22s} {by[k]}")
    baseline = len(census(path))
    global _unwrap
    orig = _unwrap

    def with_ifexp(node):
        if isinstance(node, ast.IfExp):
            return with_ifexp(node.body) + with_ifexp(node.orelse)
        if isinstance(node, ast.BoolOp):
            out = []
            for v in node.values:
                out.extend(with_ifexp(v))
            return out
        return [node]
    _unwrap = with_ifexp
    widened = len(census(path))
    _unwrap = orig
    restored = len(census(path))
    print(f"ITERATION census: {baseline}   with ast.IfExp laundering: {widened} "
          f"({widened - baseline:+d})   restored control: {restored}")
    return 0 if restored == baseline else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_TARGET)
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--kinds", action="store_true")
    ap.add_argument("--survivors", action="store_true")
    ap.add_argument("--hashprobe", action="store_true")
    ap.add_argument("--provenance", action="store_true")
    ap.add_argument("--base", help="git ref of the run's BASE commit (L27); never HEAD")
    ap.add_argument("--lo", type=int)
    ap.add_argument("--hi", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.survivors:
        return survivors()
    if a.hashprobe:
        return hashprobe(a.file)
    if a.provenance:
        if not a.base:
            print("--provenance requires --base <ref> (the run's BASE commit, never HEAD)")
            return 2
        return provenance(a.file, a.base)
    if a.kinds:
        print("consumer node kinds enumerated:", len(KINDS))
        for k in KINDS:
            print("  ", k)
        return 0
    h = census(a.file, a.lo, a.hi)
    by = {}
    for x in h:
        by[x["kind"]] = by.get(x["kind"], 0) + 1
    if a.json:
        print(json.dumps({"total": len(h), "by_kind": by, "sites": h}, indent=1))
    else:
        scope = f" lines {a.lo}-{a.hi}" if a.lo else " whole file"
        print(f"iterate-over-.get() class in {os.path.basename(a.file)}{scope}: {len(h)} sites")
        for k in KINDS:
            print(f"  {k:22s} {by.get(k, 0)}")
    return 0 if h else 1


if __name__ == "__main__":
    sys.exit(main())
