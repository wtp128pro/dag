#!/usr/bin/env python3
"""validate_run.py — enforcement layer for the dag pipeline.

Validates the machine-checkable JSON extracts of a run directory against the
Draft-2020-12 JSON Schemas in ../schemas, then checks the FSM invariants that
schemas alone cannot express.

Reconciled seams over the pipeline contract:
  * Socratic seam adopts the canonical 4-key block {premise,counter,pivot,confidence}
    (in debrief + verify; the brief carries only a protocol REFERENCE). counter must
    record an OUTCOME (I13); mechanical-unit sentinel allowed.
  * Loop/verdict seam adopts the final loop contract (feedback.actionable_changes,
    top-level defects[], PASS=>[], FAIL=>>=1 defect each naming a brief criterion,
    DISAGREE=>disagreement, loop.state in the Q vocabulary).
  * Tags + V_tag (graph.v_tag) membership (I11) + the learnings-propagation
    predicate with admission gate (I12).
  * MUST-FIX D — missing verification is now REJECTED (I9): any unit dir with a
    debrief MUST have a verify.json with a verdict; at P8/DONE every such unit must be
    PASS (I10).
  * MUST-FIX E — graph acyclicity is now FAIL-CLOSED (I3): if GRAPH.md exists, a VALID
    authoritative graph.json is REQUIRED; cycles are detected on the union of `edges`
    and edges derived from each unit's `deps`. An unparseable/absent graph.json is a
    VIOLATION, not a silent skip.
  * Premise-check — the verifier's premise_check attestation (the independent COUNTER re-run) is enforced.

Exit codes:  0 ok · 1 validation/invariant violation · 2 usage error · 3 environment error.
Usage:  validate_run.py <run_dir> [--schemas <dir>] [--self-check] [--quiet]
"""
from __future__ import annotations
import json, os, re, sys, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMAS = os.path.normpath(os.path.join(HERE, "..", "schemas"))

TOP_ARTIFACTS = {
    "personas.json": "personas.schema.json",
    "clarifications.json": "clarifications.schema.json",
    "cartography.json": "cartography.schema.json",
    "graph.json": "graph.schema.json",
    "fsm-state.json": "fsm-state.schema.json",
}
UNIT_ARTIFACTS = {
    "brief.json": "brief.schema.json",
    "debrief.json": "debrief.schema.json",
    "verify.json": "verify.schema.json",
    "disagreement.json": "disagreement.schema.json",
}

# counter values that do NOT record an outcome (I13). The mechanical sentinel is a
# full sentence and never collides with these.
BLANK_COUNTER = {"", "n/a", "na", "none", "-", "--", "tbd", "todo", "null", "pending"}
MECH_SENTINEL = "unit is mechanical; no material premise to break"

# ---------------------------------------------------------------------------
# Minimal Draft-2020-12 validator (subset used by our schemas). Real rejection.
# ---------------------------------------------------------------------------
def _pytype(v):
    if isinstance(v, bool): return "boolean"
    if isinstance(v, int): return "integer"
    if isinstance(v, float): return "number"
    if isinstance(v, str): return "string"
    if isinstance(v, list): return "array"
    if isinstance(v, dict): return "object"
    if v is None: return "null"
    return type(v).__name__

def _type_ok(v, t):
    if t == "object": return isinstance(v, dict)
    if t == "array": return isinstance(v, list)
    if t == "string": return isinstance(v, str)
    if t == "boolean": return isinstance(v, bool)
    if t == "null": return v is None
    if t == "integer":
        if isinstance(v, bool): return False
        if isinstance(v, int): return True
        return isinstance(v, float) and v.is_integer()
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return True

def _resolve_ref(ref, root):
    """Resolve an intra-document JSON Pointer $ref (e.g. '#/$defs/entry') against `root`.
    Returns the target subschema dict, or None for an unresolved/external ref (stdlib-only:
    no remote fetching)."""
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    node = root
    for part in ref.lstrip("#").lstrip("/").split("/"):
        if part == "":
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node

