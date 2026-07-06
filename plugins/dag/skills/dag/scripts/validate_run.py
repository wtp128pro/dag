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
    top-level defects[], PASS=>no blocker/major (minor allowed; I6 revised, PR1), FAIL=>>=1 defect each naming a brief criterion,
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
  * PR1 verifier hardening — I6's PASS clause is REVISED (coverage-first): a PASS may carry `minor`
    observations but not a blocker/major defect (schema allOf + a defense-in-depth check here). New
    invariant I16 (panel discipline): a `high-stakes` unit must carry a panel[] of >=3 with the
    distinct correctness/reproduce/guardrail lenses; any panel's top verdict must equal the DISCRETE
    majority (a split routes to DISAGREE — no softmax); verify_rounds (loop-until-dry) is bounded to
    [1,3]. I16 is POST-HOC / OFFLINE and gates NO transition (never a live LT7 guard).

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

# N-15: the JSON-Schema assertion keywords the built-in mini validator IMPLEMENTS. The schema
# self-check WARNs (NOTE) on any keyword a schema relies on that the mini validator would silently
# ignore, and FAILs on an unresolvable $ref it cannot enforce.
_MINI_SUPPORTED_KEYWORDS = frozenset({
    "$ref", "type", "const", "enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "items",
    "properties", "required", "additionalProperties", "allOf", "anyOf", "oneOf", "not",
    "if", "then", "else",
})
# all standard JSON-Schema assertion keywords — lets the audit tell a real keyword from a property
# NAME (only a key in this set is treated as a keyword; unknown-to-the-standard keys are ignored).
_JSONSCHEMA_ASSERTION_KEYWORDS = _MINI_SUPPORTED_KEYWORDS | frozenset({
    "format", "propertyNames", "patternProperties", "dependencies", "dependentRequired",
    "dependentSchemas", "minProperties", "maxProperties", "contains", "minContains", "maxContains",
    "prefixItems", "unevaluatedItems", "unevaluatedProperties", "multipleOf",
})
# keys whose VALUE is a map of subschemas keyed by NAME (descend into values, not the names).
_SUBSCHEMA_MAP_KEYS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
# keys whose VALUE is DATA, not a schema (never descend — avoids treating data as keywords).
_DATA_VALUE_KEYS = frozenset({"enum", "const", "examples", "default", "required"})

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
    if "not" in schema:                                 # N-06: valid iff inst does NOT match the subschema
        if not _mini_validate(inst, schema["not"], path, root):
            errs.append(f"{path}: matched 'not' subschema (must NOT match)")
    if "if" in schema:
        if not _mini_validate(inst, schema["if"], path, root):
            if "then" in schema:
                errs += _mini_validate(inst, schema["then"], path, root)
        elif "else" in schema:
            errs += _mini_validate(inst, schema["else"], path, root)
    return errs

def _audit_schema_self_check(sf, schema, rep):
    """N-15 self-check depth: FAIL on an unresolvable $ref (the mini validator cannot enforce an
    external/broken ref), and NOTE any assertion keyword a schema uses that the mini validator does
    NOT implement — so a future schema keyword cannot silently go unenforced under the stdlib backend."""
    unimpl = set()
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _JSONSCHEMA_ASSERTION_KEYWORDS and k not in _MINI_SUPPORTED_KEYWORDS:
                    unimpl.add(k)
                if k == "$ref" and isinstance(v, str) and _resolve_ref(v, schema) is None:
                    rep.fail(f"schema {sf} $ref",
                             f"unresolvable $ref {v!r} (the built-in mini validator cannot enforce "
                             "an external/broken ref)")
                if k in _SUBSCHEMA_MAP_KEYS and isinstance(v, dict):
                    for sub in v.values():
                        walk(sub)                       # values are subschemas keyed by NAME
                elif k in _DATA_VALUE_KEYS:
                    continue                            # value is DATA, not a subschema
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)
    walk(schema)
    if unimpl:
        print(f"  NOTE  schema {sf}: uses keyword(s) the built-in mini validator does not implement "
              f"(enforced only under the jsonschema backend): {sorted(unimpl)}")

