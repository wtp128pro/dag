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
import json, os, re, sys, argparse, datetime, fnmatch

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

def _model_scope_applies(entry_scope_model, run_model):
    """G4 (04-global) scope.model NARROWING conjunct for I12 propagation.
    A learning WITHOUT `scope.model` matches ALL models (unchanged behavior). With `scope.model`
    set it applies to a run only if the run's model (fsm-state.model) MATCHES — glob (fnmatch, so
    'claude-opus-*') OR prefix ('claude-opus'). If the run's model is ABSENT, a scope.model-bearing
    entry does NOT apply (fail closed on the narrowing side). This can only NARROW propagation,
    never broaden it: dropping the conjunct (model absent from the entry) yields today's behavior."""
    if not isinstance(entry_scope_model, str) or not entry_scope_model.strip():
        return True                                   # model-agnostic entry: matches every model
    if not isinstance(run_model, str) or not run_model.strip():
        return False                                  # scope.model set but run model unrecorded: fail closed
    pat, rm = entry_scope_model.strip(), run_model.strip()
    return fnmatch.fnmatch(rm, pat) or rm.startswith(pat)

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

    # ---- across-run PROJECT learnings store (03/P1, P3 expiry, P5 contradiction) ----
    # ADDITIVE + POST-HOC + OFFLINE: load persisted lessons from a project `.dag/learnings/`
    # store and merge them into the SAME `learnings` propagation set the I12 predicate below
    # consumes — this is load-time data-shaping, not an FSM gate (no live back-edge; mirrors
    # the L2 "post-hoc, not a live LT7 guard" requirement structurally). ABSENT STORE => ZERO
    # behavior change: the discovery loop finds no files, so `learnings` is exactly what the
    # run-local loader produced and every existing fixture is byte-for-byte identical.
    # Malformed store data is REPORTED (rep.fail) and DROPPED — it can never crash the run,
    # mirroring the run-local loader tolerance directly above (L398-423).
    _lschema = schemas.get("learnings.schema.json")
    _store_entry_schema = (_lschema.get("$defs", {}) or {}).get("entry") if isinstance(_lschema, dict) else None

    def _applies_frozenset(E):
        sc = E.get("scope") if isinstance(E.get("scope"), dict) else {}
        ats = sc.get("applies_to")
        return frozenset(a for a in ats if isinstance(a, str)) if isinstance(ats, list) else frozenset()

    # Discovery mirrors the persona precedent (project .dag/<kind>/*.json). Candidate roots,
    # dedup'd by realpath: the run dir itself (where fixtures + a staged demo place the store),
    # the run's parent (`<run_dir>/../.dag/learnings/`), and the project root two levels up
    # (`<run_dir>/../../.dag/learnings/`) if resolvable. Each file is ONE entry object OR
    # `{entries:[...]}` OR a bare `[...]` array — reusing the run-local loader's tolerance.
    store_dirs, _seen_real = [], set()
    for _cand in (os.path.join(rd, ".dag", "learnings"),
                  os.path.join(rd, "..", ".dag", "learnings"),
                  os.path.join(rd, "..", "..", ".dag", "learnings")):
        if os.path.isdir(_cand):
            _rp = os.path.realpath(_cand)
            if _rp not in _seen_real:
                _seen_real.add(_rp)
                store_dirs.append(_cand)
    store_ids = set()
    have_ids = {E.get("id") for E in learnings if isinstance(E, dict)}
    if store_dirs:
        merged = 0
        for sd in store_dirs:
            for fn in sorted(f for f in os.listdir(sd) if f.endswith(".json")):
                fp = os.path.join(sd, fn)
                rel = os.path.relpath(fp, rd)
                try:
                    raw = load_json(fp)
                except Exception as e:
                    rep.fail(f"learnings-store {rel}", f"not valid JSON: {e}")
                    continue
                if isinstance(raw, dict):
                    file_entries = raw["entries"] if "entries" in raw else [raw]
                elif isinstance(raw, list):
                    file_entries = raw
                else:
                    rep.fail(f"learnings-store {rel}", "expected an entry object, {entries:[...]}, or [entries]")
                    continue
                if not isinstance(file_entries, list):
                    rep.fail(f"learnings-store {rel}", "'entries' must be an array")
                    continue
                for j, E in enumerate(file_entries):
                    if _store_entry_schema is not None:
                        errs = validate(E, _store_entry_schema)
                        if errs:
                            for e in errs:
                                rep.fail(f"learnings-store {rel}[{j}]", e)
                            continue  # DROP malformed store entry — never reaches I12
                    elif not isinstance(E, dict):
                        rep.fail(f"learnings-store {rel}[{j}]", "entry is not an object")
                        continue
                    eid = E.get("id")
                    if eid in have_ids:
                        # id already present (run-local re-derivation, or an earlier store file)
                        # wins — do NOT force a duplicate into the propagation set.
                        continue
                    have_ids.add(eid)
                    store_ids.add(eid)
                    learnings.append(E)
                    merged += 1
        rep.ok(f"learnings-store discovered ({merged} project entr(y/ies) merged from {len(store_dirs)} store dir(s))")

    # ---- G2 (04-global): user-global learnings store `~/.claude/dag/learnings/*.json` ----
    # ADDITIVE + POST-HOC + OFFLINE, mirroring persona discovery (project overrides user). The
    # project/run-local set loaded above is the HIGH-precedence tier; the user store is a LOWER
    # tier. Override order is **project > user**: on an id collision OR a scope collision (an
    # identical `scope.applies_to` selector set) the project/run-local entry WINS — the shadowed
    # user entry is DROPPED from propagation and the override is REPORTED (never silent). Absent
    # dir => ZERO behavior change (nothing to read). Same tolerant loader (one entry object,
    # {entries:[...]}, or a bare [...] array); malformed data is REPORTED (rep.fail) and DROPPED.
    # User-store ids join `store_ids` so they are treated as imported/already-generalized by the
    # G1 admission carve-out and by the G5 `from_store` decay test — they are across-run entries.
    user_dir = os.path.expanduser(os.path.join("~", ".claude", "dag", "learnings"))
    if os.path.isdir(user_dir):
        # HIGH-tier snapshot (run-local ∪ project) for scope-collision override detection.
        high_scopes = {s for s in (_applies_frozenset(E) for E in learnings if isinstance(E, dict)) if s}
        u_merged = u_over = 0
        for fn in sorted(f for f in os.listdir(user_dir) if f.endswith(".json")):
            fp = os.path.join(user_dir, fn)
            rel = os.path.join("~", ".claude", "dag", "learnings", fn)
            try:
                raw = load_json(fp)
            except Exception as e:
                rep.fail(f"learnings-user-store {rel}", f"not valid JSON: {e}")
                continue
            if isinstance(raw, dict):
                file_entries = raw["entries"] if "entries" in raw else [raw]
            elif isinstance(raw, list):
                file_entries = raw
            else:
                rep.fail(f"learnings-user-store {rel}", "expected an entry object, {entries:[...]}, or [entries]")
                continue
            if not isinstance(file_entries, list):
                rep.fail(f"learnings-user-store {rel}", "'entries' must be an array")
                continue
            for j, E in enumerate(file_entries):
                if _store_entry_schema is not None:
                    errs = validate(E, _store_entry_schema)
                    if errs:
                        for e in errs:
                            rep.fail(f"learnings-user-store {rel}[{j}]", e)
                        continue                       # DROP malformed user-store entry — never reaches I12
                elif not isinstance(E, dict):
                    rep.fail(f"learnings-user-store {rel}[{j}]", "entry is not an object")
                    continue
                eid = E.get("id")
                escope = _applies_frozenset(E)
                if eid in have_ids:                    # id collision => project/run-local wins
                    rep.ok(f"learnings user-store override (G2): user entry {eid} shadowed by a "
                           f"higher-precedence entry of the same id — dropped from propagation (project > user)")
                    u_over += 1
                    continue
                if escope and escope in high_scopes:   # scope collision => project/run-local wins
                    rep.ok(f"learnings user-store override (G2): user entry {eid} shadowed on scope "
                           f"{sorted(escope)} by a higher-precedence entry — dropped from propagation (project > user)")
                    u_over += 1
                    continue
                have_ids.add(eid)
                store_ids.add(eid)
                learnings.append(E)
                u_merged += 1
        rep.ok(f"learnings user-store discovered (~/.claude/dag/learnings/): {u_merged} user entr(y/ies) "
               f"merged, {u_over} overridden by project/run-local (project > user)")

    # --- P3 expiry grammar (LOADER-side, per Cartography R4 — NOT a schema enum) ---
    # Parse the bare `scope.expiry` string grammar `run | project | runs:N | date:<iso>` plus
    # the optional decay fields. An EXPIRED entry is EXCLUDED from propagation and REPORTED as
    # a skip — it is NEVER a hard-fail (an expired lesson simply reverts to today's
    # re-derive-from-scratch behavior, the safe failure mode). Absent/unrecognized expiry is
    # INERT (today's behavior), so existing entries (which carry no expiry) are untouched.
    def _expiry_expired(E, from_store):
        sc = E.get("scope") if isinstance(E.get("scope"), dict) else {}
        exp = sc.get("expiry")
        if not isinstance(exp, str) or not exp.strip():
            return (False, None)
        exp = exp.strip()
        if exp == "project":
            return (False, None)                      # persists indefinitely within the project
        if exp == "run":
            # run-scoped: valid only within its ORIGINATING run. A store entry's run is over =>
            # expired. A run-local `run`-scoped entry is the current run => still valid.
            if from_store:
                return (True, "expiry 'run' loaded from the across-run store (its originating run has ended)")
            return (False, None)
        if exp.startswith("runs:"):
            n = exp[5:].strip()
            if n.isdigit():
                N = int(n)
                ac = E.get("applied_count")
                if isinstance(ac, int) and not isinstance(ac, bool) and ac >= N:
                    return (True, f"expiry 'runs:{N}' exhausted (applied_count={ac} >= {N})")
            return (False, None)                      # unparsed N or no decay yet: inert
        if exp.startswith("date:"):
            ds = exp[5:].strip()
            try:
                d = datetime.date.fromisoformat(ds)
            except Exception:
                return (False, None)                  # unparseable date: inert, never a hard-fail
            if datetime.date.today() > d:
                return (True, f"expiry 'date:{ds}' is in the past")
            return (False, None)
        return (False, None)                          # unrecognized grammar: inert

    # --- G5 (04-global) decay / GC — idle-budget exclusion, coordinated WITH the P3 expiry loop ---
    # Honors the decay fields (`max_idle_runs`, `last_applied_run`, `last_confirmed`, `applied_count`).
    # ARCHIVE-not-DELETE: the validator only READS and EXCLUDES a decayed entry from propagation; it
    # NEVER mutates or removes the source file. Complements (does not duplicate) U03's P3 `runs:N`
    # positive budget (which consumes `applied_count`); G5 is the *idle* budget. It runs in the SAME
    # `_kept` pass below so the two GC rules share one traversal.
    current_run_label = os.path.basename(os.path.normpath(rd)) or None
    applied_ids_this_run = set()
    for _d in unit_docs.values():
        _b = _d.get("brief")
        if _b:
            for _x in (_b.get("learnings_applied", []) or []):
                if isinstance(_x, str):
                    applied_ids_this_run.add(_x)
    def _idle_decayed(E, from_store):
        mir = E.get("max_idle_runs")
        if isinstance(mir, bool) or not isinstance(mir, int) or mir < 0:
            return (False, None)                      # no idle budget declared: inert (today's behavior)
        eid = E.get("id")
        # Applied or confirmed IN THIS run resets the idle span (entry is within budget).
        if eid in applied_ids_this_run:
            return (False, None)
        lar, lco = E.get("last_applied_run"), E.get("last_confirmed")
        if isinstance(lar, str) and current_run_label and lar == current_run_label:
            return (False, None)
        if isinstance(lco, str) and current_run_label and lco == current_run_label:
            return (False, None)
        # DECIDABLE from a single run's view: a ZERO-tolerance idle budget on an across-run
        # (store-loaded) entry that was neither applied nor confirmed this run has, by definition,
        # spent its idle budget => decay candidate (excluded + reported; source file untouched).
        if from_store and mir == 0:
            return (True, "max_idle_runs=0 idle budget exhausted (not applied/confirmed this run)")
        # max_idle_runs >= 1 needs a cross-run idle COUNTER the single-run validator cannot derive;
        # left INERT (fail-safe: kept) — a real run-harness that tracks idle spans owns that tighten.
        return (False, None)

    _kept = []
    for E in learnings:
        if isinstance(E, dict):
            from_store = E.get("id") in store_ids
            expired, why = _expiry_expired(E, from_store)
            if expired:
                rep.ok(f"learnings expiry (03/P3): {E.get('id')} EXCLUDED from propagation ({why})")
                continue
            decayed, dwhy = _idle_decayed(E, from_store)
            if decayed:
                rep.ok(f"learnings decay/GC (04/G5): {E.get('id')} EXCLUDED from propagation — idle-decay "
                       f"candidate ({dwhy}); ARCHIVE-not-delete (source file left untouched)")
                continue
        _kept.append(E)
    learnings = _kept

    # --- P5 contradiction: supersedes exclusion + genuine-split escalation ---
    # (a) an entry declaring `supersedes:"<id>"` EXCLUDES the superseded entry from
    #     propagation (retained on disk for audit; just not force-injected here).
    superseded_ids = {E["supersedes"] for E in learnings
                      if isinstance(E, dict) and isinstance(E.get("supersedes"), str) and E["supersedes"].strip()}
    if superseded_ids:
        _kept = []
        for E in learnings:
            if isinstance(E, dict) and E.get("id") in superseded_ids:
                rep.ok(f"learnings contradiction (03/P5): {E.get('id')} superseded — excluded from propagation")
                continue
            _kept.append(E)
        learnings = _kept
    # (b) two-or-more LIVE entries sharing an IDENTICAL scope.applies_to selector set with
    #     DIFFERENT lessons and NO supersedes ordering are competing for the same scope — I12
    #     would force-inject all of them into the same brief. Whether that is a genuine
    #     CONTRADICTION or merely complementary cannot be decided here without NLP (G2 forbids
    #     it), so we do NOT auto-pick and do NOT silently drop a valid lesson. Instead we SURFACE
    #     it as an explicit escalate-style NOTE (non-failing, like the SKIP lines) so a human
    #     resolves it — AO-5 "genuine split => human, not loop": the resolution is to add
    #     `supersedes` (path (a)) or narrow `scope.excludes` so the scopes stop overlapping. This
    #     is deliberately a NOTE, not a rep.fail: a hard-fail on this heuristic would break every
    #     legitimate multi-lesson store (e.g. two unrelated `tag:core` lessons), a false positive.
    def _applies_set(E):
        sc = E.get("scope") if isinstance(E.get("scope"), dict) else {}
        ats = sc.get("applies_to")
        return frozenset(a for a in ats if isinstance(a, str)) if isinstance(ats, list) else frozenset()
    _by_scope = {}
    for E in learnings:
        if isinstance(E, dict):
            s = _applies_set(E)
            if s:
                _by_scope.setdefault(s, []).append(E)
    for s, grp in sorted(_by_scope.items(), key=lambda kv: sorted(kv[0])):
        if len(grp) >= 2 and len({e.get("lesson") for e in grp}) >= 2:
            ids = sorted(str(e.get("id")) for e in grp)
            print(f"  NOTE  contradiction (03/P5): {len(grp)} live entries {ids} compete for scope "
                  f"{sorted(s)} with no supersedes ordering — NOT auto-picked; if they conflict, a "
                  f"human resolves it (AO-5) by adding `supersedes` or narrowing `scope.excludes`")

    # ---- G3 (04-global): principles-promotion ADVISORY hook (post-hoc, NON-gating) ----
    # Surface `promotable` entries (schema field) — especially global/imported, already-generalized
    # ones — as candidates for HUMAN promotion to a user-local principles file
    # (`~/.claude/dag/principles.md`). This is an ADVISORY report line ONLY: it is NOT an auto-write
    # and NOT a hard gate — promotion stays a human decision. Post-hoc, on the finalized (post
    # expiry/decay/supersede) propagation set; it never gates the FSM and never fails the run
    # (a NOTE, like the P5(b) contradiction line above), so it cannot deadlock the loop (L2).
    for E in learnings:
        if isinstance(E, dict) and E.get("promotable") is True:
            eid = E.get("id")
            src = ("global/imported" if (eid in store_ids or (isinstance(eid, str) and eid.startswith("G")))
                   else "run/project-local")
            print(f"  NOTE  G3 promotion (advisory): {eid} is marked promotable ({src}) — eligible for HUMAN "
                  f"promotion to a user-local principles.md (~/.claude/dag/principles.md); NOT auto-written, NOT gated")

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

    # I14 AO-2 do_not_touch disjointness — on a RETRY (debrief.iteration>1) no defect may name a
    # criterion the PRIOR iteration marked correct/off-limits. The validator retains only the
    # latest verify.json per unit, so the prior-iteration do_not_touch is read from the debrief
    # echo (debrief.prior_feedback.do_not_touch), not per-iteration verify files. POST-HOC/OFFLINE
    # inline check: it reports on an already-produced run and NEVER gates the FSM, so it cannot
    # deadlock LT7 or break termination (the L2 lesson) — the inline for-loop shape IS the
    # guarantee-preservation. Fail CLOSED only when the retry data is actually present.
    for uid, d in unit_docs.items():
        dbf, v = d.get("debrief"), d.get("verify")
        if not dbf or not v:
            continue
        if not (isinstance(dbf.get("iteration"), int) and dbf["iteration"] > 1):
            continue
        pf = dbf.get("prior_feedback") or {}
        dnt = pf.get("do_not_touch")
        if not dnt:                       # retry data absent (iteration 1 or no echo) — skip / no-op
            continue
        crit = {df.get("criterion") for df in v.get("defects", [])}
        overlap = sorted(x for x in (crit & set(dnt)) if x is not None)
        if overlap:
            rep.fail(f"I14 AO-2 do_not_touch disjointness (units/{uid})",
                     f"defect criteria {overlap} intersect prior_feedback.do_not_touch — a retry "
                     "must not re-open what the prior iteration marked correct (AO-2)")
        else:
            rep.ok(f"I14 AO-2 do_not_touch disjointness (units/{uid})")

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

    # I15 AO-6 responsive change — a RETRY (debrief.iteration>1) that records its prior-feedback
    # context MUST also record >=1 concrete change made in response to the prior verdict
    # (debrief.prior_feedback.changes_made present + non-empty); an empty/absent changes_made in a
    # populated prior_feedback echo means the loop re-ran without responding (silent oscillation).
    # Gated on the presence of the prior_feedback echo — mirroring I14's "fail CLOSED only when the
    # retry data is actually present" principle (a run that carries no prior_feedback block has no
    # responsive-change record for this post-hoc check to audit). POST-HOC/OFFLINE inline check: it
    # never gates the FSM, so it cannot deadlock LT7 or break termination — it only reports on a run
    # the loop has already produced.
    for uid, d in unit_docs.items():
        dbf = d.get("debrief")
        if not dbf or not (isinstance(dbf.get("iteration"), int) and dbf["iteration"] > 1):
            continue
        pf = dbf.get("prior_feedback")
        if not isinstance(pf, dict):      # retry recorded no prior_feedback echo — post-hoc no-op
            continue
        changes = pf.get("changes_made")
        if isinstance(changes, list) and any(isinstance(x, str) and x.strip() for x in changes):
            rep.ok(f"I15 AO-6 responsive change (units/{uid})")
        else:
            rep.fail(f"I15 AO-6 responsive change (units/{uid})",
                     "iteration>1 with a prior_feedback echo but changes_made is absent/empty — a "
                     "retry must record >=1 concrete change made in response to the prior verdict (AO-6)")

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

    # I11 tag vocabulary — every unit/brief tag must be a member of V_tag_eff
    # I12 learnings propagation predicate + admission gate
    if graph_doc is not None:
        v_tag = set(graph_doc.get("v_tag", []))

        # ---- G1 FLAG: global tag registry — WIDENS the I11/I12 tag DOMAIN ----
        # (guarantee-domain change; delivered as its own commit — see 04-global.md / CARTOGRAPHY R3.)
        # V_tag_eff = global ∪ project ∪ run_local. Read the global registry `~/.claude/dag/tags.json`
        # (validated against schemas/tags.schema.json) if present; its `tags[]` UNION with the run-local
        # `graph.json.v_tag`. There is NO project tag registry today: U03 added a project *learnings*
        # store (.dag/learnings/), not a project *tag* store — so V_tag_eff = global ∪ run_local here;
        # the union is written so a project tier drops in trivially if one is ever added.
        #   * ABSENT FILE  => global_tags == ∅ => V_tag_eff == v_tag  (today's behavior; ZERO change
        #     when no registry exists — the backward-compat anchor).
        #   * I11 STAYS literally `T ∈ V_tag_eff`: a FINITE enumerated set, decidable set-membership,
        #     NO free-text/NLP (the anti-NLP property is preserved — the domain grows, the test's KIND
        #     does not). I12 propagation stays run-local `T ∈ U.tags`, evaluating False (decidable, not
        #     undefined) when no unit carries T.
        # Malformed/invalid registry is REPORTED (rep.fail) — never a silent widening, never a crash.
        global_tags = set()
        _tagstore = os.path.expanduser(os.path.join("~", ".claude", "dag", "tags.json"))
        if os.path.exists(_tagstore):
            _traw = None
            try:
                _traw = load_json(_tagstore)
            except Exception as e:
                rep.fail("I11 global tag registry (G1)", f"~/.claude/dag/tags.json not valid JSON: {e}")
            if _traw is not None:
                _tschema = schemas.get("tags.schema.json")
                errs = validate(_traw, _tschema) if _tschema is not None else []
                if errs:
                    for e in errs:
                        rep.fail("I11 global tag registry (G1)", f"~/.claude/dag/tags.json: {e}")
                else:
                    global_tags = {t for t in _traw.get("tags", []) if isinstance(t, str)}
                    rep.ok(f"I11 global tag registry (G1) loaded ({len(global_tags)} tag(s) from "
                           f"~/.claude/dag/tags.json — widening V_tag_eff)")
        v_tag_eff = v_tag | global_tags   # V_tag_eff = global ∪ run_local (project tier admits trivially)

        gunits = graph_doc.get("units", [])
        unit_tags = {u.get("id"): set(u.get("tags", [])) for u in gunits}
        tag_ok = True
        for u in gunits:
            bad = sorted(t for t in u.get("tags", []) if t not in v_tag_eff)
            if bad:
                tag_ok = False
                rep.fail("I11 tag vocabulary (graph)", f"{u.get('id')} tags {bad} not in V_tag_eff {sorted(v_tag_eff)}")
        for uid, d in unit_docs.items():
            b = d.get("brief")
            if b:
                bad = sorted(t for t in b.get("tags", []) if t not in v_tag_eff)
                if bad:
                    tag_ok = False
                    rep.fail(f"I11 tag vocabulary (units/{uid}/brief)", f"tags {bad} not in V_tag_eff {sorted(v_tag_eff)}")
        if tag_ok:
            rep.ok(f"I11 tag vocabulary (all tags drawn from V_tag_eff, |V_tag_eff|={len(v_tag_eff)}"
                   f"{f', +{len(global_tags)} global' if global_tags else ''})")

        if learnings:
            def units_with_tag(T):
                return sorted(uid for uid, ts in unit_tags.items() if T in ts)
            # G4 (04-global): the run's model, used by the scope.model NARROWING conjunct below.
            run_model = fsm.get("model") if isinstance(fsm, dict) else None
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
                # G4 (04-global) scope.model NARROWING conjunct: a model-scoped entry that does NOT
                # match this run's model is entirely INAPPLICABLE this run — skip BOTH the admission
                # gate and the propagation predicate for it (it can bind nothing here). This can only
                # NARROW: a model-agnostic entry (no scope.model) is unaffected. Fail closed when the
                # run's model is absent (a scope.model-bearing entry does NOT force-inject). Reported.
                _e_model = (E.get("scope", {}) or {}).get("model")
                if isinstance(_e_model, str) and _e_model.strip() and not _model_scope_applies(_e_model, run_model):
                    rep.ok(f"I12 model narrowing (04/G4): {eid} scope.model={_e_model!r} does not match run "
                           f"model {run_model!r} — EXCLUDED from propagation this run (narrowing conjunct)")
                    continue
                # G1 FLAG: authored-vs-imported admission carve-out (widens I11/I12 domain — see
                # 04-global.md/roadmap §d). The >=2-current-run-carrier admission gate below is a
                # RE-GENERALIZATION test: it rejects a one-off authored THIS run before it can bind
                # later units. An IMPORTED/GLOBAL entry is ALREADY generalized (it survived a prior
                # run's admission and was persisted), so re-imposing the >=2-run re-proof would
                # WRONGLY reject it. An entry is imported/global iff its id was loaded from the
                # project/global store rather than authored in-run (`eid in store_ids`), OR it bears
                # the global-scoped `G#` id marker (learnings.schema: L# = run/project, G# = global).
                # Such entries are EXEMPT from the >=2-run re-proof — but are STILL FULLY governed by
                # the propagation predicate below (force-inject only where the tag actually appears).
                # The exemption is EXPLICIT (reported as a PASS-level carve-out line), NEVER silent.
                _is_imported = (eid in store_ids) or (isinstance(eid, str) and eid.startswith("G"))
                for sel in (E.get("scope", {}) or {}).get("applies_to", []):
                    if not (isinstance(sel, str) and sel.startswith("tag:")):
                        continue
                    T = sel[4:]
                    carriers = units_with_tag(T)
                    if len(carriers) < 2:               # admission gate (>=2 current-run carriers)
                        if _is_imported:
                            # G1 FLAG carve-out: already-generalized imported/global entry — EXEMPT
                            # from the >=2-run re-proof, still propagation-governed (never silent).
                            rep.ok(f"I12 admission carve-out (G1): {eid} scope tag:{T} is imported/global "
                                   f"({'store-loaded' if eid in store_ids else 'G#-id'}) — exempt from the "
                                   f">=2-carrier re-proof ({len(carriers)} current-run carrier(s)); still "
                                   "governed by the propagation predicate")
                        else:
                            prop_ok = False
                            rep.fail("I12 learnings admission gate",
                                     f"{eid} scope tag:{T} inadmissible — only {len(carriers)} unit(s) carry it {carriers} (need >=2)")
                    for uid, d in unit_docs.items():    # propagation predicate (runs for ALL entries, imported or not)
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