def _mini_validate(inst, schema, path="$", root=None, _seen=frozenset()):
    errs = []
    if not isinstance(schema, dict):
        return errs
    if root is None:
        root = schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref not in _seen:                     # guard against a self-referential $ref loop
            target = _resolve_ref(ref, root)
            if isinstance(target, dict):
                errs += _mini_validate(inst, target, path, root, _seen | {ref})
        # 2020-12: sibling keywords alongside $ref still apply — fall through and evaluate them.
    if "type" in schema:
        types = schema["type"]
        types = types if isinstance(types, list) else [types]
        if not any(_type_ok(inst, t) for t in types):
            errs.append(f"{path}: expected type {types}, got {_pytype(inst)}")
            return errs
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{path}: must equal const {schema['const']!r}, got {inst!r}")
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in enum {schema['enum']}")
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append(f"{path}: {inst} < minimum {schema['minimum']}")
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append(f"{path}: {inst} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and inst <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: {inst} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and inst >= schema["exclusiveMaximum"]:
            errs.append(f"{path}: {inst} >= exclusiveMaximum {schema['exclusiveMaximum']}")
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append(f"{path}: string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            errs.append(f"{path}: string longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], inst) is None:
            errs.append(f"{path}: {inst!r} does not match pattern {schema['pattern']!r}")
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errs.append(f"{path}: array has {len(inst)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(inst) > schema["maxItems"]:
            errs.append(f"{path}: array has {len(inst)} items > maxItems {schema['maxItems']}")
        if schema.get("uniqueItems") and len(inst) != len({json.dumps(x, sort_keys=True) for x in inst}):
            errs.append(f"{path}: array items not unique")
        if "items" in schema:
            for i, el in enumerate(inst):
                errs += _mini_validate(el, schema["items"], f"{path}[{i}]", root)
    if isinstance(inst, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in inst:
                errs.append(f"{path}: missing required property '{req}'")
        ap = schema.get("additionalProperties", True)
        for k, v in inst.items():
            if k in props:
                errs += _mini_validate(v, props[k], f"{path}.{k}", root)
            elif ap is False:
                errs.append(f"{path}: additional property '{k}' not allowed")
            elif isinstance(ap, dict):
                errs += _mini_validate(v, ap, f"{path}.{k}", root)
    for kw in ("allOf",):
        for sub in schema.get(kw, []):
            errs += _mini_validate(inst, sub, path, root)
    if "anyOf" in schema:
        if not any(not _mini_validate(inst, sub, path, root) for sub in schema["anyOf"]):
            errs.append(f"{path}: does not match anyOf")
    if "oneOf" in schema:
        n = sum(1 for sub in schema["oneOf"] if not _mini_validate(inst, sub, path, root))
        if n != 1:
            errs.append(f"{path}: matched {n} oneOf subschemas (need exactly 1)")
    if "if" in schema:
        if not _mini_validate(inst, schema["if"], path, root):
            if "then" in schema:
                errs += _mini_validate(inst, schema["then"], path, root)
        elif "else" in schema:
            errs += _mini_validate(inst, schema["else"], path, root)
    return errs

def make_validator():
    try:
        import jsonschema  # type: ignore
        from jsonschema import Draft202012Validator
        def _v(inst, schema):
            return [f"$.{'/'.join(map(str, e.path))}: {e.message}" if e.path else f"$: {e.message}"
                    for e in sorted(Draft202012Validator(schema).iter_errors(inst),
                                    key=lambda e: [str(p) for p in e.path])]
        return _v, "jsonschema library (Draft202012Validator)"
    except Exception:
        return _mini_validate, "built-in minimal validator (stdlib only)"

# ---------------------------------------------------------------------------
# GRAPH.md fenced-edge parser + cycle detection (secondary / defense-in-depth).
# ---------------------------------------------------------------------------
def parse_graph_edges(md_text):
    edges, in_block = [], False
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        norm = line.replace("->", "→")
        if "→" not in norm:
            continue
        segs = norm.split("→")
        node_lists = [re.findall(r"U[0-9]{2,}", s) for s in segs]
        for i in range(len(node_lists) - 1):
            for a in node_lists[i]:
                for b in node_lists[i + 1]:
                    edges.append((a, b))
    return edges

def md_has_unfenced_deps(md_text):
    """True if GRAPH.md contains U-id dependency arrows OUTSIDE any code fence."""
    in_block = False
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            continue
        norm = line.replace("->", "→")
        if "→" in norm and len(re.findall(r"U[0-9]{2,}", norm)) >= 2:
            return True
    return False

def find_cycle(edges):
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    def dfs(n, stack):
        color[n] = GREY
        stack.append(n)
        for m in adj[n]:
            if color[m] == GREY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                r = dfs(m, stack)
                if r:
                    return r
        color[n] = BLACK
        stack.pop()
        return None
    for n in list(adj):
        if color[n] == WHITE:
            r = dfs(n, [])
            if r:
                return r
    return None

# ---------------------------------------------------------------------------
class Report:
    def __init__(self, quiet=False):
        self.problems = []
        self.checked = []
        self.quiet = quiet
    def ok(self, what):
        self.checked.append(what)
        if not self.quiet:
            print(f"  PASS  {what}")
    def fail(self, what, detail):
        self.problems.append((what, detail))
        print(f"  FAIL  {what}: {detail}")

def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a dag run directory.")
    ap.add_argument("run_dir", nargs="?", help="path to the run directory")
    ap.add_argument("--schemas", default=DEFAULT_SCHEMAS)
    ap.add_argument("--self-check", action="store_true",
                    help="meta-validate the schema files themselves, then exit")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    validate, backend = make_validator()
    print(f"validate_run.py — backend: {backend}")

    if not os.path.isdir(args.schemas):
        print(f"ERROR: schemas dir not found: {args.schemas}", file=sys.stderr)
        return 3
    schema_files = sorted(f for f in os.listdir(args.schemas) if f.endswith(".schema.json"))
    rep = Report(quiet=args.quiet)
    print(f"\n== schema self-check ({len(schema_files)} files) ==")
    schemas = {}
    for sf in schema_files:
        try:
            s = load_json(os.path.join(args.schemas, sf))
        except Exception as e:
            rep.fail(f"schema {sf}", f"not valid JSON: {e}")
            continue
        if "$schema" not in s or "type" not in s:
            rep.fail(f"schema {sf}", "missing $schema or type")
            continue
        schemas[sf] = s
        rep.ok(f"schema {sf} well-formed")
    if args.self_check:
        return _finish(rep)

    if not args.run_dir:
        print("ERROR: run_dir is required (unless --self-check)", file=sys.stderr)
        return 2
    if not os.path.isdir(args.run_dir):
        print(f"ERROR: run_dir not found: {args.run_dir}", file=sys.stderr)
        return 2

    rd = args.run_dir
    docs = {}

    def check_artifact(rel, schema_file, key):
        p = os.path.join(rd, rel)
        if not os.path.exists(p):
            return
        try:
            inst = load_json(p)
        except Exception as e:
            rep.fail(rel, f"not valid JSON: {e}")
            return
        s = schemas.get(schema_file)
        if s is None:
            rep.fail(rel, f"no schema loaded for {schema_file}")
            return
        errs = validate(inst, s)
        if errs:
            for e in errs:
                rep.fail(rel, e)
        else:
            docs[key] = inst
            rep.ok(f"{rel} valid against {schema_file}")

    print(f"\n== artifact schema validation ({rd}) ==")
    for rel, sf in TOP_ARTIFACTS.items():
        check_artifact(rel, sf, rel.replace(".json", ""))

    units_dir = os.path.join(rd, "units")
    unit_docs = {}
    unit_dirs_with_debrief = set()
    # Any per-unit artifact — brief/debrief/verify/disagreement, in EITHER the .md primary
    # or the .json extract — marks real post-Phase-1 work under this unit. Detection must be
    # symmetric across name AND extension, else an .md-only unit (e.g. brief.md, verify.md)
    # would be invisible and could skip the persona gate (G-personas non-skippable).
    unit_dirs_with_work = set()
    # EVERY units/<Uxx>/ subdirectory (even one with no artifacts yet) is a post-clarification
    # STRUCTURAL signal: decomposition has already carved the plan into unit dirs. Used by the
    # broadened I-dod trigger (A8) so deleting cartography while keeping the unit tree cannot
    # bypass the DoD requirement. Kept separate from unit_dirs_with_work (which needs a primary
    # artifact) to stay fail-closed on the bare-directory case too.
    unit_subdirs = set()
    UNIT_PRIMARIES = ("brief", "debrief", "verify", "disagreement")
    if os.path.isdir(units_dir):
        for uid in sorted(os.listdir(units_dir)):
            udir = os.path.join(units_dir, uid)
            if not os.path.isdir(udir):
                continue
            unit_subdirs.add(uid)
            if any(os.path.exists(os.path.join(udir, f"{name}.{ext}"))
                   for name in UNIT_PRIMARIES for ext in ("md", "json")):
                unit_dirs_with_work.add(uid)
            if os.path.exists(os.path.join(udir, "debrief.json")) or \
               os.path.exists(os.path.join(udir, "debrief.md")):
                unit_dirs_with_debrief.add(uid)
            for rel, sf in UNIT_ARTIFACTS.items():
                p = os.path.join(udir, rel)
                if not os.path.exists(p):
                    continue
                try:
                    inst = load_json(p)
                except Exception as e:
                    rep.fail(f"units/{uid}/{rel}", f"not valid JSON: {e}")
                    continue
                s = schemas.get(sf)
                if s is None:
                    rep.fail(f"units/{uid}/{rel}", f"no schema loaded for {sf}")
                    continue
                errs = validate(inst, s)
                if errs:
                    for e in errs:
                        rep.fail(f"units/{uid}/{rel}", e)
                else:
                    unit_docs.setdefault(uid, {})[rel.replace(".json", "")] = inst
                    rep.ok(f"units/{uid}/{rel} valid against {sf}")
                    # D21: an artifact's declared unit_id MUST match its containing directory.
                    aid = inst.get("unit_id")
                    if aid is not None and aid != uid:
                        rep.fail(f"units/{uid}/{rel} unit_id mismatch",
                                 f"artifact declares unit_id {aid!r} but lives in directory {uid!r}")

    # optional machine-readable learnings ledger — schema'd sidecar (D01). Each entry is
    # validated against learnings.schema.json ($defs/entry). A malformed entry is REPORTED
    # (rep.fail) and DROPPED, so it can never reach the I12 `since_wave >=` comparison below
    # (which the crash-guard there also hardens against a TypeError). The loader tolerates both
    # the canonical {entries:[...]} object and a bare top-level array.
    learnings = []
    lp = os.path.join(rd, "learnings.json")
    if os.path.exists(lp):
        raw_entries = []
        try:
            raw = load_json(lp)
            raw_entries = raw.get("entries", []) if isinstance(raw, dict) else raw
            if not isinstance(raw_entries, list):
                rep.fail("learnings.json", "expected an array (or {entries:[...]})")
                raw_entries = []
        except Exception as e:
            rep.fail("learnings.json", f"not valid JSON: {e}")
            raw_entries = []
        _ls = schemas.get("learnings.schema.json")
        entry_schema = (_ls.get("$defs", {}) or {}).get("entry") if isinstance(_ls, dict) else None
        for i, E in enumerate(raw_entries):
            if entry_schema is not None:
                errs = validate(E, entry_schema)
                if errs:
                    for e in errs:
                        rep.fail(f"learnings.json[{i}]", e)
                    continue  # DROP malformed entry — it must not reach the I12 comparison
            elif not isinstance(E, dict):
                rep.fail(f"learnings.json[{i}]", "entry is not an object")
                continue
            learnings.append(E)

    # ---- FSM invariants ----------------------------------------------------
    print("\n== FSM invariants ==")

    fsm = docs.get("fsm-state")
    phase = fsm.get("phase") if fsm else None
    gates = fsm.get("gates", {}) if fsm else {}
    POST_DECOMP_PHASES = {"P5_BRIEFING", "P6_EXECUTE_VERIFY",
                          "P7_DISAGREEMENT_GATE", "P8_SYNTHESIS", "DONE"}
    post_decomposition = bool(gates.get("decomposition_approved")) or phase in POST_DECOMP_PHASES

    # I3 DAG acyclicity — FAIL-CLOSED (MUST-FIX E). graph.json is authoritative.
    graph_md = os.path.join(rd, "GRAPH.md")
    graph_md_exists = os.path.exists(graph_md)
    graph_json_exists = os.path.exists(os.path.join(rd, "graph.json"))
    graph_doc = docs.get("graph")  # present only if graph.json parsed AND schema-valid

    # Once decomposition is approved, an authoritative graph.json MUST exist — you
    # cannot reach P5+ by deleting BOTH GRAPH.md and graph.json (fail-closed).
    if post_decomposition and graph_doc is None:
        rep.fail("I3 DAG fail-closed (E)",
                 f"phase/gates indicate post-decomposition ({phase}) but no VALID authoritative "
                 f"graph.json (graph.json {'invalid' if graph_json_exists else 'absent'}) — "
                 "refusing to advance without an enforceable DAG")
    if graph_md_exists and graph_doc is None:
        rep.fail("I3 DAG fail-closed (E)",
                 "GRAPH.md present but no VALID authoritative graph.json edge set "
                 f"(graph.json {'invalid' if graph_json_exists else 'absent'}) — "
                 "refusing to pass an unverified graph")
    if graph_doc is not None:
        edges = [(e["from"], e["to"]) for e in graph_doc.get("edges", [])]
        for u in graph_doc.get("units", []):          # deps are the unavoidable edge source
            for d in u.get("deps", []):
                edges.append((d, u["id"]))
        cyc = find_cycle(edges)
        if cyc:
            rep.fail("I3 DAG acyclic (graph.json authoritative)", "cycle: " + " → ".join(cyc))
        else:
            rep.ok(f"I3 DAG acyclic (graph.json authoritative, {len(edges)} edges)")

        # I1b maker!=checker (persona distinctness) — prime directive #3 / Alloy
        # DistinctMakerChecker: a unit's executor and verifier personas MUST differ.
        # (Labeled I1b, the structural sibling of I1 verifier-independence; every I1..I13
        # integer is already taken, so a sub-label avoids a numbering collision.)
        for u in graph_doc.get("units", []):
            if u.get("executor_persona") == u.get("verifier_persona"):
                rep.fail("I1b maker!=checker (persona distinctness)",
                         f"{u.get('id')} has executor_persona == verifier_persona "
                         f"({u.get('executor_persona')!r}) — maker and checker must be distinct")
            else:
                rep.ok(f"I1b maker!=checker (persona distinctness) (units/{u.get('id')})")
    if graph_md_exists:  # defense-in-depth on the prose graph
        with open(graph_md, encoding="utf-8") as f:
            md_text = f.read()
        cyc = find_cycle(parse_graph_edges(md_text))
        if cyc:
            rep.fail("I3 DAG acyclic (GRAPH.md fenced)", "cycle: " + " → ".join(cyc))
        elif graph_doc is None and md_has_unfenced_deps(md_text):
            rep.fail("I3 DAG fail-closed (E)",
                     "GRAPH.md declares dependencies OUTSIDE a code fence and no graph.json "
                     "backs them — 0 edges parsed; refusing to pass")
    if not graph_md_exists and graph_doc is None and not post_decomposition and not args.quiet:
        print("  SKIP  I3 DAG: no GRAPH.md or graph.json present (pre-decomposition)")

    # I4 loop bound + cross-check
    if fsm and isinstance(fsm.get("loop"), dict):
        loop = fsm["loop"]
        retries, luid = loop.get("retries"), loop.get("unit_id")
        if isinstance(retries, int) and retries > 2:
            rep.fail("I4 loop bound", f"fsm loop.retries={retries} > 2")
        elif isinstance(retries, int):
            rep.ok(f"I4 loop bound (retries={retries} <= 2)")
        vd = unit_docs.get(luid, {}).get("verify")
        if vd and isinstance(retries, int) and isinstance(vd.get("iteration"), int):
            if vd["iteration"] > retries + 1:
                rep.fail("I4 loop cross-check",
                         f"{luid} verify.iteration={vd['iteration']} > retries+1={retries+1}")
            else:
                rep.ok(f"I4 loop cross-check ({luid}: iteration<=retries+1)")

    # I4 iteration ceiling (universal) - the per-unit cross-check above only covers the unit
    # named in fsm.loop.unit_id; every OTHER unit's verify.iteration is still bounded by the
    # absolute ceiling retries.maximum(2)+1 = 3 (I4: iteration<=retries+1, retries<=2).
    for _uid, _d in unit_docs.items():
        _v = _d.get("verify")
        if _v is not None and isinstance(_v.get("iteration"), int) and _v["iteration"] > 3:
            rep.fail(f"I4 iteration ceiling (units/{_uid})",
                     f"verify.iteration={_v['iteration']} > 3 (retries<=2 => iteration<=retries+1<=3)")

    # I1 verifier independence (shape). Defense-in-depth (D28): verify.schema pins
    # executor_reasoning_seen to const:false, so a violating doc is already schema-INVALID and
    # never lands in unit_docs — this FAIL branch is effectively unreachable but kept explicit.
    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v is not None:
            if v.get("executor_reasoning_seen") is False:
                rep.ok(f"I1 verifier independence attested (units/{uid})")
            else:
                rep.fail(f"I1 verifier independence (units/{uid})",
                         "executor_reasoning_seen must be false")

    # I6 evidence-bound FAIL — each defect.criterion must be drawn from brief.acceptance_criteria
    for uid, d in unit_docs.items():
        v, b = d.get("verify"), d.get("brief")
        if v and v.get("verdict") == "FAIL" and b:
            crit = set(b.get("acceptance_criteria", []))
            bad = [df.get("criterion") for df in v.get("defects", [])
                   if df.get("criterion") not in crit]
            if bad:
                rep.fail(f"I6 FAIL defect criterion (units/{uid})",
                         f"defect criteria {bad} not in brief.acceptance_criteria")
            else:
                rep.ok(f"I6 FAIL defect criteria drawn from brief (units/{uid})")

    # I13 socratic counter records an OUTCOME (debrief + verify)
    def check_counter(label, soc):
        if not isinstance(soc, dict):
            return
        c = (soc.get("counter") or "").strip()
        # D20: blank/placeholder counters record no OUTCOME (I13) and are rejected. The mechanical
        # sentinel is a full sentence, so it is never a member of BLANK_COUNTER and is accepted here
        # without an explicit exclusion (the old `!= MECH_SENTINEL` clause was always true — dead).
        if c.lower() in BLANK_COUNTER:
            rep.fail(f"I13 socratic counter ({label})",
                     f"counter {c!r} records no OUTCOME (blank/'n/a'); "
                     f"mechanical sentinel = {MECH_SENTINEL!r}")
        else:
            rep.ok(f"I13 socratic counter records an outcome ({label})")
    for uid, d in unit_docs.items():
        if d.get("debrief"):
            check_counter(f"units/{uid}/debrief", d["debrief"].get("socratic"))
        if d.get("verify"):
            check_counter(f"units/{uid}/verify", d["verify"].get("socratic"))

    # premise-check attestation (the independent COUNTER re-run)
    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v is None:
            continue
        pc = v.get("premise_check", {})
        if pc.get("counter_reran_independently") is not True:
            rep.fail(f"premise re-run (units/{uid})",
                     "premise_check.counter_reran_independently must be true "
                     "(decoupled COUNTER re-run not attested)")
        elif pc.get("is_load_bearing") is False and v.get("verdict") == "PASS":
            rep.fail(f"premise deflection (units/{uid})",
                     "verifier attests executor premise is NOT load-bearing yet verdict=PASS")
        else:
            rep.ok(f"premise-check attested (units/{uid})")

    # I9 MISSING VERIFICATION (MUST-FIX D) — a debrief without a verify is REJECTED
    for uid in sorted(unit_dirs_with_debrief):
        vpath = os.path.join(units_dir, uid, "verify.json")
        if not os.path.exists(vpath):
            rep.fail(f"I9 missing verification (units/{uid})",
                     "unit has a debrief but NO verify.json — unverified unit rejected")
        else:
            vd = unit_docs.get(uid, {}).get("verify")
            if vd is None:
                rep.fail(f"I9 missing verification (units/{uid})",
                         "verify.json present but INVALID — no usable verdict")
            elif "verdict" not in vd:
                rep.fail(f"I9 missing verification (units/{uid})", "verify.json has no verdict")
            else:
                rep.ok(f"I9 verification present (units/{uid}: verdict={vd['verdict']})")

    # I10 synthesis/DONE completeness — no unit may reach P8/DONE without a PASS
    if phase in ("P8_SYNTHESIS", "DONE"):
        for uid in sorted(unit_dirs_with_debrief):
            vd = unit_docs.get(uid, {}).get("verify")
            if not vd or vd.get("verdict") != "PASS":
                got = (vd or {}).get("verdict", "MISSING")
                rep.fail("I10 synthesis completeness",
                         f"phase {phase} but units/{uid} verdict={got} (need PASS)")
        if unit_dirs_with_debrief:
            rep.ok(f"I10 synthesis completeness checked at phase {phase}")

    # I11 tag vocabulary — every unit/brief tag must be a member of V_tag (graph.v_tag)
    # I12 learnings propagation predicate + admission gate
    if graph_doc is not None:
        v_tag = set(graph_doc.get("v_tag", []))
        gunits = graph_doc.get("units", [])
        unit_tags = {u.get("id"): set(u.get("tags", [])) for u in gunits}
        tag_ok = True
        for u in gunits:
            bad = sorted(t for t in u.get("tags", []) if t not in v_tag)
            if bad:
                tag_ok = False
                rep.fail("I11 tag vocabulary (graph)", f"{u.get('id')} tags {bad} not in V_tag {sorted(v_tag)}")
        for uid, d in unit_docs.items():
            b = d.get("brief")
            if b:
                bad = sorted(t for t in b.get("tags", []) if t not in v_tag)
                if bad:
                    tag_ok = False
                    rep.fail(f"I11 tag vocabulary (units/{uid}/brief)", f"tags {bad} not in V_tag {sorted(v_tag)}")
        if tag_ok:
            rep.ok(f"I11 tag vocabulary (all tags drawn from V_tag, |V_tag|={len(v_tag)})")

        if learnings:
            def units_with_tag(T):
                return sorted(uid for uid, ts in unit_tags.items() if T in ts)
            prop_ok = True
            for E in learnings:
                if not isinstance(E, dict):
                    continue
                eid = E.get("id")
                since = E.get("since_wave", 1)
                # D01 crash-guard: `since` MUST be an int before the `wave >= since` comparison
                # below (a bad value would raise TypeError). Load-time schema validation already
                # drops malformed entries; this is belt-and-suspenders so no value can crash us.
                if isinstance(since, bool) or not isinstance(since, int):
                    prop_ok = False
                    rep.fail("I12 learnings since_wave",
                             f"{eid} since_wave={since!r} is not an integer >= 1 — "
                             "cannot evaluate propagation")
                    continue
                for sel in (E.get("scope", {}) or {}).get("applies_to", []):
                    if not (isinstance(sel, str) and sel.startswith("tag:")):
                        continue
                    T = sel[4:]
                    carriers = units_with_tag(T)
                    if len(carriers) < 2:               # admission gate
                        prop_ok = False
                        rep.fail("I12 learnings admission gate",
                                 f"{eid} scope tag:{T} inadmissible — only {len(carriers)} unit(s) carry it {carriers} (need >=2)")
                    for uid, d in unit_docs.items():    # propagation predicate
                        b = d.get("brief")
                        if not b:
                            continue
                        w = b.get("wave", 0)
                        if isinstance(w, bool) or not isinstance(w, int):
                            continue                     # non-int wave: skip (schema requires int)
                        if T in set(b.get("tags", [])) and w >= since \
                           and eid not in b.get("learnings_applied", []):
                            prop_ok = False
                            rep.fail("I12 learnings propagation",
                                     f"units/{uid} carries tag:{T} at wave {w} "
                                     f">= since_wave {since}: MUST list {eid} in learnings_applied "
                                     f"(has {b.get('learnings_applied')})")
            if prop_ok:
                rep.ok(f"I12 learnings propagation ({len(learnings)} entr(y/ies): admission + tag-scope propagation hold)")
        elif not args.quiet:
            print("  SKIP  I12 learnings propagation: no learnings.json present")

    # I7 disagreement: exactly one recommended option
    for uid, d in unit_docs.items():
        dis = d.get("disagreement")
        if dis is not None:
            n = sum(1 for o in dis.get("options", []) if o.get("recommended") is True)
            if n == 1:
                rep.ok(f"I7 single recommended option (units/{uid})")
            else:
                rep.fail(f"I7 single recommended option (units/{uid})",
                         f"{n} options marked recommended (need exactly 1)")

    # I8 no OPEN material ambiguity
    cl = docs.get("clarifications")
    if cl:
        open_material = [r for r in cl.get("ambiguity_register", [])
                         if r.get("materiality") == "material" and not r.get("resolved", False)]
        if open_material:
            rep.fail("I8 open material ambiguity",
                     f"{len(open_material)} unresolved material item(s): "
                     + ", ".join(str(r.get('id')) for r in open_material))
        else:
            rep.ok("I8 no open material ambiguity")

    # I-dod Definition-of-Done / Non-Goals presence gate (ADDITIVE; DECISIONS U-signal/U-layer).
    # Second, complementary layer to the schema's required+non-empty definition_of_done/non_goals:
    # ARTIFACT-DRIVEN — once a run has produced ANY STRUCTURAL artifact BEYOND clarification
    # (cartography.json/CARTOGRAPHY.md, graph.json/GRAPH.md, any units/<Uxx>/ subdir, or SYNTHESIS.md),
    # a clarifications.json carrying a NON-EMPTY Definition of Done AND Non-Goals MUST exist.
    # This is the STRUCTURAL subset of the G-personas post_p1 union: it deliberately EXCLUDES the
    # learnings.json ledger sidecar (bookkeeping, not work-graph structure — a learnings.json can be a
    # run's sole extra artifact, e.g. an edge/test scenario, where requiring a DoD would be wrong; and
    # in a real pipeline learnings.json is only emitted mid-Phase-6, by which point the structural
    # artifacts already trigger this gate, so excluding it costs no reachable coverage).
    # Trigger is the UNION, not cartography alone (A8): keying only on cartography let a run delete
    # cartography while keeping the graph/units and thereby skip the DoD gate — closed here.
    # Artifact existence is tamper-resistant where the raw phase string is evadable (DECISIONS
    # U-signal); the schema layer already rejects a present-but-malformed file, so `cl` is None here
    # iff the file is absent OR schema-invalid (e.g. omitting the two fields). Presence +
    # non-emptiness ONLY — no NLP (G2). This is purely additive: no existing check is weakened.
    require_dod = (
        docs.get("cartography") is not None
        or os.path.exists(os.path.join(rd, "CARTOGRAPHY.md"))
        or graph_json_exists
        or graph_md_exists
        or bool(unit_subdirs)
        or os.path.exists(os.path.join(rd, "SYNTHESIS.md"))
    )
    if require_dod:
        def _nonempty_strlist(v):
            return isinstance(v, list) and any(isinstance(x, str) and x.strip() for x in v)
        if cl is None:
            rep.fail("I-dod DoD/non-goals present",
                     "a post-clarification artifact (cartography / graph / units / synthesis) is "
                     "present (Phase 3+) but no VALID clarifications.json carrying a non-empty "
                     "definition_of_done + non_goals (file absent or schema-invalid) — Definition "
                     "of Done and Non-Goals are required clarification outputs once any structure "
                     "beyond clarification exists")
        else:
            missing = [k for k in ("definition_of_done", "non_goals")
                       if not _nonempty_strlist(cl.get(k))]
            if missing:
                rep.fail("I-dod DoD/non-goals present",
                         f"clarifications.json lacks non-empty {missing} — Definition of Done and "
                         "Non-Goals are required once any post-clarification artifact "
                         "(cartography / graph / units / synthesis) exists")
            else:
                rep.ok("I-dod DoD/non-goals present (non-empty definition_of_done + non_goals)")

    # G-personas fail-closed (state-machine.md T2) — ARTIFACT-DRIVEN so the human persona
    # gate cannot be evaded by under-reporting `phase` or omitting/invalidating fsm-state.json.
    # Personas (Phase 1) precede EVERY other artifact, so any post-Phase-1 signal — a
    # clarifications/cartography extract, a decomposition graph, or any per-unit
    # brief/debrief/verify — means the persona gate MUST already have happened: a VALID
    # personas.json AND gates.personas_confirmed == true (gates are only readable from a
    # schema-valid fsm-state.json, so omitting/breaking it cannot make the flag "true").
    # Detect by EXISTENCE, uniformly across every artifact family — the .md primary OR its
    # .json extract, for each phase after Phase 1. (Bootstrap-seeded files — INPUT/PLAN/
    # DECISIONS/PROGRESS/LEARNINGS.md/fsm-state.json — are NOT signals; PERSONAS.md/
    # personas.json ARE the gate itself, not a signal.)
    # NOTE (D29): personas.json.confirmed_by_user is an OPTIONAL corroborating field and is NOT
    # read as the gate here — the gate keys off fsm-state.gates.personas_confirmed (the only
    # tamper-evident, schema-gated signal). confirmed_by_user is documentation, not enforcement.
    def _exists(*names):
        return any(os.path.exists(os.path.join(rd, n)) for n in names)
    post_p1 = []
    if docs.get("clarifications") is not None or _exists("CLARIFICATIONS.md"): post_p1.append("clarifications")
    if docs.get("cartography")   is not None or _exists("CARTOGRAPHY.md"):    post_p1.append("cartography")
    if graph_md_exists or graph_json_exists:                                 post_p1.append("graph")
    if unit_docs or unit_dirs_with_debrief or unit_dirs_with_work:           post_p1.append("units")
    if _exists("SYNTHESIS.md"):                                              post_p1.append("synthesis")
    if _exists("learnings.json"):                                            post_p1.append("learnings")
    if post_p1:
        missing = []
        if docs.get("personas") is None:
            missing.append("no VALID personas.json")
        if gates.get("personas_confirmed") is not True:
            missing.append("gates.personas_confirmed != true (needs a valid fsm-state.json)")
        if missing:
            rep.fail("G-personas non-skippable",
                     f"run shows post-Phase-1 work {post_p1} but {'; '.join(missing)} — the human "
                     "persona-selection gate (Phase 1) cannot be skipped; it precedes all these "
                     "artifacts (T2)")
        else:
            rep.ok("G-personas non-skippable (post-Phase-1 work present; roster confirmed + personas.json valid)")
    elif fsm and gates.get("personas_confirmed") and docs.get("personas") is None:
        # Flag set true with no roster and no downstream work yet — still a fail-closed tie.
        rep.fail("G-personas fail-closed",
                 "gates.personas_confirmed=true but no VALID personas.json (T2)")

    # Gate ordering: phase requires prior gates true. personas_confirmed is the FIRST
    # gate (Phase 1) and is required from P2 onward — the human persona gate is not skippable.
    REQUIRED_GATES = {
        "P2_CLARIFICATION": ["personas_confirmed"],
        "P3_CARTOGRAPHY": ["personas_confirmed", "clarification_resolved"],
        "P4_DECOMPOSITION": ["personas_confirmed", "clarification_resolved", "cartography_done"],
        "P5_BRIEFING": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P6_EXECUTE_VERIFY": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P7_DISAGREEMENT_GATE": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P8_SYNTHESIS": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "DONE": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
    }
    if fsm:
        gates = fsm.get("gates", {})
        need = REQUIRED_GATES.get(phase, [])
        missing = [g for g in need if not gates.get(g, False)]
        if missing:
            rep.fail("gate ordering", f"phase {phase} requires gates {missing} = true")
        elif need:
            rep.ok(f"gate ordering (phase {phase}: prior gates satisfied)")

    return _finish(rep)

def _finish(rep):
    print(f"\n== summary ==  checks passed: {len(rep.checked)}  ·  problems: {len(rep.problems)}")
    if rep.problems:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