def make_validator():
    try:
        import jsonschema  # type: ignore
        from jsonschema import Draft202012Validator
        def _v(inst, schema):
            try:
                return [f"$.{'/'.join(map(str, e.path))}: {e.message}" if e.path else f"$: {e.message}"
                        for e in sorted(Draft202012Validator(schema).iter_errors(inst),
                                        key=lambda e: [str(p) for p in e.path])]
            except Exception as e:   # IMP-18: a malformed schema raises INSIDE iter_errors (only the
                return [f"schema backend error: {e}"]   # import was guarded) — fail cleanly, not with a traceback
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
    """True if GRAPH.md contains U-id dependency arrows OUTSIDE any code fence.

    N-14: fences toggle only on a line whose *stripped* form starts with three backticks
    (```), so a stray single backtick never flips fence state. Limitation (documented, not a
    bug): this is a single-pass line scanner — it does not understand nested/indented fences,
    tildes (~~~), or inline code spans. That is acceptable because GRAPH.md dependency parsing
    is **defense-in-depth only**: `graph.json` is the AUTHORITATIVE edge set the validator
    enforces (I3), and a post-decomposition run REQUIRES a valid `graph.json`; this heuristic
    just flags an obviously-fenceless GRAPH.md as a secondary signal.
    """
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
    # N-12: iterative explicit-stack DFS (was recursive — a deep dependency chain could
    # RecursionError). This is a faithful simulation of the former recursion: same root order
    # (`list(adj)`), same neighbour order (`adj[n]`), GREY checked before WHITE, so the FIRST
    # cycle found and its returned path (`path[path.index(m):] + [m]`) are byte-identical.
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    for root in list(adj):
        if color[root] != WHITE:
            continue
        color[root] = GREY
        path = [root]                              # == the former recursion's `stack`
        frames = [(root, iter(adj[root]))]         # each frame resumes its neighbour iterator
        while frames:
            node, it = frames[-1]
            descended = False
            for m in it:
                if color[m] == GREY:
                    return path[path.index(m):] + [m]
                if color[m] == WHITE:
                    color[m] = GREY
                    path.append(m)
                    frames.append((m, iter(adj[m])))
                    descended = True
                    break
                # color[m] == BLACK: already fully explored — skip (matches the recursion)
            if not descended:                      # neighbours exhausted → backtrack
                color[node] = BLACK
                path.pop()
                frames.pop()
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

def _as_int(v):
    """Normalize a JSON number to int for an INTEGER-typed artifact field (BRK-04).
    JSON Schema `"type":"integer"` ACCEPTS a float-integral like 1.0 (both backends, per _type_ok),
    so an integer-typed field can legitimately arrive as 1.0 — treat it as the int it denotes rather
    than SKIPPING the check (the wave-as-float evasion). Returns None for a bool or a non-integral
    value (those are schema-rejected shapes the schema layer already FAILed); a caller that wants
    fail-closed semantics on None does so explicitly at its site."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None

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
    # N-13: never crash on a non-UTF-8 stdout/stderr (e.g. `LC_ALL=C PYTHONUTF8=0`). Replace an
    # unencodable char instead of raising UnicodeEncodeError; on a UTF-8 stream the labels survive.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")   # Python >=3.7; exotic streams lack reconfigure
        except Exception:
            pass
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
        _audit_schema_self_check(sf, s, rep)   # N-15: unresolvable $ref => FAIL; unimplemented keyword => NOTE
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
                    # D21: an artifact's declared unit_id MUST match its containing directory. Check
                    # BEFORE recording the ok / inserting into unit_docs (N-10): a mismatched doc must
                    # not both print "valid against ..." AND feed downstream per-unit checks under the
                    # wrong directory key.
                    aid = inst.get("unit_id")
                    if aid is not None and aid != uid:
                        rep.fail(f"units/{uid}/{rel} unit_id mismatch",
                                 f"artifact declares unit_id {aid!r} but lives in directory {uid!r}")
                    else:
                        unit_docs.setdefault(uid, {})[rel.replace(".json", "")] = inst
                        rep.ok(f"units/{uid}/{rel} valid against {sf}")

    # optional machine-readable learnings ledger — schema'd sidecar (D01). Each entry is
    # validated against learnings.schema.json ($defs/entry). A malformed entry is REPORTED
    # (rep.fail) and DROPPED, so it can never reach the I12 `since_wave >=` comparison below
    # (which the crash-guard there also hardens against a TypeError). The loader tolerates both
    # the canonical {entries:[...]} object and a bare top-level array.
    learnings = []
    lp = os.path.join(rd, "learnings.json")
    if os.path.exists(lp):
        raw_entries = []
        top_level_obj = None   # the {entries:[...]} object when that canonical form is used (N-24 shape-check)
        try:
            raw = load_json(lp)
            # BRK-05: mirror the across-run store loader's tolerance EXACTLY (see ~L500 below), instead
            # of the old `raw.get("entries", []) if dict else raw` which silently mapped a bare
            # single-entry OBJECT to [] (dropping the entry + printing a bogus "no learnings.json
            # present" SKIP) while the store loader treated the identical shape as [raw].
            if isinstance(raw, dict):
                if "entries" in raw:
                    raw_entries = raw["entries"]
                    top_level_obj = raw
                elif "id" in raw:
                    raw_entries = [raw]           # bare single-entry object — tolerated, wrapped as [entry]
                    rep.ok("learnings.json non-canonical shape tolerated (bare single-entry object wrapped as [entry])")
                else:
                    rep.fail("learnings.json", "object is neither {entries:[...]} nor a single entry (no 'id')")
                    raw_entries = []
            elif isinstance(raw, list):
                raw_entries = raw                 # bare top-level array — tolerated (documented in learnings.schema)
            else:
                rep.fail("learnings.json", "expected an entry object, {entries:[...]}, or a bare [entries] array")
                raw_entries = []
            if not isinstance(raw_entries, list):
                rep.fail("learnings.json", "'entries' must be an array")
                raw_entries = []
        except Exception as e:
            rep.fail("learnings.json", f"not valid JSON: {e}")
            raw_entries = []
        _ls = schemas.get("learnings.schema.json")
        # N-24: for the canonical {entries:[...]} object form, enforce the TOP-LEVEL shape too — the
        # per-entry loop below validates + drops malformed ENTRIES but never saw the top-level object,
        # so unknown top-level keys passed despite learnings.schema being additionalProperties:false.
        # (A bare top-level array has no object to shape-check; that tolerance is intentional.)
        if top_level_obj is not None:
            for _k in top_level_obj:
                if _k not in ("run_label", "entries"):
                    rep.fail("learnings.json",
                             f"unknown top-level key {_k!r} — learnings.schema allows only "
                             "run_label + entries (additionalProperties:false)")
            if "run_label" in top_level_obj and not isinstance(top_level_obj["run_label"], str):
                rep.fail("learnings.json", "top-level run_label must be a string")
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
    # IMP-07 / Task 2.5: malformed store data is REPORTED as a NON-GATING NOTE and DROPPED — it can
    # never crash NOR FAIL the run. A cross-run store (project `.dag/learnings/`, user
    # `~/.claude/dag/learnings/`) is IMPORTED CONTEXT, not this run's emitted artifact; a stale/corrupt
    # store file must not brick every future run of the project. This matches the two shipped promises —
    # SKILL.md Phase 0.5 "the validator's learnings role never gates a phase transition" and
    # self-learning-loops.md "a malformed entry is REPORTED and DROPPED, never a crash". The dropped
    # entry never reaches I12 either way, so enforcement is unchanged; only the gating is removed.
    # (Run-local learnings.json malformation stays rep.fail above — it IS this run's artifact.)
    _lschema = schemas.get("learnings.schema.json")
    _store_entry_schema = (_lschema.get("$defs", {}) or {}).get("entry") if isinstance(_lschema, dict) else None

    def _store_note(label, detail):
        # Non-gating store-malformation report (IMP-07): prints a NOTE, records NO problem, drops the datum.
        print(f"  NOTE  {label} MALFORMED (dropped, non-gating — imported store context): {detail}")

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
                    _store_note(f"learnings-store {rel}", f"not valid JSON: {e}")
                    continue
                if isinstance(raw, dict):
                    file_entries = raw["entries"] if "entries" in raw else [raw]
                elif isinstance(raw, list):
                    file_entries = raw
                else:
                    _store_note(f"learnings-store {rel}", "expected an entry object, {entries:[...]}, or [entries]")
                    continue
                if not isinstance(file_entries, list):
                    _store_note(f"learnings-store {rel}", "'entries' must be an array")
                    continue
                for j, E in enumerate(file_entries):
                    if _store_entry_schema is not None:
                        errs = validate(E, _store_entry_schema)
                        if errs:
                            for e in errs:
                                _store_note(f"learnings-store {rel}[{j}]", e)
                            continue  # DROP malformed store entry — never reaches I12
                    elif not isinstance(E, dict):
                        _store_note(f"learnings-store {rel}[{j}]", "entry is not an object")
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
    # {entries:[...]}, or a bare [...] array); malformed data is a NON-GATING NOTE (dropped, never a
    # FAIL — imported store context, IMP-07/Task 2.5).
    # User-store ids join `store_ids` so they are treated as imported/already-generalized by the
    # G1 admission carve-out and by the G5 `from_store` decay test — they are across-run entries.
    user_dir = os.path.expanduser(os.path.join("~", ".claude", "dag", "learnings"))
    if os.path.isdir(user_dir):
        # HIGH-tier snapshot (run-local ∪ project) for scope-collision override detection.
        high_scopes = {s for s in (_applies_frozenset(E) for E in learnings if isinstance(E, dict)) if s}
        user_scopes_seen = set()   # N-11: within-user-store scope-collision dedup (first sorted file wins)
        u_merged = u_over = 0
        for fn in sorted(f for f in os.listdir(user_dir) if f.endswith(".json")):
            fp = os.path.join(user_dir, fn)
            rel = os.path.join("~", ".claude", "dag", "learnings", fn)
            try:
                raw = load_json(fp)
            except Exception as e:
                _store_note(f"learnings-user-store {rel}", f"not valid JSON: {e}")
                continue
            if isinstance(raw, dict):
                file_entries = raw["entries"] if "entries" in raw else [raw]
            elif isinstance(raw, list):
                file_entries = raw
            else:
                _store_note(f"learnings-user-store {rel}", "expected an entry object, {entries:[...]}, or [entries]")
                continue
            if not isinstance(file_entries, list):
                _store_note(f"learnings-user-store {rel}", "'entries' must be an array")
                continue
            for j, E in enumerate(file_entries):
                if _store_entry_schema is not None:
                    errs = validate(E, _store_entry_schema)
                    if errs:
                        for e in errs:
                            _store_note(f"learnings-user-store {rel}[{j}]", e)
                        continue                       # DROP malformed user-store entry — never reaches I12
                elif not isinstance(E, dict):
                    _store_note(f"learnings-user-store {rel}[{j}]", "entry is not an object")
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
                if escope and escope in user_scopes_seen:   # N-11: user-vs-user scope collision
                    rep.ok(f"learnings user-store override (G2): user entry {eid} shadowed on scope "
                           f"{sorted(escope)} by an earlier user-store entry (first sorted file wins) — "
                           f"dropped from propagation")
                    u_over += 1
                    continue
                have_ids.add(eid)
                store_ids.add(eid)
                if escope:
                    user_scopes_seen.add(escope)
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
    # N-16: reuse the single `_applies_frozenset` helper defined above (removed the duplicate
    # `_applies_set`, which was byte-identical).
    _by_scope = {}
    for E in learnings:
        if isinstance(E, dict):
            s = _applies_frozenset(E)
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
        retries, luid = _as_int(loop.get("retries")), loop.get("unit_id")   # BRK-04: normalize float-integral
        if retries is not None and retries > 2:
            # N-17: schema `maximum:2` normally rejects retries>2 before this runs, so this FAIL
            # branch is dead when schemas load; it exists for the no-schema degraded mode (mirroring
            # the defense-in-depth comments at I1 / I6-PASS / I16c).
            rep.fail("I4 loop bound", f"fsm loop.retries={retries} > 2")
        elif retries is not None:
            rep.ok(f"I4 loop bound (retries={retries} <= 2)")
        vd = unit_docs.get(luid, {}).get("verify")
        vd_it = _as_int(vd.get("iteration")) if vd else None
        if vd and retries is not None and vd_it is not None:
            if vd_it > retries + 1:
                rep.fail("I4 loop cross-check",
                         f"{luid} verify.iteration={vd_it} > retries+1={retries + 1}")
            else:
                rep.ok(f"I4 loop cross-check ({luid}: iteration<=retries+1)")

    # I4 iteration ceiling (universal) - the per-unit cross-check above only covers the unit
    # named in fsm.loop.unit_id; every OTHER unit's verify.iteration is still bounded by the
    # absolute ceiling retries.maximum(2)+1 = 3 (I4: iteration<=retries+1, retries<=2).
    for _uid, _d in unit_docs.items():
        _v = _d.get("verify")
        _v_it = _as_int(_v.get("iteration")) if _v is not None else None   # BRK-04: normalize float-integral
        if _v_it is not None and _v_it > 3:
            rep.fail(f"I4 iteration ceiling (units/{_uid})",
                     f"verify.iteration={_v_it} > 3 (retries<=2 => iteration<=retries+1<=3)")

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

    # I6 PASS coverage-first (REVISED, PR1) — a PASS MAY carry `minor` observations (report every
    # finding + severity, filter downstream) but MUST NOT carry a blocker/major defect. The schema's
    # allOf already rejects a PASS+blocker/major (so a violating verify.json never reaches unit_docs);
    # this is defense-in-depth — mirroring I1's belt-and-suspenders — that makes the revised invariant
    # visible in the enforcement layer. (Was: PASS => defects==[]; see state-machine.md I6.)
    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v and v.get("verdict") == "PASS":
            blocking = sorted({df.get("severity") for df in v.get("defects", [])
                               if isinstance(df, dict) and df.get("severity") in ("blocker", "major")})
            if blocking:
                rep.fail(f"I6 PASS coverage-first (units/{uid})",
                         f"PASS carries {blocking} defect(s) — a PASS may record only `minor` "
                         "observations (I6 PASS-clause revised for coverage-first, PR1)")
            else:
                rep.ok(f"I6 PASS coverage-first (units/{uid}: minor-only or no defects)")

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
        _dbf_it = _as_int(dbf.get("iteration"))   # BRK-04: normalize float-integral
        if not (_dbf_it is not None and _dbf_it > 1):
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
    # D-07(b): the cartographer/planner produce no debrief.json, so their OPTIONAL socratic
    # residue lives in cartography.json / graph.json (schema-enforced landing place). When present,
    # I13 checks the counter records an OUTCOME there too — same predicate, same offline/post-hoc
    # shape as debrief/verify (absent block => no-op, so every existing run is unaffected).
    if isinstance(docs.get("cartography"), dict) and docs["cartography"].get("socratic") is not None:
        check_counter("cartography", docs["cartography"].get("socratic"))
    if isinstance(docs.get("graph"), dict) and docs["graph"].get("socratic") is not None:
        check_counter("graph", docs["graph"].get("socratic"))

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

    # I16 panel discipline (PR1 verifier hardening) — POST-HOC, OFFLINE, gates NO transition.
    # Three clauses over the emitted verify.json (never a live LT7 guard — the CLAUDE.md deadlock
    # lesson; mirrors I14/I15 which also fail CLOSED but gate nothing):
    #   (a) a unit tagged `high-stakes` (on its graph unit OR its brief) whose verify.json exists MUST
    #       carry a panel[] of >=3 members covering the canonical lens trio {correctness,reproduce,
    #       guardrail} — the panel-of-3-with-distinct-lenses default;
    #   (b) ANY present panel[] MUST have >=3 members, cover the trio, and its top-level `verdict` MUST
    #       equal the DISCRETE majority of the panel verdicts. A split with NO strict majority MUST
    #       route to DISAGREE (AO-5: genuine split => human). This is the anti-softmax guarantee: the
    #       aggregate is a discrete mode, NEVER an averaged/continuous score.
    #   (c) a present verify_rounds (loop-until-dry) MUST be within [1, R_MAX] (finiteness of the
    #       node-internal sweep; the schema also bounds it — defense-in-depth).
    CANON_LENSES = {"correctness", "reproduce", "guardrail"}
    R_MAX = 3
    _graph_unit_tags = {}
    if graph_doc is not None:
        for _u in graph_doc.get("units", []):
            _graph_unit_tags[_u.get("id")] = set(_u.get("tags", []) or [])

    def _discrete_majority(verdicts):
        """Strict discrete majority (mode) of a verdict list, or None on a tie / no-majority.
        DISCRETE by construction — no softmax, no averaging of miscalibrated confidences."""
        if not verdicts:
            return None
        counts = {}
        for x in verdicts:
            counts[x] = counts.get(x, 0) + 1
        top_val, top_n, tie = None, -1, False
        for val, c in counts.items():
            if c > top_n:
                top_val, top_n, tie = val, c, False
            elif c == top_n:
                tie = True
        if tie:
            return None
        return top_val if top_n * 2 > len(verdicts) else None

    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v is None:
            continue
        b = d.get("brief") or {}
        tags = set(b.get("tags", []) or []) | _graph_unit_tags.get(uid, set())
        panel = v.get("panel")
        top = v.get("verdict")
        is_high_stakes = "high-stakes" in tags
        # (a) high-stakes => a panel is REQUIRED
        if is_high_stakes and not isinstance(panel, list):
            rep.fail(f"I16 panel discipline (units/{uid})",
                     "unit is tagged high-stakes but verify.json carries no panel[] — a high-stakes "
                     "unit must be verified by an odd panel (>=3) with distinct lenses (PR1)")
        # (b) any present panel must be well-formed + discrete-majority consistent
        if isinstance(panel, list):
            members = [m for m in panel if isinstance(m, dict)]
            lenses = {m.get("lens") for m in members}
            verdicts = [m.get("verdict") for m in members]
            panel_ok = True
            if len(members) < 3:
                panel_ok = False
                rep.fail(f"I16 panel discipline (units/{uid})",
                         f"panel has {len(members)} member(s) — a panel needs >=3 members (odd recommended so ties are rare)")
            if not CANON_LENSES.issubset(lenses):
                panel_ok = False
                rep.fail(f"I16 panel discipline (units/{uid})",
                         f"panel lenses {sorted(l for l in lenses if l)} do not cover the canonical "
                         f"trio {sorted(CANON_LENSES)} — panel members must have DISTINCT lenses, not clones")
            maj = _discrete_majority(verdicts)
            if maj is None:
                # no strict majority => genuine split => must escalate as DISAGREE (AO-5), never softmax
                if top != "DISAGREE":
                    panel_ok = False
                    rep.fail(f"I16 panel discipline (units/{uid})",
                             f"panel verdicts {verdicts} have no strict majority (genuine split) but "
                             f"top-level verdict={top!r} — a split must route to DISAGREE (AO-5), not a "
                             "softmaxed/averaged score")
            elif top != maj:
                panel_ok = False
                rep.fail(f"I16 panel discipline (units/{uid})",
                         f"top-level verdict={top!r} != DISCRETE panel majority={maj!r} — the aggregate "
                         "must be the discrete majority (no softmax)")
            if panel_ok:
                rep.ok(f"I16 panel discipline (units/{uid}: {len(members)}-member panel, "
                       f"lenses cover trio, verdict={maj if maj else 'split->DISAGREE'})")
        # (c) loop-until-dry finiteness (schema also bounds it; belt-and-suspenders)
        vr = _as_int(v.get("verify_rounds"))   # BRK-04: normalize float-integral
        if vr is not None:
            if vr < 1 or vr > R_MAX:
                rep.fail(f"I16 loop-until-dry bound (units/{uid})",
                         f"verify_rounds={vr} outside [1,{R_MAX}] — the loop-until-dry sweep is bounded")
            else:
                rep.ok(f"I16 loop-until-dry bound (units/{uid}: verify_rounds={vr}<={R_MAX})")

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
        _dbf_it = _as_int(dbf.get("iteration")) if dbf else None   # BRK-04: normalize float-integral
        if not dbf or not (_dbf_it is not None and _dbf_it > 1):
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

    # I9 verify-without-debrief (IMP-17) — the CONVERSE of the missing-verification check above: a
    # unit dir carrying a verify.json but NO debrief is incoherent (a verifier attested to a unit that
    # produced no debrief to verify). Fail closed. Offline/post-hoc.
    for uid in sorted(unit_subdirs):
        udir = os.path.join(units_dir, uid)
        if (os.path.exists(os.path.join(udir, "verify.json")) or os.path.exists(os.path.join(udir, "verify.md"))) \
           and uid not in unit_dirs_with_debrief:
            rep.fail(f"I9 verify-without-debrief (units/{uid})",
                     "verify present but no debrief — a verifier output with nothing verified is incoherent")

    # G-brief offline presence (BRK-03; T8/G-brief offline counterpart). A missing
    # units/<U>/brief.json silently DISABLES I5 (budget) / I6-FAIL criterion binding / I11 brief-tag
    # membership / I12 propagation / I16's brief-tag high-stakes trigger for that unit — every one of
    # those keys off d.get("brief") and no-ops when it is None. Two layers, both offline/post-hoc
    # (never a live guard, never touches LT7):
    #   Layer 1 (any phase): any unit dir carrying a debrief OR verify primary (either extension) MUST
    #     have a brief.json on disk — catches out-of-graph unit dirs and earlier-phase tampering.
    #   Layer 2 (P8/DONE only, scoped to a materialized sidecar tree): EVERY graph unit needs a
    #     present, schema-valid brief.json. Layer 2 is P8/DONE-only — NOT "P6+" — because mid-P6 a
    #     later-wave graph unit is legitimately un-briefed (see tests/good: P6 with graph U02 having no
    #     dir); briefs are all present only once synthesis is reached.
    for uid in sorted(unit_dirs_with_work):
        udir = os.path.join(units_dir, uid)
        has_dv = any(os.path.exists(os.path.join(udir, f"{n}.{e}"))
                     for n in ("debrief", "verify") for e in ("md", "json"))
        if has_dv and not os.path.exists(os.path.join(udir, "brief.json")):
            rep.fail(f"G-brief offline (units/{uid})",
                     "unit has a debrief/verify but NO brief.json — I5/I6/I11/I12/I16 all key off the "
                     "brief and SILENTLY skip this unit without it (T8: every ready unit has a "
                     "schema-valid brief.json)")
    if phase in ("P8_SYNTHESIS", "DONE") and graph_doc is not None and unit_subdirs:
        for u in graph_doc.get("units", []):
            uid = u.get("id")
            if not os.path.exists(os.path.join(units_dir, uid, "brief.json")):
                rep.fail(f"G-brief offline (units/{uid})",
                         f"phase {phase}: graph unit has no brief.json — briefs are a Phase-5 "
                         "obligation, present for every unit by synthesis (T8)")
            elif unit_docs.get(uid, {}).get("brief") is None:
                rep.fail(f"G-brief offline (units/{uid})",
                         "brief.json present but schema-invalid (see the schema FAIL above) — "
                         "I5/I6/I11/I12/I16 skip this unit until it validates")

    # I10 synthesis/DONE completeness (BRK-02) — no unit may reach P8/DONE unexecuted.
    # T12 "all units accounted for": iterate the GRAPH's declared units, not just the dirs that
    # happen to carry a debrief — else deleting a unit's debrief.json+verify.json made it INVISIBLE
    # (unit_dirs_with_debrief shrank) and a run reached DONE with an unexecuted unit. Every graph
    # unit needs a units/<id>/ dir + a debrief (either extension) + a verify.json with verdict==PASS;
    # a unit blocked at ESCALATE (no PASS) therefore cannot reach DONE without human resolution — the
    # intended semantics, no bypass. SCOPED to runs that MATERIALIZED the per-unit sidecar tree
    # (unit_subdirs non-empty): a run that emits ZERO unit sidecars is the inline-execution shape
    # (units run in-conversation; only the top-level ledger + SYNTHESIS.md persisted — see the archived
    # P8 runs under .wip/), so this per-unit predicate SKIPS just like every other per-unit check
    # (I6/I9/I12/...) already does on absent artifacts. When graph.json is absent at P8/DONE, I3
    # fail-closed (E) already fires above — not duplicated here. Offline/post-hoc; gates no transition.
    if phase in ("P8_SYNTHESIS", "DONE") and unit_subdirs:
        graph_unit_ids = ([u.get("id") for u in graph_doc.get("units", [])]
                          if graph_doc is not None else [])
        for uid in graph_unit_ids:
            if not os.path.isdir(os.path.join(units_dir, uid)):
                rep.fail(f"I10 synthesis completeness (units/{uid})",
                         f"phase {phase}: no units/{uid}/ directory — graph unit never executed "
                         "(T12: all units accounted for)")
                continue
            missing = []
            if uid not in unit_dirs_with_debrief:
                missing.append("no debrief")
            vd = unit_docs.get(uid, {}).get("verify")
            if vd is None:
                missing.append("no valid verify.json")
            elif vd.get("verdict") != "PASS":
                missing.append(f"verify verdict={vd.get('verdict', 'MISSING')} (need PASS)")
            if missing:
                rep.fail(f"I10 synthesis completeness (units/{uid})",
                         f"phase {phase}: {', '.join(missing)} — every graph unit must be "
                         "debriefed and PASS-verified before DONE (T12)")
            else:
                rep.ok(f"I10 synthesis completeness (units/{uid}: debriefed + PASS)")
        # Out-of-graph unit dirs (extra work not declared in graph.json) — keep the existing
        # debrief-keyed completeness check so a stray non-PASS unit can't slip through at DONE.
        for uid in sorted(unit_dirs_with_debrief - set(graph_unit_ids)):
            vd = unit_docs.get(uid, {}).get("verify")
            if not vd or vd.get("verdict") != "PASS":
                got = (vd or {}).get("verdict", "MISSING")
                rep.fail(f"I10 synthesis completeness (units/{uid})",
                         f"phase {phase} but out-of-graph unit verdict={got} (need PASS)")

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

            # ---- 03/P4: ADVISORY tier for imported cross-run learnings (re-grounding gate) ----
            # PARTITION the propagation set the I12 REQUIREMENT consumes into two tiers:
            #   * ACTIVE   = run-local authored entries  ∪  imported entries that have been
            #                RE-GROUNDED to a local signal in THIS run (top-level
            #                grounding == "re-grounded").
            #   * ADVISORY = imported entries (loaded from the project/user store → `eid in
            #                store_ids`, or bearing the global-scoped `G#` id marker) that have
            #                NOT been re-grounded.
            # The I12 required-propagation predicate below runs over the ACTIVE set ONLY. An
            # advisory entry is still LOADED + REPORTED (the rep.ok line below) so a brief author
            # may cite it VOLUNTARILY — but its omission from any brief's learnings_applied NEVER
            # FAILs. This treats an un-re-grounded import as NOT an external signal that binds
            # briefs (AO-4): a lesson carried over from another run is ADVISORY until re-confirmed
            # against a local signal here — the exact 03/P4 intent. Re-grounded imports and every
            # run-local entry stay fully I12-enforced (and a re-grounded/active import keeps the
            # U04/G1 >=2-carrier admission carve-out — it is already generalized). ABSENT STORE =>
            # no imported entries => ACTIVE == today's set => ZERO behavior change (no store => the
            # `good` fixture and every existing fixture are byte-for-byte identical).
            def _is_regrounded(E):
                g = E.get("grounding") if isinstance(E, dict) else None
                return isinstance(g, str) and g.strip() == "re-grounded"
            active, advisory = [], []
            for E in learnings:
                eid = E.get("id") if isinstance(E, dict) else None
                _imported = (eid in store_ids) or (isinstance(eid, str) and eid.startswith("G"))
                if isinstance(E, dict) and _imported and not _is_regrounded(E):
                    advisory.append(E)
                else:
                    active.append(E)
            for E in advisory:
                rep.ok(f"advisory import (not force-injected): {E.get('id')} — imported cross-run "
                       f"learning NOT re-grounded to a local signal (no grounding==\"re-grounded\"); "
                       f"loaded + citable but its omission from a brief never FAILs I12 (AO-4: an "
                       f"un-re-grounded import is not an external signal that binds briefs)")

            prop_ok = True
            for E in active:
                if not isinstance(E, dict):
                    continue
                eid = E.get("id")
                since = _as_int(E.get("since_wave", 1))   # BRK-04: normalize float-integral (schema type=integer accepts 1.0)
                # D01 crash-guard: `since` MUST be an int before the `wave >= since` comparison
                # below (a bad value would raise TypeError). Load-time schema validation already
                # drops malformed entries; this is belt-and-suspenders so no value can crash us.
                if since is None:
                    prop_ok = False
                    rep.fail("I12 learnings since_wave",
                             f"{eid} since_wave={E.get('since_wave')!r} is not an integer >= 1 — "
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
                    # BRK-08 / D-03(a): the I12 predicate enforces the THREE documented SelectorSet
                    # kinds — `all` | unit-id (`U0X`) | `tag:T` — not `tag:` alone. An UNKNOWN selector
                    # shape is a HARD FAIL (was silently `continue`d — precisely how the doc/code drift
                    # stayed invisible). `phaseN` is DELETED from the contract (BRK-09: no unit carries a
                    # `phase` field to match against). Per selector we compute (a) a `match(uid, b)`
                    # predicate, (b) a human `match_desc` (kept byte-identical to the old tag message so
                    # fixture NOTEs stay accurate), and (c) an `admissible` flag + `adm_desc`.
                    if not isinstance(sel, str):
                        prop_ok = False
                        rep.fail("I12 selector", f"{eid} scope.applies_to has a non-string selector {sel!r}")
                        continue
                    if sel == "all":
                        match = lambda uid, b: True
                        match_desc = "matches selector all"
                        # `all` is a generalization over the whole graph — admissible iff >=2 units
                        # (an `all` scope on a 1-unit graph is not a pattern). Asymmetric with tag: on
                        # purpose (see self-learning-loops.md §4.2).
                        admissible, adm_desc = (len(gunits) >= 2), f"graph has {len(gunits)} unit(s) (need >=2)"
                    elif re.fullmatch(r"U[0-9]{2,}", sel):
                        match = (lambda uid, b, _s=sel: uid == _s)
                        match_desc = f"is unit {sel}"
                        # a unit-id selector is a DELIBERATE single-target application, not a
                        # generalization claim — it cannot force-inject beyond its one unit, so it is
                        # ALWAYS admissible (no >=2-carrier re-proof; that rule is tag-specific).
                        admissible, adm_desc = True, "unit-id selector (single-target, always admissible)"
                    elif sel.startswith("tag:"):
                        T = sel[4:]
                        match = (lambda uid, b, _T=T: _T in set(b.get("tags", [])))
                        match_desc = f"carries {sel}"
                        carriers = units_with_tag(T)
                        admissible, adm_desc = (len(carriers) >= 2), f"only {len(carriers)} unit(s) carry it {carriers} (need >=2)"
                    else:
                        prop_ok = False
                        rep.fail("I12 selector",
                                 f"{eid} scope.applies_to selector {sel!r} is not a recognized kind "
                                 "(all | U0X | tag:T) — `phaseN` was removed as unevaluable (BRK-09)")
                        continue
                    if not admissible:                  # admission gate (generalizability re-proof)
                        if _is_imported:
                            # G1 FLAG carve-out: already-generalized imported/global entry — EXEMPT
                            # from the re-proof, still propagation-governed (never silent).
                            rep.ok(f"I12 admission carve-out (G1): {eid} scope {sel} is imported/global "
                                   f"({'store-loaded' if eid in store_ids else 'G#-id'}) — exempt from the "
                                   f"generalizability re-proof ({adm_desc}); still governed by the propagation predicate")
                        else:
                            prop_ok = False
                            rep.fail("I12 learnings admission gate",
                                     f"{eid} scope {sel} inadmissible — {adm_desc}")
                    for uid, d in unit_docs.items():    # propagation predicate (runs for ALL entries, imported or not)
                        b = d.get("brief")
                        if not b:
                            continue
                        w = _as_int(b.get("wave", 0))    # BRK-04: normalize float-integral — 1.0 is a schema-valid
                        if w is None:                    # integer that MUST NOT skip the predicate (was the evasion);
                            continue                     # bool/non-integral only — schema layer already FAILed non-int shapes
                        if match(uid, b) and w >= since \
                           and eid not in b.get("learnings_applied", []):
                            prop_ok = False
                            rep.fail("I12 learnings propagation",
                                     f"units/{uid} {match_desc} at wave {w} "
                                     f">= since_wave {since}: MUST list {eid} in learnings_applied "
                                     f"(has {b.get('learnings_applied')})")
            if prop_ok:
                rep.ok(f"I12 learnings propagation ({len(active)} active entr(y/ies): admission + selector-scope "
                       f"(all|U0X|tag) propagation hold{f'; {len(advisory)} advisory import(s) not force-injected (03/P4)' if advisory else ''})")
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
    # BRK-06 / D-01(a): learnings.json is DELIBERATELY NOT a post-Phase-1 signal. It is ledger
    # BOOKKEEPING, not a work-graph artifact — the exact structural distinction the I-dod trigger
    # already codifies (which excludes learnings.json for the same reason). SKILL.md Phase 0.5 folds
    # surviving cross-run imports into learnings.json BEFORE Phase 1, so counting it as post-P1 work
    # made G-personas FAIL on the intake write and deadlocked the run before the persona gate. Every
    # other trigger (clarifications/cartography/graph/units/synthesis) still fires, so no run with
    # actual downstream work can skip the gate — the two artifact-driven triggers are now consistent.
    # SCOPE OF THIS CHANGE (guarantee bookkeeping): this REVISES ONLY the G-personas trigger. It must
    # NOT touch I2 ledger-is-truth, which shares `post_p1` as an input — a present learnings.json is
    # still a durable RUN ARTIFACT whose existence implies fsm-state.json must be on disk. The two
    # consumers are therefore DELIBERATELY disentangled: I2 below re-adds learnings.json as its own
    # signal so its fail-closed trigger is unchanged (a learnings-only dir with no fsm-state.json still
    # FAILs I2, exactly as before this PR); only G-personas stops firing on ledger bookkeeping.

    # I2 ledger-is-truth (IMP-17) — fsm-state.json is the durable FSM state. If it is ABSENT but the
    # run produced ANY other artifact/unit signal, the state is not on disk — fail closed. A truly
    # EMPTY run dir stays a no-op (init_run.sh seeds fsm-state.json, so an empty dir means "not a
    # run"). Distinct from a present-but-INVALID fsm-state.json, which check_artifact already FAILed.
    # NOTE: learnings.json is an I2 signal even though it is NOT a G-personas signal (see above) — a
    # learnings.json on disk is a real run artifact, so I2's coverage is unchanged by the D-01(a) fix.
    _i2_signals = list(post_p1) + (sorted(unit_subdirs) if unit_subdirs else [])
    if _exists("learnings.json"):
        _i2_signals.append("learnings.json")
    if not os.path.exists(os.path.join(rd, "fsm-state.json")) and _i2_signals:
        rep.fail("I2 ledger-is-truth",
                 "fsm-state.json absent but run artifacts exist "
                 f"({_i2_signals}) — the FSM state must live on disk")

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
