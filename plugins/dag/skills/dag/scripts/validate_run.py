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
  * Bounded Graph Amendments (BGA) — the Phase-6 work graph may grow under mechanical constraints via
    append-only amendments/A<NN>.json records (amendment.schema.json). Five new POST-HOC / OFFLINE
    invariants, none a live transition guard: I3b wave layering + I3c dependency closure (run whenever
    a graph is present — they also close two pre-existing gaps: `waves` was never cross-checked and a
    dangling dep/edge endpoint was never flagged); I17 frozen executed prefix (no amendment touches a
    unit with a debrief/verify); I18 fuel bound (fuel_remaining == fuel_initial - Σ fuel_cost >= 0, the
    revision/amendments_applied bookkeeping — the termination-preserving budget, mirrors retries<=2);
    I19 amendment scope (dod_refs verbatim ∈ definition_of_done, human-gate on scope_change/cancel,
    split coverage). All INERT when amendments/ is absent — BGA PRESERVES the correction-loop
    termination proof and REVISES only the pipeline-level unit-count bound (total units <= N0 + fuel0).

Exit codes:  0 ok · 1 validation/invariant violation · 2 usage error · 3 environment error.
Usage:  validate_run.py <run_dir> [--schemas <dir>] [--self-check] [--quiet]
"""
from __future__ import annotations
import json, os, re, sys, argparse, datetime, fnmatch, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCHEMAS = os.path.normpath(os.path.join(HERE, "..", "schemas"))

TOP_ARTIFACTS = {
    "personas.json": "personas.schema.json",
    "clarifications.json": "clarifications.schema.json",
    "cartography.json": "cartography.schema.json",
    "graph.json": "graph.schema.json",
    "fsm-state.json": "fsm-state.schema.json",
    "sources.json": "sources.schema.json",
    "dialogues.json": "dialogues.schema.json",
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
                    rep.fail(f"{LABEL_STEM['schema']} {sf} $ref",
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
    # DAG_FORCE_MINI=1 (WP9/G7) forces the stdlib mini-validator even where jsonschema is installed,
    # so run_tests.sh can sweep BOTH backends on the same host (CI has jsonschema, which otherwise
    # hides the fallback entirely). Behaviour-neutral: it only selects which validator function runs.
    if os.environ.get("DAG_FORCE_MINI") == "1":
        return _mini_validate, "built-in minimal validator (stdlib only) [DAG_FORCE_MINI]"
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
# ---------------------------------------------------------------------------
# LABELS — the single importable registry of check-label STEMS this validator
# emits. U04 hoist (behaviour-neutral): every PASS/FAIL message below is built by
# interpolating LABEL_STEM[<key>] as its leading static text, so `spec_check.py`
# (U05) can `import validate_run` and enumerate the emittable-label set + group it
# by the `invariant` field WITHOUT running a validation. This is DATA only: it
# moves NO enforcement logic, adds NO gate, and every emitted string stays
# byte-identical. `emitted_via`:
#   * (absent) => hoisted: the stem IS interpolated into a rep.ok/rep.fail label.
#   * "print"  => an ad-hoc NOTE/SKIP print (kept inline verbatim; registered so it
#                 is still enumerable — routing it risked drift, so it stays inline).
#   * "inline" => a rep.ok/rep.fail label whose run-data interpolation LEADS the
#                 string (a path prefix), so it cannot be split stem+tail; kept
#                 inline verbatim and registered for enumeration.
# Bare path/artifact identifiers used as a `what` (e.g. `rel`, `units/<u>/<rel>`,
# `learnings.json`, `amendments/<fn>`) carry no descriptive stem and are not listed.
LABELS = [
    # schema self-check + artifact validation
    {"key": "schema", "stem": "schema", "invariant": "schema"},
    {"key": "note_schema_keywords", "stem": "schema (mini-validator unimplemented keyword)", "invariant": "N-15", "emitted_via": "print"},
    {"key": "artifact_valid_against", "stem": "valid against", "invariant": "schema", "emitted_via": "inline"},
    {"key": "unit_id_mismatch", "stem": "unit_id mismatch", "invariant": "D21", "emitted_via": "inline"},
    {"key": "panelist_independence", "stem": "I1 panelist independence", "invariant": "I1", "emitted_via": "inline"},
    # learnings loader / store / GC
    {"key": "lshape_tolerated", "stem": "learnings.json non-canonical shape tolerated (bare single-entry object wrapped as [entry])", "invariant": "learnings"},
    {"key": "lstore_disc", "stem": "learnings-store discovered", "invariant": "store"},
    {"key": "luser_override", "stem": "learnings user-store override (G2)", "invariant": "G2"},
    {"key": "luser_disc", "stem": "learnings user-store discovered", "invariant": "G2"},
    {"key": "lexpiry", "stem": "learnings expiry (03/P3)", "invariant": "P3"},
    {"key": "ldecay", "stem": "learnings decay/GC (04/G5)", "invariant": "G5"},
    {"key": "lcontra", "stem": "learnings contradiction (03/P5)", "invariant": "P5"},
    {"key": "note_store_malformed", "stem": "MALFORMED (dropped, non-gating — imported store context)", "invariant": "IMP-07", "emitted_via": "print"},
    {"key": "note_contradiction_p5", "stem": "contradiction (03/P5)", "invariant": "P5", "emitted_via": "print"},
    {"key": "note_g3_promotion", "stem": "G3 promotion (advisory)", "invariant": "G3", "emitted_via": "print"},
    # FSM invariants — graph
    {"key": "i3_dag_failclosed", "stem": "I3 DAG fail-closed (E)", "invariant": "I3"},
    {"key": "i3_dag_acyclic", "stem": "I3 DAG acyclic", "invariant": "I3"},
    {"key": "skip_i3_dag", "stem": "I3 DAG", "invariant": "I3", "emitted_via": "print"},
    {"key": "i1b_maker_checker", "stem": "I1b maker!=checker (persona distinctness)", "invariant": "I1b"},
    {"key": "i1c_recon", "stem": "I1c artifact/declaration persona reconciliation", "invariant": "I1c"},
    {"key": "i1d_roster", "stem": "I1d roster membership", "invariant": "I1d"},
    {"key": "i3c_dep_closure", "stem": "I3c dependency closure", "invariant": "I3c"},
    {"key": "i3_unit_unique", "stem": "I3 unit id uniqueness", "invariant": "I3"},
    {"key": "i3b_wave_layering", "stem": "I3b wave layering", "invariant": "I3b"},
    {"key": "skip_i3b_wave", "stem": "I3b wave layering", "invariant": "I3b", "emitted_via": "print"},
    # FSM invariants — loop bounds
    {"key": "i4_loop_bound", "stem": "I4 loop bound", "invariant": "I4"},
    {"key": "i4_loop_crosscheck", "stem": "I4 loop cross-check", "invariant": "I4"},
    {"key": "i4_units_loop_bound", "stem": "I4 units[] loop bound", "invariant": "I4"},
    {"key": "i4_units_crosscheck", "stem": "I4 units[] cross-check", "invariant": "I4"},
    {"key": "i4_iter_ceiling", "stem": "I4 iteration ceiling", "invariant": "I4"},
    # FSM invariants — verifier / socratic / premise
    {"key": "i1_verifier_indep", "stem": "I1 verifier independence", "invariant": "I1"},
    {"key": "i6_fail_defect", "stem": "I6 FAIL defect", "invariant": "I6"},
    {"key": "i6_pass", "stem": "I6 PASS coverage-first", "invariant": "I6"},
    {"key": "i6_actionable", "stem": "I6 FAIL actionable change", "invariant": "I6"},
    {"key": "i5_within_budget", "stem": "I5 within-budget honesty", "invariant": "I5"},
    {"key": "i14_ao2", "stem": "I14 AO-2 do_not_touch disjointness", "invariant": "I14"},
    {"key": "i13_counter", "stem": "I13 socratic counter", "invariant": "I13"},
    {"key": "premise_rerun", "stem": "premise re-run", "invariant": "premise-check"},
    {"key": "premise_deflection", "stem": "premise deflection", "invariant": "premise-check"},
    {"key": "premise_attested", "stem": "premise-check attested", "invariant": "premise-check"},
    # FSM invariants — panel / responsive
    {"key": "i16_panel", "stem": "I16 panel discipline", "invariant": "I16"},
    {"key": "i16_loopdry", "stem": "I16 loop-until-dry bound", "invariant": "I16"},
    {"key": "i15_ao6", "stem": "I15 AO-6 responsive change", "invariant": "I15"},
    # Bounded Graph Amendments
    {"key": "i17_frozen", "stem": "I17 frozen prefix", "invariant": "I17"},
    {"key": "i17_frozen_ok", "stem": "I17 frozen executed prefix", "invariant": "I17"},
    {"key": "i17_reconcile", "stem": "I17 amendment reconciliation", "invariant": "I17"},
    {"key": "i17_anchor", "stem": "I17 frozen-content anchor", "invariant": "I17"},
    {"key": "i18_fuel_bound", "stem": "I18 fuel bound", "invariant": "I18"},
    {"key": "i18_records_required", "stem": "I18 amendment records required", "invariant": "I18"},
    {"key": "i18_bookkeeping", "stem": "I18 amendment bookkeeping", "invariant": "I18"},
    {"key": "i19_scope", "stem": "I19 amendment scope", "invariant": "I19"},
    # FSM invariants — per-unit DoD / non-goal binding (guardrails 1.8.0)
    {"key": "unit_dod_refs", "stem": "I20 unit dod_refs", "invariant": "I20"},
    {"key": "unit_non_goal_refs", "stem": "I21 unit non_goal_refs", "invariant": "I21"},
    # FSM invariants — guardrail compliance / P8 closure / content floors (guardrails 1.8.0)
    {"key": "guardrail_compliance", "stem": "I22 guardrail compliance", "invariant": "I22"},
    {"key": "p8_closure", "stem": "I23 closure", "invariant": "I23"},
    {"key": "register_floor", "stem": "I24 register floor", "invariant": "I24"},
    {"key": "resolution_present", "stem": "I25 resolution present", "invariant": "I25"},
    # FSM invariant — sources register (depth 1.9.0)
    {"key": "sources_register", "stem": "I26 sources register", "invariant": "I26"},
    {"key": "sources_register_note", "stem": "N-I26", "invariant": "I26", "emitted_via": "print"},
    # FSM invariant — clarification dimension-coverage sweep (depth 1.9.0)
    {"key": "clarification_sweep", "stem": "I27 clarification sweep", "invariant": "I27"},
    {"key": "clarification_sweep_note", "stem": "N-I27", "invariant": "I27", "emitted_via": "print"},
    # FSM invariant — human-gated depth-tier floors (depth 1.9.0)
    {"key": "depth_floor", "stem": "I28 depth floor", "invariant": "I28"},
    {"key": "depth_floor_note", "stem": "N-I28", "invariant": "I28", "emitted_via": "print"},
    # FSM invariant — execution-effort briefs (depth 1.9.0)
    {"key": "effort_briefs", "stem": "I29 execution-effort briefs", "invariant": "I29"},
    {"key": "effort_briefs_note", "stem": "N-I29", "invariant": "I29", "emitted_via": "print"},
    # FSM invariant — retrieval coverage verify (depth 1.9.0)
    {"key": "retrieval_coverage_verify", "stem": "I30 retrieval coverage", "invariant": "I30"},
    {"key": "retrieval_coverage_verify_note", "stem": "N-I30", "invariant": "I30", "emitted_via": "print"},
    # FSM invariants — retrieval-standard predicates (depth 1.9.0; U01 RL-1..3 / CO-1)
    {"key": "rl_rung_presence", "stem": "I31 rung presence", "invariant": "I31"},
    {"key": "rl_param_consistency", "stem": "I32 parametric-downgrade consistency", "invariant": "I32"},
    {"key": "rl_premise_presence", "stem": "I33 premise-extraction presence", "invariant": "I33"},
    {"key": "co1_owed_coverage", "stem": "I34 owed coverage", "invariant": "I34"},
    # FSM invariants — bounded Socratic dialogue transcript (socratic-guardrail 1.10.0; U01/U04)
    {"key": "i35_dialogue", "stem": "I35 dialogue", "invariant": "I35"},
    {"key": "i36_dialogue", "stem": "I36 dialogue", "invariant": "I36"},
    {"key": "note_i36", "stem": "N-I36", "invariant": "I36", "emitted_via": "print"},
    {"key": "i37_dialogue", "stem": "I37 dialogue", "invariant": "I37"},
    # FSM invariant — ask-first consequential-default legality (socratic-guardrail 1.10.0; U02/U04)
    {"key": "i38_askfirst", "stem": "I38 ask-first", "invariant": "I38"},
    {"key": "note_i38", "stem": "N-I38", "invariant": "I38", "emitted_via": "print"},
    # FSM invariants — anchor governance (socratic-guardrail 1.10.0; U03/U04/U06)
    {"key": "i39_anchor", "stem": "I39 anchor", "invariant": "I39"},
    {"key": "note_i39", "stem": "N-I39", "invariant": "I39", "emitted_via": "print"},
    {"key": "i40_anchor", "stem": "I40 anchor", "invariant": "I40"},
    # FSM invariants — verification presence / synthesis
    {"key": "i9_missing", "stem": "I9 missing verification", "invariant": "I9"},
    {"key": "i9_present", "stem": "I9 verification present", "invariant": "I9"},
    {"key": "i9_verify_wo_debrief", "stem": "I9 verify-without-debrief", "invariant": "I9"},
    {"key": "gbrief", "stem": "G-brief offline", "invariant": "G-brief"},
    {"key": "i10_synth", "stem": "I10 synthesis completeness", "invariant": "I10"},
    # FSM invariants — tags / learnings propagation
    {"key": "i11_global_reg", "stem": "I11 global tag registry (G1)", "invariant": "I11"},
    {"key": "i11_tag_vocab", "stem": "I11 tag vocabulary", "invariant": "I11"},
    {"key": "advisory_import", "stem": "advisory import (not force-injected)", "invariant": "I12"},
    {"key": "i12_since_wave", "stem": "I12 learnings since_wave", "invariant": "I12"},
    {"key": "i12_model_narrow", "stem": "I12 model narrowing (04/G4)", "invariant": "I12"},
    {"key": "i12_selector", "stem": "I12 selector", "invariant": "I12"},
    {"key": "i12_provenance", "stem": "I12 import provenance", "invariant": "I12"},
    {"key": "i12_admission_carveout", "stem": "I12 admission carve-out (G1)", "invariant": "I12"},
    {"key": "i12_admission_gate", "stem": "I12 learnings admission gate", "invariant": "I12"},
    {"key": "i12_propagation", "stem": "I12 learnings propagation", "invariant": "I12"},
    {"key": "skip_i12_prop", "stem": "I12 learnings propagation", "invariant": "I12", "emitted_via": "print"},
    # FSM invariants — disagreement / ambiguity / DoD / personas / gates
    {"key": "i7_single_rec", "stem": "I7 single recommended option", "invariant": "I7"},
    {"key": "i8_open", "stem": "I8 open material ambiguity", "invariant": "I8"},
    {"key": "i8_noopen", "stem": "I8 no open material ambiguity", "invariant": "I8"},
    {"key": "idod", "stem": "I-dod DoD/non-goals present", "invariant": "I-dod"},
    {"key": "i2_ledger", "stem": "I2 ledger-is-truth", "invariant": "I2"},
    {"key": "i2_status_verdict", "stem": "I2 status vs verify verdict", "invariant": "I2"},
    {"key": "i2_units_subset", "stem": "I2 fsm units subset", "invariant": "I2"},
    {"key": "i2_fsm_unit_unique", "stem": "I2 fsm units uniqueness", "invariant": "I2"},
    {"key": "i2_phase_floor", "stem": "I2 phase artifact floor", "invariant": "I2"},
    {"key": "gpersonas_nonskip", "stem": "G-personas non-skippable", "invariant": "G-personas"},
    {"key": "gpersonas_failclosed", "stem": "G-personas fail-closed", "invariant": "G-personas"},
    {"key": "gate_ordering", "stem": "gate ordering", "invariant": "gate-ordering"},
    {"key": "escalate_origin", "stem": "ESCALATE origin provenance", "invariant": "escalate-origin"},
    {"key": "note_selfcheck", "stem": "acceptance_self_check vs verify (C6)", "invariant": "selfcheck", "emitted_via": "print"},
]
LABEL_STEM = {e["key"]: e["stem"] for e in LABELS}

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
            rep.fail(f"{LABEL_STEM['schema']} {sf}", f"not valid JSON: {e}")
            continue
        if "$schema" not in s or "type" not in s:
            rep.fail(f"{LABEL_STEM['schema']} {sf}", "missing $schema or type")
            continue
        schemas[sf] = s
        rep.ok(f"{LABEL_STEM['schema']} {sf} well-formed")
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

            # D-04(a)/IMP-20: bless per-panelist verify files. A panel MAY persist each member's
            # FULL verify as verify_p<N>.json (same verify.schema.json) for audit; the aggregated
            # verdict still lives in verify.json + verify.json.panel[]. Validate-if-present: each
            # must be schema-valid (verify.schema pins executor_reasoning_seen const:false — the I1
            # blindness attestation) and declare a unit_id matching its directory (D21). These are
            # AUDIT artifacts — deliberately NOT inserted into unit_docs, so they never override the
            # aggregated verify.json that the downstream per-unit checks (I6/I16/…) read. Additive /
            # validate-if-present => PRESERVES (a run with no verify_p* files is unaffected).
            for prel in sorted(f for f in os.listdir(udir)
                               if f.startswith("verify_p") and f.endswith(".json")):
                p = os.path.join(udir, prel)
                try:
                    pinst = load_json(p)
                except Exception as e:
                    rep.fail(f"units/{uid}/{prel}", f"not valid JSON: {e}")
                    continue
                ps = schemas.get("verify.schema.json")
                if ps is None:
                    rep.fail(f"units/{uid}/{prel}", "no schema loaded for verify.schema.json")
                    continue
                perrs = validate(pinst, ps)
                if perrs:
                    for e in perrs:
                        rep.fail(f"units/{uid}/{prel}", e)
                    continue
                paid = pinst.get("unit_id")
                if paid is not None and paid != uid:
                    rep.fail(f"units/{uid}/{prel} unit_id mismatch",
                             f"panelist verify declares unit_id {paid!r} but lives in directory {uid!r}")
                    continue
                # Defense-in-depth (mirrors I1): verify.schema already pins executor_reasoning_seen
                # const:false, so a true value was schema-INVALID above; this explicit check keeps the
                # D-04 audit-blindness requirement legible and still bites in a no-schema degraded mode.
                if pinst.get("executor_reasoning_seen") is not False:
                    rep.fail(f"units/{uid}/{prel} I1 panelist independence",
                             "executor_reasoning_seen must be false in an audit panelist verify")
                else:
                    rep.ok(f"units/{uid}/{prel} valid against verify.schema.json (panelist audit, blind)")

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
                    rep.ok(f"{LABEL_STEM['lshape_tolerated']}")
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
                        # wins — do NOT force a duplicate into the propagation set. WP-C/A4: but the id
                        # DOES exist in a store, so record it in `store_ids` as CORROBORATION — an
                        # honestly-folded import (copied run-local, so shadowed here) is then a genuine
                        # store member for _import_provenance_ok, not a "forged by id spelling" false FAIL.
                        store_ids.add(eid)
                        continue
                    have_ids.add(eid)
                    store_ids.add(eid)
                    learnings.append(E)
                    merged += 1
        rep.ok(f"{LABEL_STEM['lstore_disc']} ({merged} project entr(y/ies) merged from {len(store_dirs)} store dir(s))")

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
                    store_ids.add(eid)                 # WP-C/A4: still a genuine store member — corroborates origin.store
                    rep.ok(f"{LABEL_STEM['luser_override']}: user entry {eid} shadowed by a "
                           f"higher-precedence entry of the same id — dropped from propagation (project > user)")
                    u_over += 1
                    continue
                if escope and escope in high_scopes:   # scope collision => project/run-local wins
                    rep.ok(f"{LABEL_STEM['luser_override']}: user entry {eid} shadowed on scope "
                           f"{sorted(escope)} by a higher-precedence entry — dropped from propagation (project > user)")
                    u_over += 1
                    continue
                if escope and escope in user_scopes_seen:   # N-11: user-vs-user scope collision
                    rep.ok(f"{LABEL_STEM['luser_override']}: user entry {eid} shadowed on scope "
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
        rep.ok(f"{LABEL_STEM['luser_disc']} (~/.claude/dag/learnings/): {u_merged} user entr(y/ies) "
               f"merged, {u_over} overridden by project/run-local (project > user)")

    # --- P3 expiry grammar (LOADER-side, per Cartography R4 — NOT a schema enum) ---
    # Parse the bare `scope.expiry` string grammar `run | project | runs:N | date:<iso>` plus
    # the optional decay fields. An EXPIRED entry is EXCLUDED from propagation and REPORTED as
    # a skip — it is NEVER a hard-fail (an expired lesson simply reverts to today's
    # re-derive-from-scratch behavior, the safe failure mode). An ABSENT expiry is INERT (existing
    # entries carry none, so they are untouched). A5/WP-D: an UNRECOGNIZED expiry is NOT reached here
    # inertly — since the N-08 schema pin it is a hard schema FAIL on a run-local entry (rejected before
    # this runs) and reported+dropped on a store entry; so by the time _expiry_expired sees an entry,
    # its expiry is either absent or grammar-valid.
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
                rep.ok(f"{LABEL_STEM['lexpiry']}: {E.get('id')} EXCLUDED from propagation ({why})")
                continue
            decayed, dwhy = _idle_decayed(E, from_store)
            if decayed:
                rep.ok(f"{LABEL_STEM['ldecay']}: {E.get('id')} EXCLUDED from propagation — idle-decay "
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
                rep.ok(f"{LABEL_STEM['lcontra']}: {E.get('id')} superseded — excluded from propagation")
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

    # ---- Bounded Graph Amendments: load append-only amendment records (I17/I18/I19) ----
    # Glob amendments/*.json (sorted); schema-validate each against amendment.schema.json; a
    # malformed record is REPORTED (rep.fail — it IS this run's emitted artifact) and DROPPED so it
    # can never reach the I17/I18/I19 predicates below. `amendments` is a list of (filename, record)
    # in sorted-filename order. ABSENT amendments/ dir => empty list => every new check (I17/I18/I19
    # and the amendment-gated arm of I3b) is INERT — a legacy run with no amendments is byte-for-byte
    # unaffected. Post-hoc/offline over emitted artifacts: no live guard on any transition (never
    # touches LT7), so BGA PRESERVES the correction-loop termination proof (Claims A-D hold verbatim).
    amendments = []
    amend_dir = os.path.join(rd, "amendments")
    if os.path.isdir(amend_dir):
        _amend_schema = schemas.get("amendment.schema.json")
        for fn in sorted(f for f in os.listdir(amend_dir) if f.endswith(".json")):
            fp = os.path.join(amend_dir, fn)
            try:
                inst = load_json(fp)
            except Exception as e:
                rep.fail(f"amendments/{fn}", f"not valid JSON: {e}")
                continue
            if _amend_schema is None:
                rep.fail(f"amendments/{fn}", "no schema loaded for amendment.schema.json")
                continue
            errs = validate(inst, _amend_schema)
            if errs:
                for e in errs:
                    rep.fail(f"amendments/{fn}", e)
                continue  # DROP malformed record — it must not reach I17/I18/I19
            amendments.append((fn, inst))
            rep.ok(f"amendments/{fn} valid against amendment.schema.json")

    # Once decomposition is approved, an authoritative graph.json MUST exist — you
    # cannot reach P5+ by deleting BOTH GRAPH.md and graph.json (fail-closed).
    if post_decomposition and graph_doc is None:
        rep.fail(f"{LABEL_STEM['i3_dag_failclosed']}",
                 f"phase/gates indicate post-decomposition ({phase}) but no VALID authoritative "
                 f"graph.json (graph.json {'invalid' if graph_json_exists else 'absent'}) — "
                 "refusing to advance without an enforceable DAG")
    if graph_md_exists and graph_doc is None:
        rep.fail(f"{LABEL_STEM['i3_dag_failclosed']}",
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
            rep.fail(f"{LABEL_STEM['i3_dag_acyclic']} (graph.json authoritative)", "cycle: " + " → ".join(cyc))
        else:
            rep.ok(f"{LABEL_STEM['i3_dag_acyclic']} (graph.json authoritative, {len(edges)} edges)")

        # I1b maker!=checker (persona distinctness) — prime directive #3 / Alloy
        # DistinctMakerChecker: a unit's executor and verifier personas MUST differ.
        # (Labeled I1b, the structural sibling of I1 verifier-independence; every I1..I13
        # integer is already taken, so a sub-label avoids a numbering collision.)
        for u in graph_doc.get("units", []):
            if u.get("executor_persona") == u.get("verifier_persona"):
                rep.fail(f"{LABEL_STEM['i1b_maker_checker']}",
                         f"{u.get('id')} has executor_persona == verifier_persona "
                         f"({u.get('executor_persona')!r}) — maker and checker must be distinct")
            else:
                rep.ok(f"{LABEL_STEM['i1b_maker_checker']} (units/{u.get('id')})")

        # I1c artifact/declaration persona reconciliation (WP-B/C1) — I1b compares only the DECLARED
        # graph personas; nothing tied the ACTUAL artifact personas to those declarations, so one
        # persona could execute a unit AND verify it while I1b still printed PASS. For every unit with
        # BOTH a debrief and a verify: debrief.persona must equal the graph executor_persona,
        # verify.verifier_persona the graph verifier_persona, and the two artifact personas must DIFFER
        # (maker != checker at the artifact level, not just in the graph). Offline/post-hoc; gates no
        # transition. Mechanizes prime-directive #3 / I1 the same way I1b did — see Limitation D (a
        # genuinely distinct MODEL behind a distinct persona LABEL stays unobservable).
        _gunits_i1c = {u.get("id"): u for u in graph_doc.get("units", [])}
        for uid in sorted(unit_docs):
            _de = unit_docs[uid].get("debrief")
            _ve = unit_docs[uid].get("verify")
            if not (isinstance(_de, dict) and isinstance(_ve, dict)):
                continue
            _dp, _vp = _de.get("persona"), _ve.get("verifier_persona")
            _gu = _gunits_i1c.get(uid)
            _probs = []
            if isinstance(_gu, dict):
                if _dp != _gu.get("executor_persona"):
                    _probs.append(f"debrief.persona {_dp!r} != graph executor_persona {_gu.get('executor_persona')!r}")
                if _vp != _gu.get("verifier_persona"):
                    _probs.append(f"verify.verifier_persona {_vp!r} != graph verifier_persona {_gu.get('verifier_persona')!r}")
            if _dp is not None and _dp == _vp:
                _probs.append(f"debrief.persona == verify.verifier_persona ({_dp!r}) — the executor also "
                              "verified its own unit (maker == checker)")
            if _probs:
                rep.fail(f"{LABEL_STEM['i1c_recon']} (units/{uid})", "; ".join(_probs))
            else:
                rep.ok(f"{LABEL_STEM['i1c_recon']} (units/{uid})")

        # I1d roster membership (WP-B/C2) — personas.schema.json's stated purpose ("enables the
        # maker!=checker invariant to be checked structurally") was unrealized: every working persona
        # (graph executor/verifier, brief/debrief.persona, verify.verifier_persona, panel members)
        # could be a fabricated string absent from the confirmed roster. Require each to be a member of
        # personas.json.roster. Runs only when a roster is present (its absence is G-personas' job).
        # Offline/post-hoc; gates no transition. The roster is a confirmed-membership check, NOT proof
        # the named model actually staffed the unit (Limitation D).
        _personas = docs.get("personas")
        if isinstance(_personas, dict):
            _roster = {r.get("persona") for r in _personas.get("roster", []) if isinstance(r, dict)}
            _working = {}   # persona -> first source that used it (deterministic report)
            for u in graph_doc.get("units", []):
                for _lbl, _k in (("graph executor", "executor_persona"), ("graph verifier", "verifier_persona")):
                    _p = u.get(_k)
                    if _p:
                        _working.setdefault(_p, f"{_lbl} {u.get('id')}")
            for uid in sorted(unit_docs):
                _dd = unit_docs[uid]
                for _doc, _k, _lbl in ((_dd.get("brief"), "persona", "brief"),
                                       (_dd.get("debrief"), "persona", "debrief"),
                                       (_dd.get("verify"), "verifier_persona", "verify")):
                    if isinstance(_doc, dict) and _doc.get(_k):
                        _working.setdefault(_doc.get(_k), f"{_lbl} units/{uid}")
                _ve = _dd.get("verify")
                if isinstance(_ve, dict):
                    for _m in _ve.get("panel", []) or []:
                        if isinstance(_m, dict) and _m.get("verifier_persona"):
                            _working.setdefault(_m.get("verifier_persona"), f"panel units/{uid}")
            _absent = sorted(p for p in _working if p not in _roster)
            if _absent:
                rep.fail(f"{LABEL_STEM['i1d_roster']}",
                         f"working persona(s) {_absent} absent from the confirmed personas.json roster "
                         f"{sorted(_roster)} — every executor/verifier/panel persona must be a confirmed "
                         f"roster member (e.g. {_absent[0]!r} used by {_working[_absent[0]]})")
            elif _working:
                rep.ok(f"{LABEL_STEM['i1d_roster']} ({len(_working)} working persona(s) all in roster)")

        # I3c dependency closure (BGA — closes a pre-existing validator gap, EVALUATION §6).
        # Every `deps` element and every `edges[].from/to` MUST name a CURRENT unit id; a dangling
        # reference (incl. a retired id still referenced) becomes a phantom node in cycle detection,
        # so fail closed. Runs whenever a graph is present (NOT amendment-gated) — verified inert on
        # all 54 legacy fixtures (their graph.json has no dangling deps/edges). Offline/post-hoc.
        _unit_ids = {u.get("id") for u in graph_doc.get("units", [])}
        # B8 (WP5): duplicate unit ids in graph.json.units[] make enforcement ORDER-DEPENDENT — every
        # downstream consumer collapses units into a dict/set (last-entry-wins), so a duplicate can
        # smuggle a benign copy past a tag-scoped check (e.g. hide a high-stakes panel requirement).
        # JSON Schema cannot express cross-item uniqueness on a derived key; the validator is the only
        # enforcement point. Offline/post-hoc.
        _id_list = [u.get("id") for u in graph_doc.get("units", [])]
        if len(_id_list) != len(_unit_ids):
            _dupe_ids = sorted({x for x in _id_list if _id_list.count(x) > 1})
            rep.fail(f"{LABEL_STEM['i3_unit_unique']}",
                     f"duplicate unit id(s) {_dupe_ids} in graph.json units[] — ids must be unique "
                     "(enforcement collapses duplicates last-wins, making verdicts order-dependent)")
        else:
            rep.ok(f"{LABEL_STEM['i3_unit_unique']} ({len(_unit_ids)} unique unit id(s))")
        _dangling = set()
        for u in graph_doc.get("units", []):
            for d in u.get("deps", []):
                if d not in _unit_ids:
                    _dangling.add(d)
        for e in graph_doc.get("edges", []):
            for endp in (e.get("from"), e.get("to")):
                if endp not in _unit_ids:
                    _dangling.add(endp)
        if _dangling:
            rep.fail(f"{LABEL_STEM['i3c_dep_closure']}",
                     f"dep/edge endpoint(s) {sorted(_dangling)} not in units[] — a dangling "
                     "reference (a retired or nonexistent unit id) is a phantom node in cycle detection")
        else:
            rep.ok(f"{LABEL_STEM['i3c_dep_closure']} ({len(_unit_ids)} unit(s); all deps/edges resolve)")

        # I3b wave layering (BGA — closes a pre-existing validator gap, EVALUATION §6: graph.json.waves
        # was never cross-checked, so a layering-violating-yet-acyclic graph passed silently). When
        # `waves` is present: every graph unit appears in exactly one wave group (and no wave group
        # names a non-unit), and every edge in `edges ∪ deps-derived` rises strictly in wave
        # (wave(from) < wave(to)). When amendments exist, `waves` is REQUIRED (absent => FAIL — new
        # units are placed by wave, so layering is load-bearing for by-construction safety); without
        # amendments an absent `waves` is a SKIP (today's behavior — the backward-compat anchor).
        # _as_int normalizes float-integral waves (BRK-04, the wave_float_gap precedent). Offline/post-hoc.
        _waves = graph_doc.get("waves")
        if not isinstance(_waves, list):
            if amendments:
                rep.fail(f"{LABEL_STEM['i3b_wave_layering']}",
                         "amendments present but graph.json has no `waves` — wave layering is required "
                         "once the graph is amended (new units are placed strictly above their deps by wave)")
            elif not args.quiet:
                print("  SKIP  I3b wave layering: graph.json has no `waves` (not required without amendments)")
        else:
            _wave_of = {}
            _multi = []
            for w in _waves:
                for uid in w.get("units", []):
                    if uid in _wave_of:
                        _multi.append(uid)
                    _wave_of[uid] = _as_int(w.get("wave"))
            _i3b_ok = True
            _missing = sorted(_unit_ids - set(_wave_of))
            _extra = sorted(set(_wave_of) - _unit_ids)
            if _multi:
                _i3b_ok = False
                rep.fail(f"{LABEL_STEM['i3b_wave_layering']}", f"unit(s) {sorted(set(_multi))} appear in >1 wave group")
            if _missing:
                _i3b_ok = False
                rep.fail(f"{LABEL_STEM['i3b_wave_layering']}", f"unit(s) {_missing} absent from every wave group (each unit needs exactly one wave)")
            if _extra:
                _i3b_ok = False
                rep.fail(f"{LABEL_STEM['i3b_wave_layering']}", f"wave group(s) list non-unit id(s) {_extra}")
            for a, b in edges:
                wa, wb = _wave_of.get(a), _wave_of.get(b)
                if wa is not None and wb is not None and not (wa < wb):
                    _i3b_ok = False
                    rep.fail(f"{LABEL_STEM['i3b_wave_layering']}",
                             f"edge {a}->{b} violates layering: wave({a})={wa} not < wave({b})={wb}")
            if _i3b_ok:
                rep.ok(f"{LABEL_STEM['i3b_wave_layering']} ({len(_wave_of)} unit(s) across {len(_waves)} wave(s); all edges rise)")
    if graph_md_exists:  # defense-in-depth on the prose graph
        # WP-A/B3: GRAPH.md as a directory or a dangling symlink raised IsADirectoryError/OSError here
        # (open() was the sole unguarded loader), aborting the whole run with a traceback and silently
        # disabling every downstream invariant. Wrap it like every other loader — an unreadable GRAPH.md
        # is a fail-closed I3 defect, not a crash.
        md_text = None
        try:
            with open(graph_md, encoding="utf-8") as f:
                md_text = f.read()
        except OSError as e:
            rep.fail(f"{LABEL_STEM['i3_dag_acyclic']} (GRAPH.md)",
                     f"GRAPH.md is present but unreadable ({e}) — a GRAPH.md that is a directory or a "
                     "dangling symlink cannot back the DAG; refusing to pass")
        if md_text is not None:
            cyc = find_cycle(parse_graph_edges(md_text))
            if cyc:
                rep.fail(f"{LABEL_STEM['i3_dag_acyclic']} (GRAPH.md fenced)", "cycle: " + " → ".join(cyc))
            elif graph_doc is None and md_has_unfenced_deps(md_text):
                rep.fail(f"{LABEL_STEM['i3_dag_failclosed']}",
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
            rep.fail(f"{LABEL_STEM['i4_loop_bound']}", f"fsm loop.retries={retries} > 2")
        elif retries is not None:
            rep.ok(f"{LABEL_STEM['i4_loop_bound']} (retries={retries} <= 2)")
        vd = unit_docs.get(luid, {}).get("verify")
        vd_it = _as_int(vd.get("iteration")) if vd else None
        if vd and retries is not None and vd_it is not None:
            if vd_it > retries + 1:
                rep.fail(f"{LABEL_STEM['i4_loop_crosscheck']}",
                         f"{luid} verify.iteration={vd_it} > retries+1={retries + 1}")
            else:
                rep.ok(f"{LABEL_STEM['i4_loop_crosscheck']} ({luid}: iteration<=retries+1)")

    # I4 per-unit units[] loop bound + cross-check (D-02/IMP-11). Parallel waves put >1 unit in
    # flight, but the single top-level `loop` slot can only snapshot the most-recently-transitioned
    # unit; so each `units[]` item MAY now carry its own durable `retries` (+ `loop_state`). When an
    # item records `retries`, apply the SAME I4 bound the loop slot enforces — extended to every unit
    # that records its own retry count, not just fsm.loop.unit_id. POST-HOC/OFFLINE over emitted
    # artifacts: it gates no transition and adds no live LT7 guard, so it cannot deadlock the loop
    # (PRESERVES termination; REVISES only I4's cross-check surface — see state-machine.md §1a/§2a).
    # The retries>2 branch mirrors the loop-slot defense-in-depth (N-17): dead when schemas load
    # (fsm-state.schema units[].retries maximum=2 rejects it first), live only in no-schema mode.
    if fsm and isinstance(fsm.get("units"), list):
        for _u in fsm["units"]:
            if not isinstance(_u, dict):
                continue                       # malformed item — schema already FAILed it
            _uid = _u.get("unit_id")
            _r = _as_int(_u.get("retries"))    # BRK-04: normalize float-integral; None => not recorded
            if _r is None:
                continue                       # per-unit retries absent — nothing to cross-check
            if _r > 2:
                rep.fail(f"{LABEL_STEM['i4_units_loop_bound']} (units/{_uid})", f"fsm units[] retries={_r} > 2")
                continue
            _uv = unit_docs.get(_uid, {}).get("verify")
            _uv_it = _as_int(_uv.get("iteration")) if _uv else None
            if _uv_it is None:
                continue                       # no verify yet (unit still in flight) — nothing to check
            if _uv_it > _r + 1:
                rep.fail(f"{LABEL_STEM['i4_units_crosscheck']} (units/{_uid})",
                         f"verify.iteration={_uv_it} > retries+1={_r + 1} (fsm units[] retries={_r})")
            else:
                rep.ok(f"{LABEL_STEM['i4_units_crosscheck']} ({_uid}: iteration<=retries+1)")

    # I4 iteration ceiling (universal) - the two per-unit cross-checks above only cover units that
    # declare a retries count (fsm.loop.unit_id, and any units[] item carrying `retries`); every
    # OTHER unit's verify.iteration is still bounded here by the absolute ceiling
    # retries.maximum(2)+1 = 3 (I4: iteration<=retries+1, retries<=2).
    for _uid, _d in unit_docs.items():
        _v = _d.get("verify")
        _v_it = _as_int(_v.get("iteration")) if _v is not None else None   # BRK-04: normalize float-integral
        if _v_it is not None and _v_it > 3:
            rep.fail(f"{LABEL_STEM['i4_iter_ceiling']} (units/{_uid})",
                     f"verify.iteration={_v_it} > 3 (retries<=2 => iteration<=retries+1<=3)")

    # I1 verifier independence (shape). Defense-in-depth (D28): verify.schema pins
    # executor_reasoning_seen to const:false, so a violating doc is already schema-INVALID and
    # never lands in unit_docs — this FAIL branch is effectively unreachable but kept explicit.
    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v is not None:
            if v.get("executor_reasoning_seen") is False:
                rep.ok(f"{LABEL_STEM['i1_verifier_indep']} attested (units/{uid})")
            else:
                rep.fail(f"{LABEL_STEM['i1_verifier_indep']} (units/{uid})",
                         "executor_reasoning_seen must be false")

    # I6 evidence-bound FAIL — each defect.criterion must be drawn from brief.acceptance_criteria
    for uid, d in unit_docs.items():
        v, b = d.get("verify"), d.get("brief")
        if v and v.get("verdict") == "FAIL" and b:
            crit = set(b.get("acceptance_criteria", []))
            bad = [df.get("criterion") for df in v.get("defects", [])
                   if df.get("criterion") not in crit]
            if bad:
                rep.fail(f"{LABEL_STEM['i6_fail_defect']} criterion (units/{uid})",
                         f"defect criteria {bad} not in brief.acceptance_criteria")
            else:
                rep.ok(f"{LABEL_STEM['i6_fail_defect']} criteria drawn from brief (units/{uid})")

    # I6 FAIL actionable change (WP5: G11) — a FAIL must name >=1 NON-BLANK actionable change (AO-3).
    # `actionable_changes: [" "]` satisfies the schema minLength:1 but is not actionable; apply the same
    # .strip() non-blank test the I15 counterpart already uses (the schema now also pins pattern "\\S",
    # so this is defense-in-depth). Offline/post-hoc.
    for uid, d in unit_docs.items():
        v = d.get("verify")
        if v and v.get("verdict") == "FAIL":
            _ac = (v.get("feedback") or {}).get("actionable_changes") or []
            if not any(isinstance(x, str) and x.strip() for x in _ac):
                rep.fail(f"{LABEL_STEM['i6_actionable']} (units/{uid})",
                         "FAIL feedback.actionable_changes has no non-blank entry — a FAIL must name "
                         "≥1 concrete change (AO-3; a whitespace-only string is not actionable)")
            else:
                rep.ok(f"{LABEL_STEM['i6_actionable']} (units/{uid})")

    # I5 within-budget honesty (WP5: G9) — the schema only forces within_budget:false ABOVE the global
    # 32000 ceiling; a unit briefed 16000 that consumed 20000 with within_budget:true still passes.
    # Tie the honesty signal to the unit's OWN brief.budget_tokens: consumed > budget with within_budget
    # true is a dishonest report (undermines the IMP-04/re-atomization signal). Offline/post-hoc.
    for uid, d in unit_docs.items():
        dbf, b = d.get("debrief"), d.get("brief")
        if not isinstance(dbf, dict) or not isinstance(b, dict):
            continue
        _fp = dbf.get("footprint") or {}
        _tc = _as_int(_fp.get("tokens_consumed"))
        _bt = _as_int(b.get("budget_tokens"))
        if _tc is not None and _bt is not None and _tc > _bt and _fp.get("within_budget") is True:
            rep.fail(f"{LABEL_STEM['i5_within_budget']} (units/{uid})",
                     f"debrief.footprint.within_budget==true but tokens_consumed={_tc} > "
                     f"brief.budget_tokens={_bt} — an over-budget unit must report within_budget:false (I5/IMP-04)")
        elif _tc is not None and _bt is not None:
            rep.ok(f"{LABEL_STEM['i5_within_budget']} (units/{uid}: {_tc} within brief budget {_bt} or honestly flagged)")

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
                rep.fail(f"{LABEL_STEM['i6_pass']} (units/{uid})",
                         f"PASS carries {blocking} defect(s) — a PASS may record only `minor` "
                         "observations (I6 PASS-clause revised for coverage-first, PR1)")
            else:
                rep.ok(f"{LABEL_STEM['i6_pass']} (units/{uid}: minor-only or no defects)")

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
        # WP-D/A2 (REVISES I14/AO-2): scope the do_not_touch intersection to blocker|major defects.
        # The old check intersected ALL defects regardless of severity, which was mutually
        # UNSATISFIABLE with the coverage-first mandate (report every finding + its severity,
        # methodology.md §Verification): reporting a minor observation on a previously-clean criterion
        # was a hard I14 FAIL, yet suppressing it violated coverage-first — no compliant path existed.
        # Scoping restores satisfiability while preserving AO-2's purpose (a retry must not CHURN
        # settled work): a blocker/major on a sealed criterion is a real regression and still FAILs; a
        # minor coverage-first observation is REPORTABLE (advisory NOTE, not a FAIL).
        _dnt = set(dnt)
        _bm = sorted(x for x in ({df.get("criterion") for df in v.get("defects", [])
                                  if isinstance(df, dict) and df.get("severity") in ("blocker", "major")} & _dnt)
                     if x is not None)
        _minor = sorted(x for x in ({df.get("criterion") for df in v.get("defects", [])
                                     if isinstance(df, dict) and df.get("severity") == "minor"} & _dnt)
                        if x is not None)
        if _bm:
            rep.fail(f"{LABEL_STEM['i14_ao2']} (units/{uid})",
                     f"blocker/major defect criteria {_bm} intersect prior_feedback.do_not_touch — a "
                     "retry must not re-open (regress) what the prior iteration marked correct (AO-2)")
        else:
            if _minor and not args.quiet:
                print(f"  NOTE  {LABEL_STEM['i14_ao2']} (units/{uid}): minor coverage-first observation(s) "
                      f"{_minor} on a previously-sealed criterion — REPORTABLE, not a re-opening "
                      "(a blocker/major here would FAIL; A2 severity scoping)")
            rep.ok(f"{LABEL_STEM['i14_ao2']} (units/{uid})")

    # I13 socratic counter records an OUTCOME (debrief + verify)
    def check_counter(label, soc):
        if not isinstance(soc, dict):
            return
        c = (soc.get("counter") or "").strip()
        # D20: blank/placeholder counters record no OUTCOME (I13) and are rejected. The mechanical
        # sentinel is a full sentence, so it is never a member of BLANK_COUNTER and is accepted here
        # without an explicit exclusion (the old `!= MECH_SENTINEL` clause was always true — dead).
        if c.lower() in BLANK_COUNTER:
            rep.fail(f"{LABEL_STEM['i13_counter']} ({label})",
                     f"counter {c!r} records no OUTCOME (blank/'n/a'); "
                     f"mechanical sentinel = {MECH_SENTINEL!r}")
        else:
            rep.ok(f"{LABEL_STEM['i13_counter']} records an outcome ({label})")
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
            rep.fail(f"{LABEL_STEM['premise_rerun']} (units/{uid})",
                     "premise_check.counter_reran_independently must be true "
                     "(decoupled COUNTER re-run not attested)")
        elif pc.get("is_load_bearing") is False and v.get("verdict") == "PASS":
            rep.fail(f"{LABEL_STEM['premise_deflection']} (units/{uid})",
                     "verifier attests executor premise is NOT load-bearing yet verdict=PASS")
        else:
            rep.ok(f"{LABEL_STEM['premise_attested']} (units/{uid})")

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
    _graph_unit_exec = {}
    if graph_doc is not None:
        for _u in graph_doc.get("units", []):
            _graph_unit_tags[_u.get("id")] = set(_u.get("tags", []) or [])
            _graph_unit_exec[_u.get("id")] = _u.get("executor_persona")

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
            rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
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
                rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                         f"panel has {len(members)} member(s) — a panel needs >=3 members (odd recommended so ties are rare)")
            if not CANON_LENSES.issubset(lenses):
                panel_ok = False
                rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                         f"panel lenses {sorted(l for l in lenses if l)} do not cover the canonical "
                         f"trio {sorted(CANON_LENSES)} — panel members must have DISTINCT lenses, not clones")
            # WP-B/C4: panel INDEPENDENCE — distinct lenses alone did not stop a panel of three CLONES
            # sharing one verifier_persona. verifier_persona is schema-optional, so check pairwise
            # distinctness over the members that DECLARE one, and that none is the unit's executor
            # persona (a panelist may not be the maker). Independence is the whole point of the panel.
            _pv = [m.get("verifier_persona") for m in members if m.get("verifier_persona")]
            if len(_pv) != len(set(_pv)):
                panel_ok = False
                _pv_dupes = sorted({p for p in _pv if _pv.count(p) > 1})
                rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                         f"panel verifier_persona(s) {_pv_dupes} appear on multiple members — an "
                         "independent panel needs DISTINCT verifiers, not clones sharing one persona")
            _exec_p = _graph_unit_exec.get(uid) or b.get("persona")
            if _exec_p is not None and _exec_p in set(_pv):
                panel_ok = False
                rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                         f"panel includes the unit's executor persona {_exec_p!r} — a panelist may not "
                         "be the maker (maker != checker)")
            maj = _discrete_majority(verdicts)
            if maj is None:
                # no strict majority => genuine split => must escalate as DISAGREE (AO-5), never softmax
                if top != "DISAGREE":
                    panel_ok = False
                    rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                             f"panel verdicts {verdicts} have no strict majority (genuine split) but "
                             f"top-level verdict={top!r} — a split must route to DISAGREE (AO-5), not a "
                             "softmaxed/averaged score")
            elif top != maj:
                panel_ok = False
                rep.fail(f"{LABEL_STEM['i16_panel']} (units/{uid})",
                         f"top-level verdict={top!r} != DISCRETE panel majority={maj!r} — the aggregate "
                         "must be the discrete majority (no softmax)")
            if panel_ok:
                rep.ok(f"{LABEL_STEM['i16_panel']} (units/{uid}: {len(members)}-member panel, "
                       f"lenses cover trio, verdict={maj if maj else 'split->DISAGREE'})")
        # (c) loop-until-dry finiteness (schema also bounds it; belt-and-suspenders)
        vr = _as_int(v.get("verify_rounds"))   # BRK-04: normalize float-integral
        if vr is not None:
            if vr < 1 or vr > R_MAX:
                rep.fail(f"{LABEL_STEM['i16_loopdry']} (units/{uid})",
                         f"verify_rounds={vr} outside [1,{R_MAX}] — the loop-until-dry sweep is bounded")
            else:
                rep.ok(f"{LABEL_STEM['i16_loopdry']} (units/{uid}: verify_rounds={vr}<={R_MAX})")

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
            rep.ok(f"{LABEL_STEM['i15_ao6']} (units/{uid})")
        else:
            rep.fail(f"{LABEL_STEM['i15_ao6']} (units/{uid})",
                     "iteration>1 with a prior_feedback echo but changes_made is absent/empty — a "
                     "retry must record >=1 concrete change made in response to the prior verdict (AO-6)")

    # C6 (WP-C): a debrief whose acceptance_self_check marks EVERY criterion met:false while its
    # verify.json verdict is PASS is an internal inconsistency worth surfacing — but NON-GATING: the
    # INDEPENDENT verifier is authoritative (the executor's self-check is advisory), so this is an
    # advisory NOTE, never a FAIL (tests/LIMITATIONS.md documents the intent). Post-hoc/offline.
    for uid in sorted(unit_docs):
        _de6 = unit_docs[uid].get("debrief"); _ve6 = unit_docs[uid].get("verify")
        if not (isinstance(_de6, dict) and isinstance(_ve6, dict)):
            continue
        _asc = _de6.get("acceptance_self_check")
        if (isinstance(_asc, list) and _asc
                and all(isinstance(x, dict) and x.get("met") is False for x in _asc)
                and _ve6.get("verdict") == "PASS" and not args.quiet):
            print(f"  NOTE  {LABEL_STEM['note_selfcheck']} (units/{uid}): debrief acceptance_self_check "
                  f"marks all {len(_asc)} criteri(on/a) met:false but verify verdict=PASS — the "
                  "independent verifier is authoritative (advisory, non-gating; LIMITATIONS.md)")

    # ======================= Bounded Graph Amendments (I17/I18/I19) =======================
    # All three are POST-HOC / OFFLINE predicates over the emitted amendment records + graph.json +
    # fsm-state.json. None gates a transition and none touches LT7 — so BGA PRESERVES the correction-
    # loop termination proof (self-learning-loops.md §2 Claims A-D hold verbatim) and REVISES only the
    # pipeline-level unit-count bound (total units <= N0 + fuel0). They are INERT when amendments/ is
    # absent (empty `amendments`), so every legacy run is byte-for-byte unaffected. (The live guard
    # they deliberately are NOT is the 02/P1 deadlock lesson — mirrors I14/I15/I16.)
    # B1 (WP1) fail-closed trigger: the append-only amendments/A<NN>.json records are the SOLE
    # provenance for an amended graph, so deleting amendments/ must NOT launder the guarantee. Compute
    # whether graph.json / fsm-state.json bear amendment EVIDENCE (revision>1, a non-empty
    # amendments_applied or retired_units, or fuel spent); if so, the block runs EVEN when `amendments`
    # is empty, and the records-required check below FAILs closed. Still post-hoc/offline over emitted
    # artifacts — no live LT7 guard — so BGA PRESERVES the termination proof (Claims A-D verbatim).
    amendment_evidence = False
    _ev_reasons = []
    if graph_doc is not None:
        _rev0 = _as_int(graph_doc.get("revision"))
        if _rev0 is not None and _rev0 > 1:
            amendment_evidence = True; _ev_reasons.append(f"graph.revision={_rev0}>1")
        if graph_doc.get("amendments_applied"):
            amendment_evidence = True; _ev_reasons.append(f"amendments_applied={graph_doc.get('amendments_applied')}")
        if graph_doc.get("retired_units"):
            amendment_evidence = True; _ev_reasons.append("graph.retired_units non-empty")
    _exp0 = fsm.get("expansion") if isinstance(fsm, dict) else None
    if isinstance(_exp0, dict):
        _fi0, _fr0 = _as_int(_exp0.get("fuel_initial")), _as_int(_exp0.get("fuel_remaining"))
        if _fi0 is not None and _fr0 is not None and _fr0 != _fi0:
            amendment_evidence = True; _ev_reasons.append(f"fuel spent ({_fi0}->{_fr0})")

    if amendments or amendment_evidence:
        record_ids = [_rec.get("id") for _fn, _rec in amendments]

        # ---- B1 records-required trigger — evidence with absent/desynced records => FAIL (I18) ----
        if amendment_evidence:
            applied = list(graph_doc.get("amendments_applied", []) or []) if graph_doc is not None else []
            _rev = _as_int(graph_doc.get("revision")) if graph_doc is not None else None
            _probs = []
            if len(amendments) != len(applied):
                _probs.append(f"|records|={len(amendments)} != |amendments_applied|={len(applied)}")
            if _rev is not None and len(amendments) != _rev - 1:
                _probs.append(f"|records|={len(amendments)} != revision-1={_rev - 1}")
            if record_ids != applied:
                _probs.append(f"record ids {record_ids} != amendments_applied {applied}")
            if _probs:
                rep.fail(f"{LABEL_STEM['i18_records_required']}",
                         "amendment evidence present (" + "; ".join(_ev_reasons) + ") but amendment "
                         "records missing/desynced: " + "; ".join(_probs) + " — the append-only "
                         "amendments/A<NN>.json records are the sole provenance and may never be "
                         "deleted or desynced from graph.json")
            else:
                rep.ok(f"{LABEL_STEM['i18_records_required']} ({len(amendments)} record(s) back the amended graph)")

        # ---- I18 amendment bookkeeping (WP3: G1/G2/G3/G12) — record identity + counters + frontier ----
        # Previously dead data: duplicate ids / id↔filename decoupling (G1), graph_revision_after never
        # read (G2), the expansion.amendments_applied integer never cross-checked (G3), and frontier_wave
        # had no teeth (G12). All post-hoc/offline; REVISES the amendment-accounting surface upward.
        if amendments:
            book_ok = True
            _seen_ids = {}
            for _fn, _rec in amendments:
                _rid = _rec.get("id")
                _stem = _fn[:-5] if _fn.endswith(".json") else _fn
                if _rid != _stem:
                    book_ok = False
                    rep.fail(f"{LABEL_STEM['i18_bookkeeping']} (amendments/{_fn})",
                             f"record id {_rid!r} != filename stem {_stem!r} — the id must equal its filename")
                if _rid in _seen_ids:
                    book_ok = False
                    rep.fail(f"{LABEL_STEM['i18_bookkeeping']} (amendments/{_fn})",
                             f"duplicate amendment id {_rid!r} (already used by {_seen_ids[_rid]})")
                else:
                    _seen_ids[_rid] = _fn
            for _idx, (_fn, _rec) in enumerate(amendments):
                _gra = _as_int(_rec.get("graph_revision_after"))
                if _gra != 2 + _idx:
                    book_ok = False
                    rep.fail(f"{LABEL_STEM['i18_bookkeeping']} (amendments/{_rec.get('id')})",
                             f"graph_revision_after={_rec.get('graph_revision_after')!r} != 2 + record_index({_idx}) = {2 + _idx}")
            _expc = fsm.get("expansion") if isinstance(fsm, dict) else None
            if isinstance(_expc, dict) and _expc.get("amendments_applied") is not None:
                _cnt = _as_int(_expc.get("amendments_applied"))
                if _cnt != len(amendments):
                    book_ok = False
                    rep.fail(f"{LABEL_STEM['i18_bookkeeping']}",
                             f"fsm-state.expansion.amendments_applied counter={_cnt} != |records|={len(amendments)}")
            # frontier_wave teeth (G12): every added unit lands at or beyond the record's declared frontier.
            if graph_doc is not None and isinstance(graph_doc.get("waves"), list):
                _wof = {}
                for _w in graph_doc.get("waves", []):
                    for _uid in _w.get("units", []):
                        _wof[_uid] = _as_int(_w.get("wave"))
                for _fn, _rec in amendments:
                    _fw = _as_int(_rec.get("frontier_wave"))
                    if _fw is None:
                        continue
                    for _aid in (_rec.get("units_added", []) or []):
                        _wv = _wof.get(_aid)
                        if _wv is not None and _wv < _fw:
                            book_ok = False
                            rep.fail(f"{LABEL_STEM['i18_bookkeeping']} (amendments/{_rec.get('id')})",
                                     f"added unit {_aid} placed at wave {_wv} < record.frontier_wave {_fw} "
                                     "— an amendment inserts only at/beyond the frontier (internal-consistency check; "
                                     "dispatch timing stays Limitation J)")
            if book_ok:
                rep.ok(f"{LABEL_STEM['i18_bookkeeping']} ({len(amendments)} record(s): ids unique + filename-matched, "
                       "graph_revision_after + counter consistent, frontier respected)")

        # Retired ids: split by source so attribution (below) can compare the two. `retired_ids` (their
        # union) preserves the pre-WP1 semantics every downstream I17 clause keys off.
        retired_from_records = set()
        for _fn, _rec in amendments:
            for _rid in (_rec.get("units_retired", []) or []):
                retired_from_records.add(_rid)
        retired_from_graph = set()
        if graph_doc is not None:
            for _ru in (graph_doc.get("retired_units", []) or []):
                if isinstance(_ru, dict) and _ru.get("id"):
                    retired_from_graph.add(_ru.get("id"))
        retired_ids = retired_from_records | retired_from_graph
        current_unit_ids = ({u.get("id") for u in graph_doc.get("units", [])}
                            if graph_doc is not None else set())

        # ---- I17 amendment reconciliation (WP1: B2/B3) — the unit-set accounting that makes the
        # revised pipeline bound (executed units <= N0 + fuel0) REAL. Without it, amendment ops are
        # taken on faith: units can be smuggled into units[] with no amendment, phantom-added (recorded
        # but never materialized), or phantom-retired (paying fuel to retire ids that never existed).
        # Runs only when a valid graph carries the immutable baseline (schema requires it once
        # revision>1). Offline/post-hoc; REVISES I17 upward (strictly stronger surface). ----
        if graph_doc is not None and graph_doc.get("baseline_units") is not None:
            baseline = set(graph_doc.get("baseline_units", []) or [])
            added_all = set()
            for _fn, _rec in amendments:
                for _aid in (_rec.get("units_added", []) or []):
                    added_all.add(_aid)
            recon_ok = True
            # (1) exact unit-set equation, both directions.
            lhs = current_unit_ids | retired_ids
            rhs = baseline | added_all
            if lhs != rhs:
                recon_ok = False
                _smuggled = sorted(lhs - rhs)    # in graph but neither baseline nor added by a record
                _phantom = sorted(rhs - lhs)     # baseline/added by a record but absent from the graph
                rep.fail(f"{LABEL_STEM['i17_reconcile']}",
                         "unit-set mismatch: (units[] ∪ retired) != (baseline_units ∪ ⋃ units_added) — "
                         f"unaccounted-for in graph {_smuggled}; recorded but missing {_phantom}")
            # (2) retirement existence — a retired id must have existed (baseline or an earlier add),
            #     order-aware so add-then-retire within the same run is legitimate.
            _existed = set(baseline)
            for _fn, _rec in amendments:
                for _rid in (_rec.get("units_retired", []) or []):
                    if _rid not in _existed:
                        recon_ok = False
                        rep.fail(f"{LABEL_STEM['i17_reconcile']} (amendments/{_rec.get('id')})",
                                 f"retires {_rid} which never existed (not in baseline_units nor any "
                                 "earlier amendment's units_added) — a phantom retirement inflates the bound")
                for _aid in (_rec.get("units_added", []) or []):
                    _existed.add(_aid)
            # (3) disjointness — a retired id must be GONE from the current units[].
            _still = sorted(retired_ids & current_unit_ids)
            if _still:
                recon_ok = False
                rep.fail(f"{LABEL_STEM['i17_reconcile']}",
                         f"retired id(s) {_still} still present in units[] — a retired unit must be "
                         "removed from the current graph (else N <= N0 + fuel0 has no floor)")
            # (4) attribution — graph.retired_units[].id == ⋃ records' units_retired, both directions.
            if retired_from_graph != retired_from_records:
                recon_ok = False
                rep.fail(f"{LABEL_STEM['i17_reconcile']}",
                         f"graph.retired_units ids {sorted(retired_from_graph)} != ⋃ amendment "
                         f"units_retired {sorted(retired_from_records)} — retirement bookkeeping desynced")
            if recon_ok:
                rep.ok(f"{LABEL_STEM['i17_reconcile']} (units[] ∪ retired == baseline ∪ adds; "
                       f"{len(baseline)} baseline + {len(added_all)} added)")

        # ---- I17 frozen executed prefix — amendments touch only the not-yet-started future ----
        # (1) a retired unit dir may hold at most brief.md/brief.json (no debrief/verify — a retired
        #     unit must never have executed); (2) every debriefed unit dir's id is in the CURRENT
        #     graph units[] (executed work is never orphaned by an amendment); (3) a retired id never
        #     reappears in a later units_added (retired ids are never reused); (4) a retired id in
        #     fsm-state.units[] carries status 'retired'.
        i17_ok = True
        for rid in sorted(retired_ids):
            rdir = os.path.join(units_dir, rid)
            if os.path.isdir(rdir):
                for f in sorted(os.listdir(rdir)):
                    if f not in ("brief.md", "brief.json"):
                        i17_ok = False
                        rep.fail(f"{LABEL_STEM['i17_frozen']} (amendments/{rid})",
                                 f"retired unit dir contains {f!r} — a retired unit may keep at most "
                                 "brief.md/brief.json (it must never have executed: no debrief/verify)")
        if graph_doc is not None:
            for uid in sorted(unit_dirs_with_debrief):
                if uid not in current_unit_ids:
                    i17_ok = False
                    rep.fail(f"{LABEL_STEM['i17_frozen']} (amendments/{uid})",
                             f"unit {uid} has a debrief but is absent from the amended graph.json units[] "
                             "— executed work must never be orphaned by an amendment")
        # (3) order-aware: an id may be added then later retired (legitimate), but a retired id must
        # never REAPPEAR in a LATER amendment's units_added. `amendments` is in sorted-filename =
        # chronological order (A01, A02, ...), so accumulate retired-by-earlier and check each add
        # against it (an order-insensitive check would false-flag the add-then-cancel case).
        retired_so_far = set()
        for _fn, _rec in amendments:
            for _aid in (_rec.get("units_added", []) or []):
                if _aid in retired_so_far:
                    i17_ok = False
                    rep.fail(f"{LABEL_STEM['i17_frozen']} (amendments/{_rec.get('id')})",
                             f"amendment re-adds retired unit id {_aid} — a retired id is never reused")
            for _rid in (_rec.get("units_retired", []) or []):
                retired_so_far.add(_rid)
        if fsm and isinstance(fsm.get("units"), list):
            for _u in fsm["units"]:
                if isinstance(_u, dict) and _u.get("unit_id") in retired_ids and _u.get("status") != "retired":
                    i17_ok = False
                    rep.fail(f"{LABEL_STEM['i17_frozen']} (amendments/{_u.get('unit_id')})",
                             f"retired unit {_u.get('unit_id')} has fsm status {_u.get('status')!r} != 'retired'")
        if i17_ok:
            rep.ok(f"{LABEL_STEM['i17_frozen_ok']} ({len(retired_ids)} retired id(s); no executed unit touched)")

        # ---- I17 frozen-content anchor (WP4: B5) — an EXECUTED unit's current graph entry must still
        # match its immutable brief.json (the contract written at dispatch). A post-execution rewrite of
        # an executed unit's title/wave/deps/persona/tags/acceptance_criteria in graph.json is caught.
        # `goal` and `est_footprint_tokens` are NOT brief-carried (the brief has budget_tokens, a distinct
        # ceiling), so they remain attested — Limitation J covers the residual dispatch-timing surface.
        # Offline/post-hoc; REVISES I17 upward. ----
        if graph_doc is not None:
            _gunits = {u.get("id"): u for u in graph_doc.get("units", [])}
            _gwave = {}
            for _w in (graph_doc.get("waves") or []):
                for _uid in _w.get("units", []):
                    _gwave[_uid] = _as_int(_w.get("wave"))
            for uid in sorted(unit_dirs_with_debrief):
                b = unit_docs.get(uid, {}).get("brief")
                gu = _gunits.get(uid)
                if not isinstance(b, dict) or not isinstance(gu, dict):
                    continue                       # no brief (G-brief already FAILs) or unit not in graph (I17 orphan)
                _mism = []
                if gu.get("title") != b.get("title"):
                    _mism.append(f"title {gu.get('title')!r} != brief {b.get('title')!r}")
                _bw = _as_int(b.get("wave"))
                if _gwave.get(uid) is not None and _bw is not None and _gwave.get(uid) != _bw:
                    _mism.append(f"wave {_gwave.get(uid)} != brief {_bw}")
                if sorted(gu.get("deps", []) or []) != sorted(b.get("depends_on", []) or []):
                    _mism.append(f"deps {sorted(gu.get('deps', []) or [])} != brief depends_on {sorted(b.get('depends_on', []) or [])}")
                if gu.get("executor_persona") != b.get("persona"):
                    _mism.append(f"executor_persona {gu.get('executor_persona')!r} != brief persona {b.get('persona')!r}")
                if sorted(gu.get("tags", []) or []) != sorted(b.get("tags", []) or []):
                    _mism.append(f"tags {sorted(gu.get('tags', []) or [])} != brief {sorted(b.get('tags', []) or [])}")
                if list(gu.get("acceptance_criteria", []) or []) != list(b.get("acceptance_criteria", []) or []):
                    _mism.append("acceptance_criteria differ from brief")
                if _mism:
                    rep.fail(f"{LABEL_STEM['i17_anchor']} (units/{uid})",
                             "executed unit's graph entry diverges from its frozen brief.json: " + "; ".join(_mism)
                             + " — an amendment may not modify/re-wave/rewire an executed unit")
                else:
                    rep.ok(f"{LABEL_STEM['i17_anchor']} (units/{uid}: graph entry matches frozen brief)")

        # ---- I18 fuel bound — the termination-preserving budget (mirrors retries<=2 structurally) ----
        # fuel_remaining == fuel_initial - Σ fuel_cost >= 0; each record's fuel_cost == max(1,
        # |units_added| - |units_retired|); graph.json.revision == 1 + |records|; graph.json.
        # amendments_applied lists exactly the record ids in order. Amendments present with NO
        # expansion object => FAIL (BGA disabled means no amendments allowed).
        expansion = fsm.get("expansion") if isinstance(fsm, dict) else None
        if not isinstance(expansion, dict):
            rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                     "amendments/ present but no valid fsm-state.json `expansion` object — the fuel "
                     "budget must be seeded (Phase 4) before any amendment (0/absent expansion = BGA off)")
        else:
            i18_ok = True
            fuel_initial = _as_int(expansion.get("fuel_initial"))
            fuel_remaining = _as_int(expansion.get("fuel_remaining"))
            total_cost = 0
            for _fn, _rec in amendments:
                fc = _as_int(_rec.get("fuel_cost"))
                added = len(_rec.get("units_added", []) or [])
                retired = len(_rec.get("units_retired", []) or [])
                expect = max(1, added - retired)
                if fc is None:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']} (amendments/{_rec.get('id')})",
                             f"fuel_cost {_rec.get('fuel_cost')!r} is not an integer")
                    continue
                total_cost += fc
                if fc != expect:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']} (amendments/{_rec.get('id')})",
                             f"fuel_cost={fc} != max(1, |units_added|={added} - |units_retired|={retired})={expect}")
            if fuel_initial is None or fuel_remaining is None:
                i18_ok = False
                rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                         f"expansion.fuel_initial/fuel_remaining must be integers (got "
                         f"{expansion.get('fuel_initial')!r}/{expansion.get('fuel_remaining')!r})")
            else:
                if fuel_remaining != fuel_initial - total_cost:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                             f"fuel_remaining={fuel_remaining} != fuel_initial={fuel_initial} - "
                             f"Σ fuel_cost={total_cost} = {fuel_initial - total_cost}")
                if fuel_remaining < 0:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']}", f"fuel_remaining={fuel_remaining} < 0 (fuel exhausted/overrun)")

            # ---- Fuel tamper-evidence (WP2: B4) — immutable seed anchor + per-record fuel chain ----
            # The old I18 arithmetic reads expansion.fuel_initial at face value, so widening it mid-run
            # (fuel_initial 2->3 to buy a 3rd amendment) passes. Anchor it to the immutable
            # graph.json.fuel_initial (written once at T6), and chain each record's fuel_before/fuel_after
            # from fuel_initial to fuel_remaining so a spoofed seed or a broken link is caught. REVISES
            # I18 upward; still post-hoc/offline (no LT7 guard) => termination PRESERVED.
            if graph_doc is not None and graph_doc.get("fuel_initial") is not None:
                g_fi = _as_int(graph_doc.get("fuel_initial"))
                if fuel_initial is not None and g_fi is not None and fuel_initial != g_fi:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                             f"expansion.fuel_initial={fuel_initial} != immutable graph.json.fuel_initial={g_fi} "
                             "— the fuel seed is fixed at T6; widening it mid-run is tamper-evident (B4)")
            _prev_after = fuel_initial   # A01.fuel_before must equal the seed
            for _fn, _rec in amendments:
                _fb = _as_int(_rec.get("fuel_before"))
                _fa = _as_int(_rec.get("fuel_after"))
                _fc = _as_int(_rec.get("fuel_cost"))
                if _fb is None or _fa is None:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']} (amendments/{_rec.get('id')})",
                             "fuel_before/fuel_after must be integers — the fuel chain is unverifiable")
                    _prev_after = None
                    continue
                if _prev_after is not None and _fb != _prev_after:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']} (amendments/{_rec.get('id')})",
                             f"fuel chain break: fuel_before={_fb} != prior fuel_after/fuel_initial={_prev_after}")
                if _fc is not None and _fa != _fb - _fc:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']} (amendments/{_rec.get('id')})",
                             f"fuel chain break: fuel_after={_fa} != fuel_before={_fb} - fuel_cost={_fc} = {_fb - _fc}")
                _prev_after = _fa
            if amendments and _prev_after is not None and fuel_remaining is not None and _prev_after != fuel_remaining:
                i18_ok = False
                rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                         f"fuel chain break: last amendment fuel_after={_prev_after} != "
                         f"expansion.fuel_remaining={fuel_remaining}")

            expect_rev = 1 + len(amendments)
            record_ids = [_rec.get("id") for _fn, _rec in amendments]
            if graph_doc is None:
                i18_ok = False
                rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                         "amendments present but no valid graph.json to carry revision/amendments_applied")
            else:
                revision = _as_int(graph_doc.get("revision"))
                if revision != expect_rev:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                             f"graph.json.revision={graph_doc.get('revision')!r} != 1 + |amendment records|={expect_rev}")
                applied = graph_doc.get("amendments_applied")
                if applied != record_ids:
                    i18_ok = False
                    rep.fail(f"{LABEL_STEM['i18_fuel_bound']}",
                             f"graph.json.amendments_applied={applied} != amendment record ids in order {record_ids}")
            if i18_ok:
                rep.ok(f"{LABEL_STEM['i18_fuel_bound']} ({len(amendments)} amendment(s); Σ fuel_cost={total_cost}; "
                       f"fuel {fuel_initial}->{fuel_remaining}; revision={expect_rev})")

        # ---- I19 amendment scope — DoD traceability + human-gate policy + split coverage, per record ----
        # * add_units/split_unit => dod_refs non-empty AND each element verbatim ∈ clarifications.json
        #   .definition_of_done (a decidable string-membership check — the semantic backstop is the
        #   verifier/critique pass; state-machine.md §5 honest boundary).
        # * scope_change==true => human_gate==true; kind==cancel_unit => human_gate==true (the human-
        #   gate POLICY — enforced here, not in amendment.schema.json, so an ungated cancel/scope-change
        #   reaches this check and fails with the I19 label; presence-checked attestation, not proof a
        #   human decided — §5 Limitation pattern, like signoff_confirmed).
        # * split_unit => children tags ⊇ retired_snapshot tags AND every snapshot acceptance criterion
        #   is a criteria_map key mapping to >=1 existing child id (scope-preserving by construction).
        dod = set()
        _cl = docs.get("clarifications")
        if isinstance(_cl, dict):
            dod = {x for x in _cl.get("definition_of_done", []) if isinstance(x, str)}
        cur_units = ({u.get("id"): u for u in graph_doc.get("units", [])}
                     if graph_doc is not None else {})
        for _fn, _rec in amendments:
            aid = _rec.get("id")
            kind = _rec.get("kind")
            rec_ok = True
            if _rec.get("scope_change") is True and _rec.get("human_gate") is not True:
                rec_ok = False
                rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                         "scope_change==true requires human_gate==true (a scope change is human-gated)")
            if kind == "cancel_unit" and _rec.get("human_gate") is not True:
                rec_ok = False
                rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                         "cancel_unit requires human_gate==true (deleting planned scope is always human-gated)")
            # dod_refs traceability — keyed on units_added being non-empty REGARDLESS of kind (WP3
            # belt-and-braces: a relabeled kind that keeps units_added can no longer dodge the DoD trace;
            # the schema kind-closure already forbids units_added on add_edges/cancel_unit, so this is
            # defense-in-depth for any schema-valid record that materializes units).
            if kind in ("add_units", "split_unit") or _rec.get("units_added"):
                refs = _rec.get("dod_refs") or []
                if not refs:
                    rec_ok = False
                    rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                             f"{kind} adds units but carries no dod_refs tracing to definition_of_done")
                untraced = sorted(r for r in refs if r not in dod)
                if untraced:
                    rec_ok = False
                    rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                             f"dod_refs {untraced} not present verbatim in clarifications.json."
                             f"definition_of_done {sorted(dod)}")
            if kind == "split_unit":
                children = _rec.get("units_added", []) or []
                # WP3: the snapshot must be EXACTLY the retired unit(s) (no fake/bare padding).
                # WP-A/B1: only string ids (a non-string/unhashable id would crash the set comprehension;
                # the schema now pins id:string, so this is belt-and-braces for degraded/no-schema mode).
                _snap_ids = {s.get("id") for s in (_rec.get("retired_snapshot", []) or [])
                             if isinstance(s, dict) and isinstance(s.get("id"), str)}
                _ret_set = set(_rec.get("units_retired", []) or [])
                if _snap_ids != _ret_set:
                    rec_ok = False
                    rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                             f"retired_snapshot ids {sorted(x for x in _snap_ids if x)} != units_retired "
                             f"{sorted(_ret_set)} — the snapshot must be exactly the retired unit(s)")
                child_tags = set()
                for c in children:
                    if c in cur_units:
                        _ct = cur_units[c].get("tags", [])   # WP-A/B1: tolerate a non-list tags (graph.schema pins it; belt-and-braces)
                        if isinstance(_ct, list):
                            child_tags |= {t for t in _ct if isinstance(t, str)}
                snap_tags, snap_crits = set(), []
                for s in (_rec.get("retired_snapshot", []) or []):
                    if isinstance(s, dict):
                        # WP-A/B1: guard non-list tags/acceptance_criteria — the schema now pins these to
                        # array<string> (both backends), so a wrong-typed snapshot is DROPPED before it
                        # reaches here; these isinstance guards are belt-and-braces so an unforeseen shape
                        # in degraded/no-schema mode FAILs cleanly instead of raising a TypeError traceback.
                        _st = s.get("tags", [])
                        if isinstance(_st, list):
                            snap_tags |= {t for t in _st if isinstance(t, str)}
                        _sc = s.get("acceptance_criteria", [])
                        if isinstance(_sc, list):
                            snap_crits += [c for c in _sc if isinstance(c, str)]
                missing_tags = sorted(snap_tags - child_tags)
                if missing_tags:
                    rec_ok = False
                    rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                             f"split children tags {sorted(child_tags)} do not cover parent tags "
                             f"(missing {missing_tags}) — children collectively must carry ⊇ parent tags")
                cmap = _rec.get("criteria_map") or {}
                _children_set = set(children)
                for crit in snap_crits:
                    targets = cmap.get(crit)
                    if not targets:
                        rec_ok = False
                        rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                                 f"parent criterion {crit!r} is not a criteria_map key — every parent "
                                 "acceptance criterion must map to >=1 child")
                        continue
                    # WP3: targets must be the split's OWN children (units_added), not any current unit
                    # (state-machine.md §3.6 / schema description / SKILL all say "child").
                    _noncild = [t for t in targets if t not in _children_set]
                    if _noncild:
                        rec_ok = False
                        rep.fail(f"{LABEL_STEM['i19_scope']} (amendments/{aid})",
                                 f"criteria_map[{crit!r}] targets {_noncild} are not split children "
                                 f"(units_added {sorted(_children_set)}) — a parent criterion maps only to its own children")
            if rec_ok:
                rep.ok(f"{LABEL_STEM['i19_scope']} (amendments/{aid}: dod-traced, gated, split-covered)")

    # ---- I20 per-unit DoD binding (dod_refs) — adoption closure + verbatim membership + brief mirror ----
    # WP-1 (guardrails 1.8.0): generalizes I19's verbatim set-membership from amendment RECORDS to
    # graph.json units[]. Adoption/presence-triggered: a run where NO graph unit carries the dod_refs
    # KEY emits nothing (archived pre-adoption runs stay green — pure presence-triggering, never a
    # validator_version read; state-machine.md §5 version-skew posture). Once ANY unit adopts:
    #   * CLOSURE — every unit must carry the key ("some bound, some not" is the forgot-vs-bound
    #     ambiguity this invariant exists to kill);
    #   * MEMBERSHIP (always when present) — each ref must be verbatim ∈ clarifications.json
    #     .definition_of_done (decidable string membership; the semantic backstop is the
    #     verifier/critique pass — state-machine.md §5 honest boundary, exactly like I19);
    #   * BRIEF MIRROR — units/<id>/brief.json (when it exists and parses) must carry dod_refs
    #     sorted-equal to the graph unit's (the brief is the frozen dispatch contract; drift means
    #     the executed contract diverged from the plan's binding).
    # Amendment interplay: I19 keeps governing amendment RECORDS' dod_refs untouched; units an
    # amendment adds land in graph.json.units[] and are therefore I20-bound under adoption — one
    # standard, zero I19 edits. Offline post-hoc predicate over emitted artifacts: gates no FSM
    # transition, no LT7 guard — correction-loop termination (Claim D) untouched.
    _i20_clar = docs.get("clarifications")
    if graph_doc is not None and isinstance(_i20_clar, dict):
        _i20_units = [u for u in (graph_doc.get("units") or []) if isinstance(u, dict)]
        # GV-16 membership-union (socratic-guardrail 1.10.0; I40-4): a revise_anchors edit/remove
        # freezes the executed prefix (I17), so an executed unit's dod_refs may still cite text a
        # later amendment retired. Accept `current ∪ anchors_retired[].prior_text` so the frozen
        # prefix stays valid; a unit ADDED after the retirement citing retired text is caught by the
        # I40-4 ordering check (offline, no LT7 guard — PRESERVES). REVISES the I20 membership set.
        _i20_dset = ({x for x in _i20_clar.get("definition_of_done", []) if isinstance(x, str)}
                     | {r.get("prior_text") for r in (_i20_clar.get("anchors_retired") or [])
                        if isinstance(r, dict) and r.get("list") == "definition_of_done"
                        and isinstance(r.get("prior_text"), str)})
        _i20_bound = [u for u in _i20_units if "dod_refs" in u]
        if _i20_bound:                                                # ADOPTION
            _i20_failures = []                   # (label, msg) pairs — explicit tracking
            _i20_unbound = sorted(str(u.get("id", "?")) for u in _i20_units if "dod_refs" not in u)
            if _i20_unbound:                                          # CLOSURE
                _i20_failures.append((f"{LABEL_STEM['unit_dod_refs']}",
                                      f"adoption closure: units missing dod_refs: {_i20_unbound}"))
            for u in _i20_bound:                 # MEMBERSHIP (always when present)
                _uid = u.get("id", "?")
                refs = u.get("dod_refs")
                refs = [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []
                miss = sorted(r for r in refs if r not in _i20_dset)
                if miss:
                    _i20_failures.append((f"{LABEL_STEM['unit_dod_refs']} (units/{_uid})",
                                          f"not verbatim in definition_of_done: {miss}"))
                bdoc = None                      # BRIEF MIRROR — parse directly (a schema-invalid
                _bp = os.path.join(units_dir, str(_uid), "brief.json")   # brief still gets the drift
                if os.path.exists(_bp):                                  # check; its schema FAIL
                    try:                                                 # fires separately above)
                        _cand = load_json(_bp)
                    except Exception:
                        _cand = None
                    if isinstance(_cand, dict):
                        bdoc = _cand
                if bdoc is not None:
                    if "dod_refs" not in bdoc:
                        _i20_failures.append((f"{LABEL_STEM['unit_dod_refs']} (units/{_uid})",
                                              "brief mirror missing: graph unit is bound but "
                                              "brief.json carries no dod_refs"))
                    else:
                        _brefs = bdoc.get("dod_refs")
                        _bnorm = (sorted(x for x in _brefs if isinstance(x, str))
                                  if isinstance(_brefs, list) else None)
                        if _bnorm != sorted(refs):
                            _i20_failures.append((f"{LABEL_STEM['unit_dod_refs']} (units/{_uid})",
                                                  f"brief mirror drift: brief.dod_refs {_brefs!r} != "
                                                  f"graph unit dod_refs {sorted(refs)!r}"))
            for _lbl, _msg in _i20_failures:
                rep.fail(_lbl, _msg)
            if not _i20_failures:
                rep.ok(f"{LABEL_STEM['unit_dod_refs']} ({len(_i20_bound)}/{len(_i20_units)} unit(s) "
                       "bound; refs verbatim in definition_of_done; brief mirrors consistent)")

    # ---- I21 per-unit non-goal binding (non_goal_refs) — adoption closure + membership + brief mirror ----
    # WP-2 (guardrails 1.8.0): structurally identical to I20 over clarifications.json.non_goals, with
    # ONE deliberate difference — non_goal_refs MAY be [] ("no non-goal applies to this unit" is an
    # explicit, distinguishable statement), while an ABSENT key under adoption is a closure FAIL:
    # explicit-none vs forgot becomes mechanical. Adoption = any unit carrying the non_goal_refs KEY;
    # closure = every unit carries the KEY (possibly []); membership + brief mirror as I20. Same
    # posture: presence-triggered (zero-adoption runs emit nothing), no validator_version read,
    # offline post-hoc, gates no FSM transition, no LT7 guard — termination (Claim D) untouched.
    if graph_doc is not None and isinstance(_i20_clar, dict):
        _i21_units = [u for u in (graph_doc.get("units") or []) if isinstance(u, dict)]
        # GV-16 membership-union (I40-4): current non_goals ∪ retired prior_text (see I20 above).
        _i21_ngset = ({x for x in _i20_clar.get("non_goals", []) if isinstance(x, str)}
                      | {r.get("prior_text") for r in (_i20_clar.get("anchors_retired") or [])
                         if isinstance(r, dict) and r.get("list") == "non_goals"
                         and isinstance(r.get("prior_text"), str)})
        _i21_bound = [u for u in _i21_units if "non_goal_refs" in u]
        if _i21_bound:                                                # ADOPTION
            _i21_failures = []                   # (label, msg) pairs — explicit tracking
            _i21_unbound = sorted(str(u.get("id", "?")) for u in _i21_units if "non_goal_refs" not in u)
            if _i21_unbound:                                          # CLOSURE (key may map to [])
                _i21_failures.append((f"{LABEL_STEM['unit_non_goal_refs']}",
                                      f"adoption closure: units missing the non_goal_refs key: "
                                      f"{_i21_unbound} ([] is the explicit none-applicable statement)"))
            for u in _i21_bound:                 # MEMBERSHIP (always when present; [] passes vacuously)
                _uid = u.get("id", "?")
                refs = u.get("non_goal_refs")
                refs = [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []
                miss = sorted(r for r in refs if r not in _i21_ngset)
                if miss:
                    _i21_failures.append((f"{LABEL_STEM['unit_non_goal_refs']} (units/{_uid})",
                                          f"not verbatim in non_goals: {miss}"))
                bdoc = None                      # BRIEF MIRROR — same direct-parse posture as I20
                _bp = os.path.join(units_dir, str(_uid), "brief.json")
                if os.path.exists(_bp):
                    try:
                        _cand = load_json(_bp)
                    except Exception:
                        _cand = None
                    if isinstance(_cand, dict):
                        bdoc = _cand
                if bdoc is not None:
                    if "non_goal_refs" not in bdoc:
                        _i21_failures.append((f"{LABEL_STEM['unit_non_goal_refs']} (units/{_uid})",
                                              "brief mirror missing: graph unit carries the key but "
                                              "brief.json carries no non_goal_refs"))
                    else:
                        _brefs = bdoc.get("non_goal_refs")
                        _bnorm = (sorted(x for x in _brefs if isinstance(x, str))
                                  if isinstance(_brefs, list) else None)
                        if _bnorm != sorted(refs):
                            _i21_failures.append((f"{LABEL_STEM['unit_non_goal_refs']} (units/{_uid})",
                                                  f"brief mirror drift: brief.non_goal_refs {_brefs!r} != "
                                                  f"graph unit non_goal_refs {sorted(refs)!r}"))
            for _lbl, _msg in _i21_failures:
                rep.fail(_lbl, _msg)
            if not _i21_failures:
                rep.ok(f"{LABEL_STEM['unit_non_goal_refs']} ({len(_i21_bound)}/{len(_i21_units)} unit(s) "
                       "carry the key; refs verbatim in non_goals; brief mirrors consistent)")

    # ---- Family B (guardrails 1.8.0, WP-3..WP-6): I22 guardrail compliance · I23 closure ----
    # ---- · I24 register floor · I25 resolution present --------------------------------------
    # All four are OFFLINE post-hoc predicates over emitted artifacts (no FSM edge or guard is
    # touched — correction-loop termination Claim D unaffected), decidable at string level,
    # stdlib-only, with NO validator_version branching. Firing posture per APPROVED_PLAN §4:
    #   I22/I23 — adoption-gated on the NEW artifacts (a guardrail_compliance block in a
    #     verify.json; dod_refs / the block at P8) ⇒ archived runs are silent;
    #   I24/I25 — artifact-driven on POSITIVE evidence (the I-dod trigger-family precedent):
    #     an archived run CAN newly flag (empty register after structural work / fake-resolved
    #     material item) — expected §5 version skew, never a reason to edit the archive.
    # Shared hoists (plan WP-4: "same map I22 builds — hoist and share one helper"):
    #   _i22_verifies — uid -> RAW-parsed units/<uid>/verify.json carrying a "verdict" key.
    #     Raw parse, not unit_docs: a parseable-but-schema-invalid verify already FAILs at the
    #     schema layer above, but the compliance predicates must still see its verdict/rows —
    #     fail-closed (the I20/I21 brief-mirror posture).
    #   _i22_clar — the schema-VALID clarifications doc (membership sets for I22/I23).
    #   _i22_clar_raw — the RAW-parsed clarifications.json (I24/I25 are backstops and must run
    #     even when the doc is schema-invalid; I25 especially: the WP-6 schema conditional
    #     makes I25's trip doc schema-INVALID, so docs['clarifications'] is None exactly when
    #     the defect exists — only the raw parse can mirror it).
    _i22_verifies = {}
    for _i22_uid in sorted(unit_subdirs):
        _i22_vp = os.path.join(units_dir, _i22_uid, "verify.json")
        if os.path.exists(_i22_vp):
            try:
                _i22_vdoc = load_json(_i22_vp)
            except Exception:
                _i22_vdoc = None
            if isinstance(_i22_vdoc, dict) and "verdict" in _i22_vdoc:
                _i22_verifies[_i22_uid] = _i22_vdoc
    _i22_clar = docs.get("clarifications")
    _i22_clar_raw = None
    _i22_cp = os.path.join(rd, "clarifications.json")
    if os.path.exists(_i22_cp):
        try:
            _i22_clar_raw = load_json(_i22_cp)
        except Exception:
            _i22_clar_raw = None

    # ---- I22 verify-time guardrail-compliance block (WP-3) ----
    # Honesty boundary (labeled the same way in spec/invariants.json): presence, verbatim
    # membership, coverage, and the violated+PASS clause are MECHANICAL; whether a `respected`
    # row is TRUE stays verifier attestation (presence-not-genuineness). ADOPTION = any
    # verdict-bearing verify carries the block; CLOSURE then requires every verdict-bearing
    # verify to carry it (verdictless verifies are not bound — partial runs mid-wave stay
    # incremental). The one decidable semantic clause mechanizes SKILL.md's "a delivered
    # non-goal is a FAIL, not a bonus": a violated row on a PASS verdict is a defect.
    # GV-16 membership-union (I40-4): current non_goals ∪ retired prior_text (frozen-prefix rule).
    _i22_ngset = (({x for x in _i22_clar.get("non_goals") or [] if isinstance(x, str)}
                   | {r.get("prior_text") for r in (_i22_clar.get("anchors_retired") or [])
                      if isinstance(r, dict) and r.get("list") == "non_goals"
                      and isinstance(r.get("prior_text"), str)})
                  if isinstance(_i22_clar, dict) else set())
    _i22_gunits = ([u for u in (graph_doc.get("units") or []) if isinstance(u, dict)]
                   if graph_doc is not None else [])
    _i22_withblk = {u for u, v in _i22_verifies.items() if "guardrail_compliance" in v}
    if _i22_withblk:                                                # ADOPTION
        _i22_lacking = sorted(set(_i22_verifies) - _i22_withblk)
        if _i22_lacking:                                            # CLOSURE
            rep.fail(f"{LABEL_STEM['guardrail_compliance']}",
                     f"adoption closure: verifies missing the block: {_i22_lacking}")
    for _i22_uid in sorted(_i22_withblk):
        _i22_v = _i22_verifies[_i22_uid]
        # Raw-parse posture ⇒ rows can be ANY shape here (a schema-invalid verify still FAILs
        # at the schema layer above, but must not crash this predicate): list-guard the block,
        # dict-guard each row, and treat a non-string non_goal as fail-closed non-membership
        # (never hash a potentially-unhashable value into the set).
        _i22_gc = _i22_v.get("guardrail_compliance")
        _i22_rows = ([r for r in _i22_gc if isinstance(r, dict)]
                     if isinstance(_i22_gc, list) else [])
        _i22_bad = [r.get("non_goal") for r in _i22_rows
                    if not isinstance(r.get("non_goal"), str)
                    or r.get("non_goal") not in _i22_ngset]
        if _i22_bad:                                                # MEMBERSHIP
            rep.fail(f"{LABEL_STEM['guardrail_compliance']} (units/{_i22_uid})",
                     f"rows name strings not verbatim in non_goals: {_i22_bad}")
        if (_i22_v.get("verdict") == "PASS"
                and any(r.get("status") == "violated" for r in _i22_rows)):
            rep.fail(f"{LABEL_STEM['guardrail_compliance']} (units/{_i22_uid})",  # DECIDABLE BITE
                     "a violated non-goal row on a PASS verdict: a delivered non-goal is "
                     "a FAIL, not a bonus")
        _i22_unit = next((u for u in _i22_gunits if u.get("id") == _i22_uid), None)
        if _i22_unit is not None and "non_goal_refs" in _i22_unit:  # COVERAGE (WP-2 synergy)
            _i22_covered = {r.get("non_goal") for r in _i22_rows
                            if isinstance(r.get("non_goal"), str)}
            _i22_uncov = [g for g in (_i22_unit.get("non_goal_refs") or [])
                          if g not in _i22_covered]
            if _i22_uncov:
                rep.fail(f"{LABEL_STEM['guardrail_compliance']} (units/{_i22_uid})",
                         f"unit's non_goal_refs lack an attestation row: {_i22_uncov}")

    # ---- I23 Phase-8 DoD / non-goal closure (WP-4) ----
    # Mechanical counterpart of the synthesis obligations, double-gated: (gate 1) I10's phase
    # condition VERBATIM (post-hoc fsm-state inspection exactly as I10 does — not a transition
    # guard, so Claim D holds); (gate 2) adoption of the WP-1 / WP-3 artifacts respectively.
    # Iterates GRAPH units, never dirs (BRK-02). Retired units are absent from
    # graph.json.units[] and so correctly contribute no coverage. Violated-row policing at
    # closure is unnecessary: I10 forces all units PASS at DONE and I22 already forbids
    # violated+PASS.
    if phase in ("P8_SYNTHESIS", "DONE") and unit_subdirs:
        _i23_units = ([u for u in (graph_doc.get("units") or []) if isinstance(u, dict)]
                      if graph_doc is not None else [])
        _i23_verifies = {}                # uid -> parsed verify.json carrying a "verdict"
        for _i23_u in _i23_units:         # (the I22 map, restricted to graph units)
            _i23_uid = _i23_u.get("id")
            if isinstance(_i23_uid, str) and _i23_uid in _i22_verifies:
                _i23_verifies[_i23_uid] = _i22_verifies[_i23_uid]
        _i23_pass_ids = sorted(u for u, v in _i23_verifies.items()
                               if v.get("verdict") == "PASS")
        _i23_pass_units = [u for u in _i23_units if u.get("id") in _i23_pass_ids]
        if any("dod_refs" in u for u in _i23_units):                      # WP-1 adoption
            _i23_covered = set()
            for _i23_u in _i23_pass_units:
                _i23_covered.update(x for x in (_i23_u.get("dod_refs") or [])
                                    if isinstance(x, str))
            _i23_dod = ((_i22_clar.get("definition_of_done") or [])
                        if isinstance(_i22_clar, dict) else [])
            _i23_unmet = [d for d in _i23_dod if d not in _i23_covered]
            if _i23_unmet:
                rep.fail(f"{LABEL_STEM['p8_closure']}",
                         f"DoD items referenced by no PASS-verified unit: {_i23_unmet}")
        if any("guardrail_compliance" in v for v in _i23_verifies.values()):  # WP-3 adoption
            _i23_att = set()
            for _i23_uid in _i23_pass_ids:
                _i23_gc = _i23_verifies[_i23_uid].get("guardrail_compliance")
                for _i23_r in (_i23_gc if isinstance(_i23_gc, list) else []):
                    if (isinstance(_i23_r, dict)
                            and _i23_r.get("status") in ("respected", "not-applicable")
                            and isinstance(_i23_r.get("non_goal"), str)):
                        _i23_att.add(_i23_r.get("non_goal"))
            _i23_ng = ((_i22_clar.get("non_goals") or [])
                       if isinstance(_i22_clar, dict) else [])
            _i23_unatt = [g for g in _i23_ng if g not in _i23_att]
            if _i23_unatt:
                rep.fail(f"{LABEL_STEM['p8_closure']}",
                         "non-goals with no respected/not-applicable attestation from any "
                         f"PASS unit: {_i23_unatt}")

    # ---- I24 artifact-driven ambiguity-register floor (WP-5) ----
    # I-dod trigger-set reused VERBATIM (union of cartography / graph / units / synthesis;
    # learnings.json stays EXCLUDED — the Phase-0.5 deadlock). Validator-only floor: NO schema
    # minItems (a schema floor would hard-fail legitimate mid-dialogue pure-P2 authoring and
    # make archived empty-register docs schema-invalid, cascading into the I8/I-dod extraction
    # paths instead of one legible finding). "No ambiguities found" is recorded as an ordinary
    # register item, so non-emptiness IS the none-found attestation form. I8 stays untouched:
    # it keeps judging recorded content; I24 only guarantees there is content to judge.
    _i24_trigger = (
        docs.get("cartography") is not None
        or os.path.exists(os.path.join(rd, "CARTOGRAPHY.md"))
        or graph_json_exists
        or graph_md_exists
        or bool(unit_subdirs)
        or os.path.exists(os.path.join(rd, "SYNTHESIS.md"))
    )
    if _i24_trigger and _i22_clar_raw is not None:
        _i24_reg = (_i22_clar_raw.get("ambiguity_register")
                    if isinstance(_i22_clar_raw, dict) else None)
        if not (isinstance(_i24_reg, list) and len(_i24_reg) >= 1):
            rep.fail(f"{LABEL_STEM['register_floor']}",
                     "ambiguity_register is empty after structural work exists; "
                     "record real ambiguities or an explicit none-found item")

    # ---- I25 resolution required on resolved material items (WP-6) ----
    # Validator MIRROR of the WP-6 schema conditional (the I15 schema+backstop precedent) —
    # reads the RAW parse (see the _i22_clar_raw hoist note). The .strip() bar also catches
    # " " — stricter than the schema's minLength:1 (the G11/fail_blank_actionable precedent).
    # I8 keeps trusting `resolved` for the OPEN-item gate; I25 polices the CLOSED-item claim.
    if isinstance(_i22_clar_raw, dict) and isinstance(_i22_clar_raw.get("ambiguity_register"), list):
        for _i25_item in _i22_clar_raw.get("ambiguity_register"):
            if (isinstance(_i25_item, dict)
                    and _i25_item.get("materiality") == "material"
                    and _i25_item.get("resolved") is True
                    and not str(_i25_item.get("resolution") or "").strip()):
                rep.fail(f"{LABEL_STEM['resolution_present']} ({_i25_item.get('id', '?')})",
                         "material item marked resolved carries no resolution text")

    # ---- I26 sources register (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.1. Presence-triggered on the I-dod/I24 structural union (cartography / graph / units /
    # synthesis; learnings.json EXCLUDED — the Phase-0.5 deadlock, I24 precedent). NOT archive-silent
    # (deliberately, like I-dod/I24): the observed failure mode is SILENT cartography-skipping, so a
    # structurally-active run without a schema-valid source register FAILs check 1 (archived runs newly
    # flagging read as §5 expected skew — never edited, never backfilled). Offline post-hoc predicate
    # over emitted artifacts: gates NO FSM transition, no LT7 guard — correction-loop termination
    # (Claim D) and AO-1..7 untouched (PRESERVES). Content checks (2-6 + 5b) fire whenever sources.json
    # RAW-parses to an object, schema-valid or not (the I22 raw-parse visibility posture); the .strip()
    # bar mirrors the schema conditionals one layer stricter (I25/G11 whitespace precedent).
    _i26_trigger = (
        docs.get("cartography") is not None
        or os.path.exists(os.path.join(rd, "CARTOGRAPHY.md"))
        or graph_json_exists
        or graph_md_exists
        or bool(unit_subdirs)
        or os.path.exists(os.path.join(rd, "SYNTHESIS.md"))
    )
    _i26_stem = LABEL_STEM['sources_register']
    _i26_note = LABEL_STEM['sources_register_note']
    _i26_path = os.path.join(rd, "sources.json")
    _i26_raw = None
    if os.path.exists(_i26_path):
        try:
            _i26_raw = load_json(_i26_path)
        except Exception:
            _i26_raw = None
    _i26_probs0 = len(rep.problems)
    if _i26_trigger:
        # check 1 (presence) — fail-closed on absent / unparseable / schema-invalid / zero rows.
        _i26_valid = docs.get("sources")            # schema-valid parse (set by check_artifact)
        _i26_rows_ok = (isinstance(_i26_valid, dict)
                        and isinstance(_i26_valid.get("sources"), list)
                        and len(_i26_valid.get("sources")) >= 1)
        if not _i26_rows_ok:
            if not os.path.exists(_i26_path):
                _i26_why = "absent"
            elif _i26_raw is None:
                _i26_why = "unparseable"
            elif _i26_valid is None:
                _i26_why = "schema-invalid"
            else:
                _i26_why = "zero rows"
            rep.fail(f"{_i26_stem} (presence)",
                     f"structural work exists but sources.json is {_i26_why} — a schema-valid source "
                     "register with >=1 row is the cartography floor (fail-closed; NOT archive-silent)")
    # Content checks (2-6 + 5b) — raw-parse mirror, independent of the schema layer.
    if isinstance(_i26_raw, dict):
        _i26_sources = [r for r in (_i26_raw.get("sources") or []) if isinstance(r, dict)]
        _i26_venues = [v for v in (_i26_raw.get("venues") or []) if isinstance(v, dict)]
        _i26_coverage = [c for c in (_i26_raw.get("coverage") or []) if isinstance(c, dict)]
        _i26_ids = [r.get("id") for r in _i26_sources if isinstance(r.get("id"), str)]
        _i26_idset = set(_i26_ids)
        _i26_consulted = {r.get("id") for r in _i26_sources
                          if r.get("disposition") == "consulted" and isinstance(r.get("id"), str)}
        _i26_vids = [v.get("venue_id") for v in _i26_venues if isinstance(v.get("venue_id"), str)]
        _i26_vidset = set(_i26_vids)
        _i26_vadmit = {v.get("venue_id"): (v.get("admitted") is True) for v in _i26_venues
                       if isinstance(v.get("venue_id"), str)}

        def _i26_blank(x):
            return not str(x if x is not None else "").strip()

        # check 2 (consulted floor)
        if not any(r.get("disposition") == "consulted" for r in _i26_sources):
            rep.fail(f"{_i26_stem} (consulted floor)",
                     "zero rows with disposition == 'consulted' — a run that mapped sources without "
                     "opening ANY produced a listing, not cartography")
        # check 3 (id uniqueness) — duplicate source id OR venue_id (I3 dup-unit-id precedent)
        _i26_dup_s = sorted({i for i in _i26_ids if _i26_ids.count(i) > 1})
        _i26_dup_v = sorted({i for i in _i26_vids if _i26_vids.count(i) > 1})
        if _i26_dup_s or _i26_dup_v:
            rep.fail(f"{_i26_stem} (id uniqueness)",
                     f"duplicate ids make reference resolution order-dependent: sources "
                     f"{_i26_dup_s or '[]'}, venues {_i26_dup_v or '[]'}")
        # check 4 (row S<id> completeness) — raw-parse .strip() mirror of the schema conditionals
        for r in _i26_sources:
            _rid = r.get("id") if isinstance(r.get("id"), str) else "?"
            _bad = []
            if _i26_blank(r.get("why")): _bad.append("why")
            if _i26_blank(r.get("locator")): _bad.append("locator")
            if r.get("disposition") == "consulted":
                if _i26_blank(r.get("accessed")): _bad.append("accessed")
                if _i26_blank(r.get("yielded")): _bad.append("yielded")
            if r.get("disposition") == "queued" and _i26_blank(r.get("queued_for")):
                _bad.append("queued_for")
            if _bad:
                rep.fail(f"{_i26_stem} (row {_rid} completeness)",
                         f"blank/whitespace required field(s): {_bad}")
        # check 5 (venue linkage S<id>) — ONE-directional: a consulted/queued T-COMM row's venue must
        # be admitted; a REJECTED T-COMM row needs only a resolvable venue_ref (the honest failed-
        # admission record the §4 overturn path depends on — never a biconditional).
        for r in _i26_sources:
            if r.get("tier") != "T-COMM":
                continue
            _rid = r.get("id") if isinstance(r.get("id"), str) else "?"
            _vref = r.get("venue_ref")
            if not (isinstance(_vref, str) and _vref in _i26_vidset):
                rep.fail(f"{_i26_stem} (venue linkage {_rid})",
                         f"T-COMM row's venue_ref {_vref!r} does not resolve to a venues[].venue_id")
            elif r.get("disposition") in ("consulted", "queued") and not _i26_vadmit.get(_vref):
                rep.fail(f"{_i26_stem} (venue linkage {_rid})",
                         f"a {r.get('disposition')} T-COMM row references venue {_vref!r} whose "
                         "admitted != true")
        # check 5b (venue rationale V<id>) — EVERY venue, admitted or refused, carries K-A/B/C
        for v in _i26_venues:
            _vid = v.get("venue_id") if isinstance(v.get("venue_id"), str) else "?"
            _blk = [k for k in ("k_a", "k_b", "k_c") if _i26_blank(v.get(k))]
            if _blk:
                rep.fail(f"{_i26_stem} (venue rationale {_vid})",
                         f"blank/whitespace admission rationale field(s): {_blk}")
        # check 6 (coverage linkage) — membership + >=1 consulted member (rejects all-unopened basis)
        for c in _i26_coverage:
            _basis = [b for b in (c.get("based_on") or []) if isinstance(b, str)]
            _area = c.get("area") if isinstance(c.get("area"), str) else "?"
            _dangling = sorted(b for b in _basis if b not in _i26_idset)
            if _dangling:
                rep.fail(f"{_i26_stem} (coverage linkage)",
                         f"coverage '{_area}' based_on ids not in sources[]: {_dangling}")
            elif not any(b in _i26_consulted for b in _basis):
                rep.fail(f"{_i26_stem} (coverage linkage)",
                         f"coverage '{_area}' rests on no consulted row (all-unopened basis) — "
                         "membership requires >=1 consulted id")
        # ---- NOTE lines (advisory; never a non-zero exit) ----
        # N-I26 (queued_for dangling): a queued_for ~ ^U[0-9]+$ naming no CURRENT graph.json unit id
        if graph_doc is not None:
            _i26_gunits = {u.get("id") for u in (graph_doc.get("units") or [])
                           if isinstance(u, dict) and isinstance(u.get("id"), str)}
            for r in _i26_sources:
                _qf = r.get("queued_for")
                if isinstance(_qf, str) and re.match(r"^U[0-9]+$", _qf) and _qf not in _i26_gunits:
                    if not args.quiet:
                        print(f"  NOTE  {_i26_note} (queued_for dangling): row {r.get('id')!r} "
                              f"queued_for {_qf!r} names no current graph.json unit")
        # N-I26 (coverage monoculture): >=2 coverage rows ∧ union of CONSULTED based_on ids has card 1
        if len(_i26_coverage) >= 2:
            _i26_union = {b for c in _i26_coverage for b in (c.get("based_on") or [])
                          if isinstance(b, str) and b in _i26_consulted}
            if len(_i26_union) == 1 and not args.quiet:
                print(f"  NOTE  {_i26_note} (coverage monoculture): {len(_i26_coverage)} coverage rows "
                      f"all rest on the single consulted id {sorted(_i26_union)}")
        # N-I26 (external tiers unconsulted): ∃ T-VENDOR/T-COMM row ∧ zero CONSULTED such rows
        _i26_ext = {"T-VENDOR", "T-COMM"}
        if (any(r.get("tier") in _i26_ext for r in _i26_sources)
                and not any(r.get("tier") in _i26_ext and r.get("disposition") == "consulted"
                            for r in _i26_sources)
                and not args.quiet):
            print(f"  NOTE  {_i26_note} (external tiers unconsulted): external-tier rows present but "
                  "none consulted — a user-blessed deferral is legitimate, silence about it is not")
    if _i26_trigger and isinstance(_i26_raw, dict) and len(rep.problems) == _i26_probs0:
        rep.ok(f"{_i26_stem} ({len(_i26_raw.get('sources') or [])} row(s); consulted floor + "
               "disposition completeness + venue/coverage linkage OK)")

    # ---- I27 clarification sweep (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.2. Two-level version-honest trigger. T1 (presence floor) fires when the I-dod/I24
    # structural union holds AND the run is version-stamped >= the release shipping I27 (semver on
    # fsm-state.json.validator_version — the §5 version-skew convention); archived/UNSTAMPED runs stay
    # SILENT — the deliberate asymmetry with I26 (which is NOT archive-silent). T2 (shape checks) fire
    # whenever dimension_sweep is PRESENT, any version — adopting the key is submitting to its checks
    # (the I20/I21 adoption-closure pattern). Offline post-hoc predicate over emitted artifacts: gates
    # NO FSM transition, never guards LT7 => correction-loop termination (Claim D) + AO-1..7 untouched
    # (PRESERVES). Every check reads the RAW-parsed clarifications.json (the I22 raw-parse visibility
    # posture); the .strip() bar is one layer stricter than the schema's minLength:1 (I25/G11). The
    # register-id resolution set is clarifications.json.ambiguity_register (integer ids). Frozen
    # bindings (PLAN §5.0): I27-4's register FILE is RUN_DIR/sources.json; I27-10's record home is the
    # whole-run verification at RUN_DIR/verify.json; the T1 comparator is semver on validator_version.
    # The nine-dimension coverage set is tier-INDEPENDENT (U04 DT-K4 scales DEPTH, never coverage).
    # RT-5 residual: the register's machine-readable unknown-list arm of I27-4 stays ATTESTATION — no
    # such field is bound in the sources register (R-4 widened). Disposition GENUINENESS stays
    # attestation — Limitation Q (validity != correctness).
    _I27_SHIP = "1.9.0"                # release shipping I27; validator_version >= this arms T1
    _I27_DIMS = ["terms", "success-criteria", "scope-boundaries", "audience-format",
                 "constraints", "assumptions", "failure-modes", "sources", "stakes"]
    _i27_stem = LABEL_STEM['clarification_sweep']
    _i27_note = LABEL_STEM['clarification_sweep_note']

    def _i27_semver_ge(a, b):
        # True iff version string a >= b under numeric semver; a malformed/absent a => False
        # (archive-safe: an unstamped or pre-shipping run never arms T1).
        def _parse(v):
            if not isinstance(v, str):
                return None
            head = re.split(r"[-+]", v.strip(), maxsplit=1)[0].split(".")[:3]
            try:
                nums = [int(p) for p in head]
            except (ValueError, TypeError):
                return None
            return tuple(nums + [0] * (3 - len(nums)))
        pa, pb = _parse(a), _parse(b)
        return pa is not None and pb is not None and pa >= pb

    def _i27_blank(x):
        return not str(x if x is not None else "").strip()

    _i27_struct = (
        docs.get("cartography") is not None
        or os.path.exists(os.path.join(rd, "CARTOGRAPHY.md"))
        or graph_json_exists
        or graph_md_exists
        or bool(unit_subdirs)
        or os.path.exists(os.path.join(rd, "SYNTHESIS.md"))
    )
    _i27_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _i27_t1 = _i27_struct and _i27_semver_ge(_i27_ver, _I27_SHIP)

    # RAW clarifications parse — independent of the schema layer (like I26 reads sources.json raw).
    _i27_clar_raw = None
    _i27_clar_path = os.path.join(rd, "clarifications.json")
    if os.path.exists(_i27_clar_path):
        try:
            _i27_clar_raw = load_json(_i27_clar_path)
        except Exception:
            _i27_clar_raw = None
    _i27_sweep = (_i27_clar_raw.get("dimension_sweep")
                  if isinstance(_i27_clar_raw, dict) else None)
    _i27_t2 = isinstance(_i27_sweep, dict)
    _i27_probs0 = len(rep.problems)

    # I27-1 (T1 ∧ clarifications parses ∧ dimension_sweep absent) — "not swept" is now visible.
    if _i27_t1 and isinstance(_i27_clar_raw, dict) and not _i27_t2:
        rep.fail(f"{_i27_stem} (not swept)",
                 f"structural work + validator_version {_i27_ver!r} (>= {_I27_SHIP}) but "
                 "clarifications.json carries no dimension_sweep — the nine-dimension sweep is now "
                 "required (version-gated; archived/unstamped runs stay silent)")

    if _i27_t2:
        _i27_reg = [r for r in (_i27_clar_raw.get("ambiguity_register") or []) if isinstance(r, dict)]
        _i27_regids = {r.get("id") for r in _i27_reg if isinstance(r.get("id"), int)}
        _i27_entries = [e for e in (_i27_sweep.get("dimensions") or []) if isinstance(e, dict)]
        _i27_by_dim = {e.get("dimension"): e for e in _i27_entries}

        # I27-2 (coverage) — the nine literals exactly once, tier-INDEPENDENT.
        _i27_seen = [e.get("dimension") for e in _i27_entries]
        _i27_dupes = sorted({d for d in _i27_seen if d in _I27_DIMS and _i27_seen.count(d) > 1})
        if set(d for d in _i27_seen if d in _I27_DIMS) != set(_I27_DIMS) or _i27_dupes:
            _i27_missing = sorted(set(_I27_DIMS) - set(_i27_seen))
            _i27_extra = sorted({d for d in _i27_seen if d not in _I27_DIMS})
            rep.fail(f"{_i27_stem} (coverage)",
                     f"dimensions[] must cover the nine literals exactly once — missing "
                     f"{_i27_missing or '[]'}, duplicated {_i27_dupes or '[]'}, unknown {_i27_extra or '[]'}")

        # I27-3 (per-entry completeness): found => register_ids resolve; clean => .strip() statement.
        for e in _i27_entries:
            _d = e.get("dimension")
            _disp = e.get("disposition")
            if _disp == "ambiguity-found":
                _rids = [i for i in (e.get("register_ids") or []) if isinstance(i, int)]
                _dangling = sorted(i for i in _rids if i not in _i27_regids)
                if not _rids or _dangling:
                    rep.fail(f"{_i27_stem} (entry {_d} completeness)",
                             f"ambiguity-found entry needs register_ids resolving into the register — "
                             f"empty={not _rids}, dangling={_dangling or '[]'}")
            elif _disp in ("probed-clear", "none-after-genuine-search"):
                if _i27_blank(e.get("search_statement")):
                    rep.fail(f"{_i27_stem} (entry {_d} completeness)",
                             "clean disposition needs a .strip()-non-blank search_statement")

        # I27-4 (cartography round): cartography artifact ∧ sources register FILE exist =>
        #   cartography_round present ∧ status != register-absent; performed => dispositioned_unknowns
        #   non-empty ∧ every register_id resolves; sources_register_ref (when present) names the bound
        #   register (basename sources.json, PR-6). The RT-5 unknown-LIST set checks stay attestation.
        _i27_cart = (docs.get("cartography") is not None
                     or os.path.exists(os.path.join(rd, "CARTOGRAPHY.md")))
        _i27_srcfile = os.path.exists(os.path.join(rd, "sources.json"))
        if _i27_cart and _i27_srcfile:
            _cr = _i27_sweep.get("cartography_round")
            if not isinstance(_cr, dict) or _cr.get("status") == "register-absent":
                rep.fail(f"{_i27_stem} (cartography round)",
                         "cartography + sources register exist but cartography_round is "
                         f"{'absent' if not isinstance(_cr, dict) else 'register-absent'} — record the "
                         "round (status performed / no-register-unknowns)")
            else:
                _ref = _cr.get("sources_register_ref")
                if (isinstance(_ref, str) and _ref.strip()
                        and os.path.basename(_ref.strip()) != "sources.json"):
                    rep.fail(f"{_i27_stem} (cartography round)",
                             f"sources_register_ref {_ref!r} does not name the bound register "
                             "(RUN_DIR/sources.json)")
                if _cr.get("status") == "performed":
                    _du = [u for u in (_cr.get("dispositioned_unknowns") or []) if isinstance(u, dict)]
                    _du_bad = sorted(u.get("register_id") for u in _du
                                     if isinstance(u.get("register_id"), int)
                                     and u.get("register_id") not in _i27_regids)
                    if not _du or _du_bad:
                        rep.fail(f"{_i27_stem} (cartography round)",
                                 "status performed needs dispositioned_unknowns whose register_ids "
                                 f"resolve — empty={not _du}, dangling={_du_bad or '[]'}")

        # I27-5 (resolution_source visibility): every resolved register row carries a valid source enum.
        _I27_RS = {"human-gate", "logged-default", "prompt-verbatim"}
        for r in _i27_reg:
            if r.get("resolved") is True:
                _rs = r.get("resolution_source")
                if _rs is None or _rs not in _I27_RS:
                    rep.fail(f"{_i27_stem} (resolution_source {r.get('id', '?')})",
                             f"resolved row carries resolution_source {_rs!r} not in {sorted(_I27_RS)}")

        # I27-8 (prompt-verbatim receipt): prompt-verbatim => .strip()-non-blank prompt_span.
        for r in _i27_reg:
            if r.get("resolution_source") == "prompt-verbatim" and _i27_blank(r.get("prompt_span")):
                rep.fail(f"{_i27_stem} (prompt_span {r.get('id', '?')})",
                         "prompt-verbatim row has an absent/blank prompt_span receipt")

        # I27-9 (clean->found flip): a dimension-tagged row => that dimension's sweep entry is
        #   ambiguity-found ∧ the row's id ∈ that entry's register_ids. Untagged rows exempt.
        for r in _i27_reg:
            _tag = r.get("dimension")
            if _tag in _I27_DIMS:
                _e = _i27_by_dim.get(_tag)
                _rids = [i for i in ((_e or {}).get("register_ids") or []) if isinstance(i, int)]
                if _e is None or _e.get("disposition") != "ambiguity-found" or r.get("id") not in _rids:
                    rep.fail(f"{_i27_stem} (flip {r.get('id', '?')})",
                             f"register row tagged dimension {_tag!r} but that sweep entry is not "
                             "ambiguity-found with the row id in its register_ids")

        # I27-10 (P8 spot-check presence): at P8/DONE the whole-run verification (RUN_DIR/verify.json)
        #   must carry sweep_spot_check[] with >=1 clean-dispositioned AND >=1 ambiguity-found entry
        #   when each class exists; each entry {dimension, disposition, probe_attempted, outcome} with
        #   a non-blank outcome. Skipping the spot-check is now itself visible (RT-1/RT-4).
        if phase in ("P8_SYNTHESIS", "DONE"):
            _clean_present = any(e.get("disposition") in ("probed-clear", "none-after-genuine-search")
                                 for e in _i27_entries)
            _found_present = any(e.get("disposition") == "ambiguity-found" for e in _i27_entries)
            _wr = None
            _wrp = os.path.join(rd, "verify.json")
            if os.path.exists(_wrp):
                try:
                    _wr = load_json(_wrp)
                except Exception:
                    _wr = None
            _ssc = [s for s in ((_wr.get("sweep_spot_check") if isinstance(_wr, dict) else None) or [])
                    if isinstance(s, dict)]
            _ssc_bad = [s for s in _ssc
                        if not all(k in s for k in ("dimension", "disposition", "probe_attempted", "outcome"))
                        or _i27_blank(s.get("outcome"))]
            _ssc_clean = any(s.get("disposition") in ("probed-clear", "none-after-genuine-search")
                             for s in _ssc)
            _ssc_found = any(s.get("disposition") == "ambiguity-found" for s in _ssc)
            _i27_miss = []
            if _clean_present and not _ssc_clean:
                _i27_miss.append("clean-dispositioned")
            if _found_present and not _ssc_found:
                _i27_miss.append("ambiguity-found")
            if _i27_miss or _ssc_bad:
                rep.fail(f"{_i27_stem} (spot-check)",
                         "P8/DONE whole-run verification (verify.json) sweep_spot_check[] is missing a "
                         f"symmetric entry (need >=1 clean + >=1 found when each class exists) — "
                         f"missing={_i27_miss or '[]'}, malformed={len(_ssc_bad)}")

        # ---- NOTE lines (advisory; never a non-zero exit) ----
        # N-I27 (material self-default): a material row self-defaulted rather than gated (I27-6).
        for r in _i27_reg:
            if (r.get("materiality") == "material" and r.get("resolution_source") == "logged-default"
                    and not args.quiet):
                print(f"  NOTE  {_i27_note} (material self-default): register row {r.get('id')!r} is "
                      "material but resolution_source is logged-default (surfaced, not forbidden)")
        # N-I27 (duplicate statement): >=2 entries share a NORMALIZED search_statement (I27-7).
        _I27_SYN = set(_I27_DIMS) | {
            "term", "success", "criteria", "acceptance", "scope", "boundaries", "boundary",
            "audience", "format", "constraint", "assumption", "failure", "modes", "mode",
            "source", "stake"}

        def _i27_norm(s):
            return " ".join(t for t in re.findall(r"[a-z0-9]+", str(s or "").lower())
                            if t not in _I27_SYN)
        _i27_norms = {}
        for e in _i27_entries:
            _n = _i27_norm(e.get("search_statement"))
            if _n:
                _i27_norms.setdefault(_n, []).append(e.get("dimension"))
        for _n, _ds in _i27_norms.items():
            if len(_ds) >= 2 and not args.quiet:
                print(f"  NOTE  {_i27_note} (duplicate statement): dimensions "
                      f"{sorted(d for d in _ds if d)} share a normalized search_statement — "
                      "duplicate-disposition boilerplate suspect")
        # N-I27 (manufactured diligence): ALL entries ambiguity-found ∧ every linked row minor +
        #   logged-default (I27-11) — deliberately a NOTE (a FAIL would Goodhart dispositions clean).
        if _i27_entries and all(e.get("disposition") == "ambiguity-found" for e in _i27_entries):
            _linked = {i for e in _i27_entries for i in (e.get("register_ids") or [])
                       if isinstance(i, int)}
            _linkrows = [r for r in _i27_reg if r.get("id") in _linked]
            if (_linkrows
                    and all(r.get("materiality") == "minor"
                            and r.get("resolution_source") == "logged-default" for r in _linkrows)
                    and not args.quiet):
                print(f"  NOTE  {_i27_note} (manufactured diligence): all sweep dimensions are "
                      "ambiguity-found with every linked register row minor + logged-default — "
                      "manufactured-diligence suspect")

    if (_i27_t1 or _i27_t2) and len(rep.problems) == _i27_probs0:
        rep.ok(f"{_i27_stem} (T1={_i27_t1}, sweep={'present' if _i27_t2 else 'absent'}; "
               "nine-dimension coverage + disposition presence + linkage OK)")

    # ---- I28 depth-tier floors (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.3. ADOPTION-GATED / ARCHIVE-SILENT: fires ONLY when fsm-state carries a `depth`
    # block (Limitation O(i) pattern); a depth-ABSENT run — every archived run, AND this release's
    # own run when it operates at `full` tier by RECORDED DECISION rather than the mechanical block —
    # leaves I28 WHOLLY SILENT (the archive-safe leg). Offline predicate over emitted artifacts:
    # gates NO FSM transition, never guards LT7 => correction-loop termination (Claim D) + AO-1..7
    # untouched (PRESERVES); a mid-run non-zero exit is a hard stop routed to ESCALATE per the existing
    # convention. Reads the RAW depth block (schema does enums/required; the .strip() bar is one layer
    # stricter — G11/I25). Frozen bindings (PLAN §5.0): tier_at_verification is the VALUE at each unit's
    # verify.retrieval_coverage.tier_at_verification (I30-0 owns its PRESENCE); DT-K4 reads the whole-run
    # RUN_DIR/verify.json.sweep_spot_check[] — the SAME record I27-10 reads (U04 adds no field). I28 does
    # NOT re-implement other invariants' checks (U-F1..U-F7 / I27 / I31+). Residual: stakes/reversibility
    # GENUINENESS and probe/label authorship stay attestation (DR-c/DR-e).
    _i28_depth = fsm.get("depth") if isinstance(fsm, dict) else None
    if isinstance(_i28_depth, dict):
        _i28_stem = LABEL_STEM['depth_floor']
        _i28_note = LABEL_STEM['depth_floor_note']
        _i28_probs0 = len(rep.problems)
        _I28_RANK = {"light": 0, "standard": 1, "full": 2}
        _I28_NINE = {"terms", "success-criteria", "scope-boundaries", "audience-format",
                     "constraints", "assumptions", "failure-modes", "sources", "stakes"}

        def _i28_blank(x):
            return not str(x if x is not None else "").strip()

        _ct = _i28_depth.get("confirmed_tier")
        _eff_tier = _i28_depth.get("tier")
        _just = _i28_depth.get("justification") if isinstance(_i28_depth.get("justification"), dict) else {}
        _extsurf = _just.get("external_surface") if isinstance(_just.get("external_surface"), dict) else {}
        _overrides = [o for o in (_i28_depth.get("overrides") or []) if isinstance(o, dict)]

        # PASS units + a per-unit tier_at_verification map (VALUE read; PRESENCE is I30-0's job).
        _i28_pass = {}          # uid -> verify dict, verdict == PASS
        _i28_tav = {}           # uid -> verify.retrieval_coverage.tier_at_verification (where present)
        for _uid, _dd in unit_docs.items():
            _v = _dd.get("verify") if isinstance(_dd, dict) else None
            if not isinstance(_v, dict):
                continue
            if _v.get("verdict") == "PASS":
                _i28_pass[_uid] = _v
            _rc = _v.get("retrieval_coverage")
            if isinstance(_rc, dict) and _rc.get("tier_at_verification") is not None:
                _i28_tav[_uid] = _rc.get("tier_at_verification")

        # I28-P0 (shape + contentfulness) — schema does enums/required; the .strip() bar catches the
        #   whitespace-only string the schema's minLength:1 admits (G11/I25 precedent).
        _p0_bad = [k for k in ("stakes", "reversibility") if _i28_blank(_just.get(k))]
        if _i28_blank(_extsurf.get("detail")):
            _p0_bad.append("external_surface.detail")
        if _p0_bad:
            rep.fail(f"{_i28_stem} (contentfulness)",
                     f"depth.justification blank/whitespace field(s): {_p0_bad}")

        # I28-P1 (gate provenance) — depth present => personas_confirmed; a clarification-gate
        #   confirmation additionally requires clarification_resolved.
        if gates.get("personas_confirmed") is not True:
            rep.fail(f"{_i28_stem} (gate provenance)",
                     "depth block present but gates.personas_confirmed != true — the depth tier is "
                     "confirmed at the human persona gate")
        if (_i28_depth.get("confirmed_at_gate") == "clarification"
                and gates.get("clarification_resolved") is not True):
            rep.fail(f"{_i28_stem} (gate provenance)",
                     "confirmed_at_gate == 'clarification' but gates.clarification_resolved != true")

        # I28-P1b (unconditional second touch, RT-1) — a personas-confirmed tier whose clarification
        #   gate is resolved MUST record the Phase-2 keep-or-raise touch; a raise MUST be backed by an
        #   overrides[] entry at_gate == "P2_CLARIFICATION" (string equality). A never-touched tier is
        #   a FAIL, not a self-judged skip.
        if (_i28_depth.get("confirmed_at_gate") == "personas"
                and gates.get("clarification_resolved") is True):
            _pt = _i28_depth.get("phase2_touch")
            if not (isinstance(_pt, dict) and _pt.get("outcome") in ("kept", "raised")):
                rep.fail(f"{_i28_stem} (phase2 touch)",
                         "personas-confirmed depth tier with clarification_resolved==true but no "
                         "phase2_touch{outcome in {kept,raised}} — the unconditional Phase-2 second "
                         "touch is unrecorded")
            elif _pt.get("outcome") == "raised" and not any(
                    o.get("at_gate") == "P2_CLARIFICATION" for o in _overrides):
                rep.fail(f"{_i28_stem} (phase2 raise)",
                         "phase2_touch.outcome == 'raised' but no overrides[] entry has "
                         "at_gate == 'P2_CLARIFICATION' — the raise carries no ratchet record")

        # I28-P2 (canonical disclosure — completeness; referent confirmed_tier, PR-3). skipped_floors
        #   as a set == {DT-K2,DT-K4,DT-K5,DT-K6}@confirmed_tier for light/standard; == [] iff full.
        _sf = [s for s in (_just.get("skipped_floors") or []) if isinstance(s, str)]
        if _ct == "full":
            _sf_expect = set()
        elif _ct in ("light", "standard"):
            _sf_expect = {f"{k}@{_ct}" for k in ("DT-K2", "DT-K4", "DT-K5", "DT-K6")}
        else:
            _sf_expect = None
        if _sf_expect is not None and set(_sf) != _sf_expect:
            rep.fail(f"{_i28_stem} (skipped-floor disclosure)",
                     f"skipped_floors {sorted(_sf)} != canonical {sorted(_sf_expect)} for "
                     f"confirmed_tier {_ct!r} (== [] iff full; else the four DT-K@tier prefixes)")

        # I28-P3 (ratchet) — no representable downward move. Non-empty overrides: chain from
        #   confirmed_tier, strictly upward (light<standard<full), decision_ref + pending_units[]
        #   per entry, effective tier == last .to. Empty/absent: effective tier == confirmed_tier.
        if _overrides:
            _prev = _ct
            _p3_ok = True
            for _i, _o in enumerate(_overrides):
                _frm, _to = _o.get("from"), _o.get("to")
                if _i == 0 and _frm != _ct:
                    rep.fail(f"{_i28_stem} (ratchet)",
                             f"overrides[0].from {_frm!r} != confirmed_tier {_ct!r}")
                    _p3_ok = False
                if _i > 0 and _frm != _prev:
                    rep.fail(f"{_i28_stem} (ratchet)",
                             f"overrides[{_i}].from {_frm!r} != prior .to {_prev!r} (chain break)")
                    _p3_ok = False
                if not (_frm in _I28_RANK and _to in _I28_RANK and _I28_RANK[_to] > _I28_RANK[_frm]):
                    rep.fail(f"{_i28_stem} (ratchet)",
                             f"overrides[{_i}] {_frm!r}->{_to!r} is not a strict upward move "
                             "(light<standard<full)")
                    _p3_ok = False
                if _i28_blank(_o.get("decision_ref")):
                    rep.fail(f"{_i28_stem} (ratchet)",
                             f"overrides[{_i}] carries a blank decision_ref")
                    _p3_ok = False
                if not isinstance(_o.get("pending_units"), list):
                    rep.fail(f"{_i28_stem} (ratchet)",
                             f"overrides[{_i}] carries no pending_units[] array")
                    _p3_ok = False
                _prev = _to
            if _p3_ok and _eff_tier != _overrides[-1].get("to"):
                rep.fail(f"{_i28_stem} (ratchet)",
                         f"effective tier {_eff_tier!r} != overrides[-1].to "
                         f"{_overrides[-1].get('to')!r}")
        elif _eff_tier != _ct:
            rep.fail(f"{_i28_stem} (ratchet)",
                     f"no overrides but effective tier {_eff_tier!r} != confirmed_tier {_ct!r} "
                     "(there is no representable downward move)")

        # I28-P3b (override time-scoping, RT-6) — every recorded tier_at_verification is a tier the
        #   chain actually passed through; a pending unit reaching PASS carries tier_at_verification
        #   >= its override's .to. Pre-override PASS units (absent from every pending_units[]) keep
        #   their original floors — no >= obligation.
        _passed_tiers = {_ct} | {o.get("to") for o in _overrides}
        for _uid, _tav in sorted(_i28_tav.items()):
            if _tav not in _passed_tiers:
                rep.fail(f"{_i28_stem} (override time-scoping)",
                         f"units/{_uid} tier_at_verification {_tav!r} is not a tier the chain passed "
                         f"through ({sorted(t for t in _passed_tiers if t)})")
        for _i, _o in enumerate(_overrides):
            _to = _o.get("to")
            for _pu in (_o.get("pending_units") or []):
                if _pu in _i28_pass and _pu in _i28_tav:
                    _tav = _i28_tav[_pu]
                    if (_tav in _I28_RANK and _to in _I28_RANK
                            and _I28_RANK[_tav] < _I28_RANK[_to]):
                        rep.fail(f"{_i28_stem} (override time-scoping)",
                                 f"units/{_pu} is in overrides[{_i}].pending_units and PASSed at "
                                 f"tier_at_verification {_tav!r} < the raised floor {_to!r}")

        # I28-P4 (floor conformance).
        # DT-K2 (probes/chases — unit-scoped): for every PASS unit WITH a tier_at_verification, the
        #   required probe set from its debrief evidence rows scales per tier — light: reopen for
        #   covered fallback rows; standard: reopen for ALL fallback rows + chase for vendor-silent;
        #   full: + reopen for URL-locator rows + chase for T-COMM rows. Each required row_ref is
        #   matched by a probe record (exact int match, non-blank outcome); a provably-empty required
        #   set needs retrieval_probes_none_reason. Visibility backstop (RT-3): list the fallback rows.
        _I28_FALLBACK = {"parametric-only", "cached-copy"}
        for _uid in sorted(_i28_pass):
            _tav = _i28_tav.get(_uid)
            if _tav is None:
                continue
            _rc = _i28_pass[_uid].get("retrieval_coverage")
            _rc = _rc if isinstance(_rc, dict) else {}
            _db = unit_docs.get(_uid, {}).get("debrief")
            _rows = [r for r in ((_db or {}).get("evidence_table") or []) if isinstance(r, dict)]
            _req_reopen, _req_chase, _fallback_refs = set(), set(), []
            for _idx, _r in enumerate(_rows):
                _is_fb = (_r.get("retrieval_rung") in _I28_FALLBACK or _r.get("vendor_silent") is True)
                _covers = [c for c in (_r.get("covers_owed") or []) if isinstance(c, str)]
                if _is_fb and _covers:
                    _fallback_refs.append(_idx)
                if _tav == "light":
                    if _is_fb and _covers:
                        _req_reopen.add(_idx)
                elif _tav in ("standard", "full"):
                    if _is_fb:
                        _req_reopen.add(_idx)
                    if _r.get("vendor_silent") is True:
                        _req_chase.add(_idx)
                    if _tav == "full":
                        if _r.get("source_tier") == "T-COMM":
                            _req_chase.add(_idx)
                        if re.search(r"https?://", str(_r.get("evidence") or "")):
                            _req_reopen.add(_idx)
            _probes = [p for p in (_rc.get("retrieval_probes") or []) if isinstance(p, dict)]
            _reopen_have = {p.get("row_ref") for p in _probes
                            if p.get("kind") == "reopen" and not _i28_blank(p.get("outcome"))}
            _chase_have = {p.get("row_ref") for p in _probes
                           if p.get("kind") == "chase" and not _i28_blank(p.get("outcome"))}
            if _fallback_refs and not args.quiet:
                print(f"  NOTE  {_i28_note} (DT-K2 coverage): units/{_uid} at tier {_tav!r} — "
                      f"{len(_fallback_refs)} fallback row(s) {_fallback_refs}, "
                      f"{len(_reopen_have | _chase_have)} probe(s) recorded")
            _miss_reopen = sorted(r for r in _req_reopen if r not in _reopen_have)
            _miss_chase = sorted(r for r in _req_chase if r not in _chase_have)
            if not _req_reopen and not _req_chase:
                if _i28_blank(_rc.get("retrieval_probes_none_reason")):
                    rep.fail(f"{_i28_stem} (DT-K2 probe floor)",
                             f"units/{_uid} at tier {_tav!r} has a provably-empty required probe set "
                             "but no retrieval_probes_none_reason")
            elif _miss_reopen or _miss_chase:
                rep.fail(f"{_i28_stem} (DT-K2 probe floor)",
                         f"units/{_uid} at tier {_tav!r}: required probes unmatched — reopen rows "
                         f"{_miss_reopen or '[]'}, chase rows {_miss_chase or '[]'}")

        # DT-K4 (sweep spot-check scope — run-scoped) — full tier ∧ dimension_sweep present ⇒ the
        #   whole-run RUN_DIR/verify.json.sweep_spot_check[] (the SAME record I27-10 reads) covers all
        #   nine dimensions, each with a non-blank outcome. Gated to P8/DONE (the record's due phase,
        #   per I27-10) so a mid-run full tier never false-FAILs before the spot-check is owed.
        if _eff_tier == "full" and phase in ("P8_SYNTHESIS", "DONE"):
            _clar = None
            _clarp = os.path.join(rd, "clarifications.json")
            if os.path.exists(_clarp):
                try:
                    _clar = load_json(_clarp)
                except Exception:
                    _clar = None
            _sweep = (_clar.get("dimension_sweep") if isinstance(_clar, dict) else None)
            if isinstance(_sweep, dict):
                _wr = None
                _wrp = os.path.join(rd, "verify.json")
                if os.path.exists(_wrp):
                    try:
                        _wr = load_json(_wrp)
                    except Exception:
                        _wr = None
                _ssc = [s for s in ((_wr.get("sweep_spot_check") if isinstance(_wr, dict) else None) or [])
                        if isinstance(s, dict)]
                _ssc_dims = {s.get("dimension") for s in _ssc if not _i28_blank(s.get("outcome"))}
                if _ssc_dims != _I28_NINE:
                    rep.fail(f"{_i28_stem} (DT-K4 sweep spot-check)",
                             f"full tier + dimension_sweep present but the whole-run sweep_spot_check "
                             f"dimensions {sorted(d for d in _ssc_dims if d)} != the nine-literal enum "
                             "(each entry needs a non-blank outcome)")

        # DT-K5 (consultation — run-scoped) — standard/full ∧ a brief owes a T-VENDOR claim ⇒ the
        #   SOURCES register carries a T-VENDOR row; full ⇒ additionally a T-COMM row.
        if _eff_tier in ("standard", "full"):
            _owes_vendor = any(
                isinstance(_co, dict) and _co.get("min_tier") == "T-VENDOR"
                for _dd in unit_docs.values()
                for _co in ((_dd.get("brief") or {}).get("claims_owed") or [])
                if isinstance(_dd, dict))
            if _owes_vendor:
                _src = docs.get("sources") if isinstance(docs.get("sources"), dict) else {}
                _stiers = {r.get("tier") for r in (_src.get("sources") or []) if isinstance(r, dict)}
                if "T-VENDOR" not in _stiers:
                    rep.fail(f"{_i28_stem} (DT-K5 consultation)",
                             "standard/full tier owes a T-VENDOR claim but the sources register "
                             "carries no T-VENDOR disposition row")
                if _eff_tier == "full" and "T-COMM" not in _stiers:
                    rep.fail(f"{_i28_stem} (DT-K5 consultation)",
                             "full tier owes a T-VENDOR claim but the sources register carries no "
                             "T-COMM disposition row")

        # DT-K6 (panel — unit-scoped) — a unit verified at tier_at_verification == full whose brief
        #   tags intersect {design, schema, validator} must carry a verify.json panel[] block (I16's
        #   own field shapes; I16's checks unchanged).
        _I28_DESIGN = {"design", "schema", "validator"}
        for _uid, _tav in sorted(_i28_tav.items()):
            if _tav != "full":
                continue
            _tags = set((unit_docs.get(_uid, {}).get("brief") or {}).get("tags") or [])
            if _tags & _I28_DESIGN and not isinstance(
                    (unit_docs.get(_uid, {}).get("verify") or {}).get("panel"), list):
                rep.fail(f"{_i28_stem} (DT-K6 panel)",
                         f"units/{_uid} verified at full tier with design/schema/validator tags but "
                         "verify.json carries no panel[] block")

        # I28-P5 (external-surface consistency, RT-4 — run-scoped) — a project-local stakes picture
        #   contradicted by a PASS unit's external-tier evidence rows is a mechanical self-contradiction.
        if _extsurf.get("kind") == "project-local":
            _contra = []
            for _uid in sorted(_i28_pass):
                _db = unit_docs.get(_uid, {}).get("debrief")
                for _idx, _r in enumerate(
                        [r for r in ((_db or {}).get("evidence_table") or []) if isinstance(r, dict)]):
                    if _r.get("source_tier") in ("T-VENDOR", "T-COMM"):
                        _contra.append(f"units/{_uid}#{_idx}")
            if _contra:
                rep.fail(f"{_i28_stem} (external-surface consistency)",
                         f"external_surface.kind == 'project-local' but PASS-unit evidence rows carry "
                         f"T-VENDOR/T-COMM source_tier: {_contra} — the run contradicts its own stakes")

        if len(rep.problems) == _i28_probs0:
            rep.ok(f"{_i28_stem} (tier {_eff_tier!r} confirmed {_ct!r}; disclosure + ratchet + "
                   "floor conformance OK)")

    # ---- I29 execution-effort briefs (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.4. ADOPTION-GATED (the I20/I21 closure pattern): the closure + clauses 2-5 fire ONLY
    # once SOME brief.json in the run carries `claims_owed` or `required_sources`; a zero-adoption run
    # — every archived run AND this release's own run (which adopts NEITHER, by design) — stays WHOLLY
    # SILENT on them (§11 R-7 residual). Clause 1 (queued-consumer closure) is adoption-INDEPENDENT: it
    # rides I26's structurally-triggered register (same version-skew posture as I26). Offline predicate
    # over emitted artifacts: gates NO FSM transition, never guards LT7 => correction-loop termination
    # (Claim D) + AO-1..7 untouched (PRESERVES); a mid-run non-zero exit is a hard stop routed to
    # ESCALATE. Reads RAW briefs (a schema-invalid brief still gets the shape checks — the I22/I26
    # raw-parse visibility posture; every missing key is read safely). CO-2 folds into clause 5
    # (I29-5): trigger is key adoption, NEVER dod_refs presence (U05 §1 seam close). Bindings
    # (PLAN §5.0): source_id/source_ref resolve into RUN_DIR/sources.json; CB-1 is templates/brief.md's
    # canonical bridge string (clause 4 preserves I6 FAIL-ability), compared after whitespace
    # normalization ONLY. This block NEVER pulls verify-side adoption — that forced linkage is I30 (U11).
    _i29_stem = LABEL_STEM['effort_briefs']
    _i29_note = LABEL_STEM['effort_briefs_note']
    _i29_probs0 = len(rep.problems)
    _I29_TYPES = {"empirical-world-fact", "code-behavior", "api-tool-contract",
                  "numeric-quantitative", "causal", "design-judgment", "provenance-quote"}
    _I29_SRC_NATIVE = {"empirical-world-fact", "api-tool-contract", "provenance-quote"}
    _I29_TIERS = {"T-VENDOR", "T-COMM", "T-LOCAL"}
    _I29_CB1 = ("Retrieval coverage: every claims_owed entry is discharged per its min_tier by "
                "evidence rows linked via covers_owed, and every required_sources entry is consulted "
                "at a declared fallback-ladder rung or its unreachability is declared in the debrief "
                "— never silently skipped.")

    def _i29_blank(x):
        return not str(x if x is not None else "").strip()

    def _i29_norm(x):
        return re.sub(r"\s+", " ", str(x if x is not None else "")).strip()

    # RAW briefs — independent of the schema layer; a schema-invalid brief still gets its I29 checks.
    _i29_briefs = {}                       # uid -> raw brief dict (only those that parse to an object)
    for _uid in sorted(unit_subdirs):
        _bp = os.path.join(units_dir, str(_uid), "brief.json")
        if os.path.exists(_bp):
            try:
                _cand = load_json(_bp)
            except Exception:
                _cand = None
            if isinstance(_cand, dict):
                _i29_briefs[_uid] = _cand

    # RAW sources register (clause 1 + clause 3) — re-parsed here so the block is self-contained.
    _i29_src = None
    _i29_srcpath = os.path.join(rd, "sources.json")
    if os.path.exists(_i29_srcpath):
        try:
            _i29_src = load_json(_i29_srcpath)
        except Exception:
            _i29_src = None
    _i29_srows = [r for r in ((_i29_src.get("sources") if isinstance(_i29_src, dict) else None) or [])
                  if isinstance(r, dict)]
    _i29_sidset = {r.get("id") for r in _i29_srows if isinstance(r.get("id"), str)}
    _i29_srow = {r.get("id"): r for r in _i29_srows if isinstance(r.get("id"), str)}

    # current graph unit ids (clause 1 target-resolution + N-I29 vendor-title tokens).
    _i29_gunits = ({u.get("id") for u in (graph_doc.get("units") or [])
                    if isinstance(u, dict) and isinstance(u.get("id"), str)}
                   if graph_doc is not None else set())

    # Clause 1 (queued-consumer closure — adoption-INDEPENDENT; rides I26's register). For every
    #   register row queued_for a CURRENT graph unit whose brief.json exists, the brief must name the
    #   row id in required_sources[].source_id or some claims_owed[].source_ref (lens-A tension 2). A
    #   queued_for naming no current unit stays U02's N-I26 dangling NOTE (BGA retirement tolerance).
    for _r in _i29_srows:
        _qf = _r.get("queued_for")
        _rid = _r.get("id")
        if not (isinstance(_qf, str) and _qf in _i29_gunits and _qf in _i29_briefs
                and isinstance(_rid, str)):
            continue
        _cb = _i29_briefs[_qf]
        _req_ids = {e.get("source_id") for e in (_cb.get("required_sources") or [])
                    if isinstance(e, dict)}
        _owed_refs = {e.get("source_ref") for e in (_cb.get("claims_owed") or [])
                      if isinstance(e, dict)}
        if _rid not in _req_ids and _rid not in _owed_refs:
            rep.fail(f"{_i29_stem} (queued-consumer closure {_rid})",
                     f"sources row {_rid!r} is queued_for {_qf!r} but units/{_qf}/brief.json names it "
                     "in neither required_sources[].source_id nor claims_owed[].source_ref")

    # ADOPTION — ANY brief carrying claims_owed OR required_sources (the I20/I21 pattern).
    _i29_adopt = any(("claims_owed" in _b or "required_sources" in _b)
                     for _b in _i29_briefs.values())
    if _i29_adopt:
        # Closure — every on-disk brief must carry claims_owed (entries, or [] + none_reason).
        _i29_unclosed = sorted(u for u, b in _i29_briefs.items() if "claims_owed" not in b)
        if _i29_unclosed:
            rep.fail(f"{_i29_stem} (adoption closure)",
                     f"a brief adopts claims_owed/required_sources but these briefs carry no "
                     f"claims_owed key: {_i29_unclosed}")

        _i29_vtitles = {str(r.get("title")).lower() for r in _i29_srows
                        if r.get("tier") == "T-VENDOR" and isinstance(r.get("title"), str)}
        for _uid in sorted(_i29_briefs):
            _b = _i29_briefs[_uid]
            _owed = [e for e in (_b.get("claims_owed") or []) if isinstance(e, dict)]
            _reqs = [e for e in (_b.get("required_sources") or []) if isinstance(e, dict)]
            _acc = [c for c in (_b.get("acceptance_criteria") or []) if isinstance(c, str)]
            _dodr = [c for c in (_b.get("dod_refs") or []) if isinstance(c, str)]
            _trigger_pool = set(_acc) | set(_dodr)

            # Clause 2 (owed-entry shape / no-straw): id unique; type in the seven literals; trigger_ref
            #   VERBATIM in acceptance_criteria ∪ dod_refs; min_tier present iff source-native type, and
            #   value in the three-tier enum (raw-parse mirror of schema B1/B2, I22 posture).
            _seen = []
            for _i, _e in enumerate(_owed):
                _eid, _etype = _e.get("id"), _e.get("type")
                _tref, _mt = _e.get("trigger_ref"), _e.get("min_tier")
                _seen.append(_eid)
                _bad = []
                if isinstance(_eid, str) and _seen.count(_eid) > 1:
                    _bad.append(f"duplicate id {_eid!r} within the brief")
                if _etype not in _I29_TYPES:
                    _bad.append(f"type {_etype!r} not in the seven literals")
                if not (isinstance(_tref, str) and _tref in _trigger_pool):
                    _bad.append(f"trigger_ref {_tref!r} not verbatim in acceptance_criteria/dod_refs")
                if _etype in _I29_SRC_NATIVE:
                    if _mt not in _I29_TIERS:
                        _bad.append(f"min_tier {_mt!r} (required for a source-native type) not in "
                                    f"{sorted(_I29_TIERS)}")
                elif _mt is not None:
                    _bad.append(f"min_tier {_mt!r} present on an observation-native type "
                                "(must be absent)")
                if _bad:
                    rep.fail(f"{_i29_stem} (owed-entry shape units/{_uid}#{_i})", "; ".join(_bad))

            # Clause 3 (register linkage): required_sources[].source_id ∈ register ids; tier mirrors the
            #   register row; a required entry resolving to a REJECTED row FAILs; present source_refs ∈ ids.
            for _i, _e in enumerate(_reqs):
                _sid, _tier = _e.get("source_id"), _e.get("tier")
                if _sid not in _i29_sidset:
                    rep.fail(f"{_i29_stem} (register linkage units/{_uid})",
                             f"required_sources[{_i}].source_id {_sid!r} not in sources[].id")
                    continue
                _row = _i29_srow.get(_sid, {})
                if _tier != _row.get("tier"):
                    rep.fail(f"{_i29_stem} (register linkage units/{_uid})",
                             f"required_sources[{_i}].tier {_tier!r} != register row {_sid} tier "
                             f"{_row.get('tier')!r}")
                if _row.get("disposition") == "rejected":
                    rep.fail(f"{_i29_stem} (register linkage units/{_uid})",
                             f"required_sources[{_i}] resolves to REJECTED row {_sid!r} — append an "
                             "overturn row first (U02 §4; history is never rewritten)")
            for _i, _e in enumerate(_owed):
                _sr = _e.get("source_ref")
                if _sr is not None and _sr not in _i29_sidset:
                    rep.fail(f"{_i29_stem} (register linkage units/{_uid})",
                             f"claims_owed[{_i}].source_ref {_sr!r} not in sources[].id")

            # Clause 4 (bridge presence) — non-empty owed/reqs => CB-1 ∈ acceptance_criteria
            #   (whitespace-normalized membership ONLY). This is what preserves I6 FAIL-ability.
            if (_owed or _reqs) and not any(_i29_norm(c) == _i29_norm(_I29_CB1) for c in _acc):
                rep.fail(f"{_i29_stem} (bridge presence units/{_uid})",
                         "non-empty claims_owed/required_sources but the CB-1 bridge criterion is "
                         "absent from acceptance_criteria (whitespace-normalized) — retrieval failure "
                         "is not FAIL-able under I6")

            # Clause 5 (explicit-none — CO-2 fold) — claims_owed present ∧ [] => none_reason non-blank.
            if ("claims_owed" in _b and _b.get("claims_owed") == []
                    and _i29_blank(_b.get("claims_owed_none_reason"))):
                rep.fail(f"{_i29_stem} (explicit-none units/{_uid})",
                         "claims_owed present and empty but claims_owed_none_reason is "
                         "blank/whitespace")

            # ---- NOTE lines (advisory; never a non-zero exit) ----
            # N-I29 (owed-heavy brief): >8 owed entries carrying min_tier ∈ {T-VENDOR,T-COMM}.
            _heavy = [e for e in _owed if e.get("min_tier") in ("T-VENDOR", "T-COMM")]
            if len(_heavy) > 8 and not args.quiet:
                print(f"  NOTE  {_i29_note} (owed-heavy brief): units/{_uid} carries {len(_heavy)} "
                      "external-tier owed entries — consider a research-unit split")
            # N-I29 (tier-shape mismatch): a trigger_ref carrying external-authority tokens whose
            #   obligation is T-LOCAL or an observation-native type (content-vs-tier is judgment; NOTE).
            for _i, _e in enumerate(_owed):
                _tref = _e.get("trigger_ref")
                if not isinstance(_tref, str):
                    continue
                _low = _tref.lower()
                _ext = (bool(re.search(r"https?://", _low))
                        or any(t in _low for t in ("vendor", "documented", "api"))
                        or any(vt and vt in _low for vt in _i29_vtitles))
                _localish = (_e.get("min_tier") == "T-LOCAL"
                             or _e.get("type") in ("code-behavior", "numeric-quantitative",
                                                   "causal", "design-judgment"))
                if _ext and _localish and not args.quiet:
                    print(f"  NOTE  {_i29_note} (tier-shape mismatch): units/{_uid}#{_i} trigger_ref "
                          "carries external-authority tokens but the obligation is "
                          "T-LOCAL/observation-native")

        if len(rep.problems) == _i29_probs0:
            rep.ok(f"{_i29_stem} (adoption; {len(_i29_briefs)} brief(s); queued-consumer + owed-shape "
                   "+ register linkage + bridge + explicit-none OK)")

    # ---- I30 retrieval coverage verify (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.5. ADOPTION-GATED + forced linkage (the I22 pattern, extended to the verify side): the
    # block fires once (a) ANY verdict-bearing verify.json carries `retrieval_coverage`, OR (b) a unit
    # whose brief carries non-empty claims_owed/required_sources ALSO has a verdict-bearing verify.json
    # (brief-side adoption pulls verify-side adoption — closes the "adopt briefs, skip the check" gap).
    # A brief-ONLY adopting unit (an owing brief with NO verify — e.g. every effort_brief_* fixture and
    # this release's own briefs) does NOT trigger I30: no verdict-bearing verify => no obligation. This
    # release adopts NEITHER a retrieval_coverage block NOR an owing-brief-with-verify, so I30 stays
    # WHOLLY SILENT here (§11 R-7 residual, the archive-safe leg). Offline predicate over emitted
    # artifacts: gates NO FSM transition, never guards LT7 => correction-loop termination (Claim D) +
    # AO-1..7 untouched (PRESERVES); a mid-run non-zero exit is a hard stop routed to ESCALATE. Reads
    # RAW verify/brief/debrief (a schema-invalid retrieval_coverage still gets the clauses — the RT-1
    # vacuous-pass mirror re-checks row_refs NON-EMPTY that the schema allOf also pins; every missing
    # key is read safely). Frozen bindings (PLAN §5.0): I30-0 owns tier_at_verification PRESENCE (I28-P4
    # owns its VALUE); clause 5 parses S-id tokens from claims_owed[].note free prose (splice fix 6) and
    # from context_pointers entries matching ^S<n>: (U02's convention). This block is I30 (U11); the
    # brief-side I29 (U10) never pulls verify-side adoption.
    _i30_stem = LABEL_STEM['retrieval_coverage_verify']
    _i30_note = LABEL_STEM['retrieval_coverage_verify_note']
    _i30_probs0 = len(rep.problems)

    def _i30_blank(x):
        return not str(x if x is not None else "").strip()

    def _i30_idx_ok(ix, n):
        return isinstance(ix, int) and not isinstance(ix, bool) and 0 <= ix < n

    # RAW briefs/debriefs/verifies — schema-independent (mirrors I29's raw-brief posture).
    def _i30_load(uid, name):
        _p = os.path.join(units_dir, str(uid), name)
        if os.path.exists(_p):
            try:
                _c = load_json(_p)
            except Exception:
                _c = None
            if isinstance(_c, dict):
                return _c
        return None

    _i30_verifies = {}     # uid -> raw verify dict carrying a verdict (verdict-bearing)
    _i30_rc = {}           # uid -> retrieval_coverage dict (only where present + a dict)
    _i30_briefs = {}       # uid -> raw brief dict
    _i30_debriefs = {}     # uid -> raw debrief dict
    for _uid in sorted(unit_subdirs):
        _b = _i30_load(_uid, "brief.json")
        if _b is not None:
            _i30_briefs[_uid] = _b
        _d = _i30_load(_uid, "debrief.json")
        if _d is not None:
            _i30_debriefs[_uid] = _d
        _v = _i30_load(_uid, "verify.json")
        if _v is not None and "verdict" in _v:
            _i30_verifies[_uid] = _v
            _rc = _v.get("retrieval_coverage")
            if isinstance(_rc, dict):
                _i30_rc[_uid] = _rc

    # ADOPTION — (a) any verify carries retrieval_coverage, OR (b) an owing brief has a verdict-bearing verify.
    def _i30_owing(b):
        _co = b.get("claims_owed"); _rs = b.get("required_sources")
        return (isinstance(_co, list) and len(_co) > 0) or (isinstance(_rs, list) and len(_rs) > 0)
    _i30_owing_with_verify = sorted(u for u in _i30_briefs
                                    if _i30_owing(_i30_briefs[u]) and u in _i30_verifies)
    if bool(_i30_rc) or bool(_i30_owing_with_verify):
        _i30_depth_present = isinstance(fsm.get("depth"), dict) if isinstance(fsm, dict) else False
        _I30_COVERED = {"covered", "covered-downgraded"}

        # Forced linkage: an owing brief whose unit has a verdict-bearing verify => that verify carries
        #   retrieval_coverage => else FAIL (brief-side adoption pulls verify-side adoption).
        for _uid in _i30_owing_with_verify:
            if _uid not in _i30_rc:
                rep.fail(f"{_i30_stem} (forced linkage units/{_uid})",
                         "brief carries non-empty claims_owed/required_sources and the unit has a "
                         "verdict-bearing verify.json, but that verify carries no retrieval_coverage block")
        # Verify-side closure: once ANY verify carries retrieval_coverage, EVERY verdict-bearing verify must.
        if _i30_rc:
            for _uid in sorted(_i30_verifies):
                if _uid not in _i30_rc:
                    rep.fail(f"{_i30_stem} (adoption closure units/{_uid})",
                             "another verify carries retrieval_coverage but this verdict-bearing "
                             "verify.json does not — adoption is all-or-nothing (the I22 pattern)")

        def _i30_sat(row, min_tier):
            # U01's min_tier satisfaction lattice (PLAN §2.1) — claim-scoped; the caller passes a REAL
            # counted row so it is never satisfiable by vacuity. declared-unreachable arithmetic ==
            # parametric-only / T-PARAM ladder fields.
            _st = row.get("source_tier"); _rung = row.get("retrieval_rung")
            _param = (_st == "T-PARAM" or _rung == "parametric-only")
            if min_tier == "T-VENDOR":
                if _st == "T-VENDOR":
                    return True
                if (_st == "T-COMM" and row.get("vendor_silent") is True
                        and not _i30_blank(row.get("vendor_surface_searched"))):
                    return True
                return _param
            if min_tier == "T-COMM":
                if _st in ("T-VENDOR", "T-COMM"):
                    return True
                return _param
            if min_tier == "T-LOCAL":
                return _st == "T-LOCAL"
            return False

        for _uid in sorted(_i30_rc):
            _rc = _i30_rc[_uid]
            _v = _i30_verifies[_uid]
            _verdict = _v.get("verdict")
            _brief = _i30_briefs.get(_uid, {})
            _debrief = _i30_debriefs.get(_uid, {})
            _et = [r for r in (_debrief.get("evidence_table") or []) if isinstance(r, dict)]
            _n = len(_et)
            _owed_list = [e for e in (_brief.get("claims_owed") or []) if isinstance(e, dict)]
            _owed_by_id = {e.get("id"): e for e in _owed_list if isinstance(e.get("id"), str)}
            _oc = [r for r in (_rc.get("owed_check") or []) if isinstance(r, dict)]
            _sc = [r for r in (_rc.get("sources_check") or []) if isinstance(r, dict)]
            _probes = [p for p in (_rc.get("retrieval_probes") or []) if isinstance(p, dict)]

            # Clause 0 (tier stamp): fsm-state depth block present => tier_at_verification present.
            if _i30_depth_present and "tier_at_verification" not in _rc:
                rep.fail(f"{_i30_stem} (tier stamp units/{_uid})",
                         "fsm-state carries a depth block (U04 adopted) but retrieval_coverage omits "
                         "tier_at_verification (I30-0 owns its PRESENCE)")

            # Clause 1 (totality + shape): owed_check ids == brief claims_owed ids (set EQUALITY);
            #   every row_refs/row_ref integer is a valid evidence_table index.
            _oc_ids = {r.get("owed_id") for r in _oc if isinstance(r.get("owed_id"), str)}
            _brief_ids = set(_owed_by_id)
            if _oc_ids != _brief_ids:
                rep.fail(f"{_i30_stem} (totality units/{_uid})",
                         f"owed_check ids {sorted(_oc_ids)} != brief claims_owed ids {sorted(_brief_ids)} "
                         "(set equality — a missing or phantom owed id)")
            for _r in _oc:
                for _ix in (_r.get("row_refs") or []):
                    if not _i30_idx_ok(_ix, _n):
                        rep.fail(f"{_i30_stem} (shape units/{_uid})",
                                 f"owed_check {_r.get('owed_id')!r} row_refs {_ix!r} is not a valid "
                                 f"evidence_table index [0,{_n})")
            for _p in _probes:
                if not _i30_idx_ok(_p.get("row_ref"), _n):
                    rep.fail(f"{_i30_stem} (shape units/{_uid})",
                             f"retrieval_probes row_ref {_p.get('row_ref')!r} is not a valid "
                             f"evidence_table index [0,{_n})")

            # Clause 2 (coverage arithmetic — the anti-fabrication re-computation; RT-1 fix landed).
            for _r in _oc:
                _oid = _r.get("owed_id"); _status = _r.get("status")
                if _status not in _I30_COVERED:
                    continue
                _refs = _r.get("row_refs") or []
                if not _refs:
                    rep.fail(f"{_i30_stem} (vacuous coverage units/{_uid}#{_oid})",
                             "status is covered/covered-downgraded but row_refs is EMPTY — an empty "
                             "universal quantification never counts as coverage (the vacuous-pass hole)")
                    continue
                _counted = [_et[_ix] for _ix in _refs if _i30_idx_ok(_ix, _n)]
                _meta = _owed_by_id.get(_oid)     # None for a phantom owed id (clause 1 owns that)
                if _meta is not None:
                    _otype = _meta.get("type")
                    _bad = [_ix for _ix in _refs if _i30_idx_ok(_ix, _n)
                            and not (_oid in (_et[_ix].get("covers_owed") or [])
                                     and _et[_ix].get("type") == _otype)]
                    if _bad:
                        rep.fail(f"{_i30_stem} (fabricated coverage units/{_uid}#{_oid})",
                                 f"listed row(s) {_bad} do not carry owed id {_oid!r} in covers_owed with "
                                 f"matching type {_otype!r} — a 'covered' the debrief's own rows do not support")
                    _mt = _meta.get("min_tier")
                    if _mt is not None and _counted and not any(_i30_sat(_row, _mt) for _row in _counted):
                        rep.fail(f"{_i30_stem} (min_tier coverage units/{_uid}#{_oid})",
                                 f"no counted row satisfies min_tier {_mt!r} per U01's satisfaction lattice "
                                 "(existential — never satisfiable by vacuity)")
                # Downgrade laundering: any counted parametric-only row, OR a T-VENDOR obligation whose
                #   sole support is the T-COMM vendor-silent form => status MUST be covered-downgraded.
                _must_dg = any(_row.get("retrieval_rung") == "parametric-only" for _row in _counted)
                if _meta is not None and _meta.get("min_tier") == "T-VENDOR":
                    _direct = any(_row.get("source_tier") == "T-VENDOR" for _row in _counted)
                    _vsilent = any(_row.get("source_tier") == "T-COMM" and _row.get("vendor_silent") is True
                                   for _row in _counted)
                    if not _direct and _vsilent:
                        _must_dg = True
                if _must_dg and _status != "covered-downgraded":
                    rep.fail(f"{_i30_stem} (downgrade laundering units/{_uid}#{_oid})",
                             "coverage rests on a parametric-only row or a T-COMM vendor-silent sole support "
                             "of a T-VENDOR obligation — status MUST be covered-downgraded")

            # Clause 3 (PASS-with-uncovered contradiction — the headline).
            if _verdict == "PASS":
                for _r in _oc:
                    if _r.get("status") == "uncovered":
                        rep.fail(f"{_i30_stem} (PASS-with-uncovered units/{_uid}#{_r.get('owed_id')})",
                                 "verdict is PASS but this owed id is uncovered — an honest verifier that "
                                 "records the gap can no longer PASS it")
                for _r in _sc:
                    if _r.get("origin") == "required_sources" and _r.get("outcome") == "not-consulted":
                        rep.fail(f"{_i30_stem} (required-source not-consulted units/{_uid}#{_r.get('source_id')})",
                                 "verdict is PASS but a required_sources entry is recorded not-consulted")

            # Clause 4 (probe floor + shape).
            for _p in _probes:
                if _p.get("kind") not in ("reopen", "chase") or _i30_blank(_p.get("outcome")):
                    rep.fail(f"{_i30_stem} (probe shape units/{_uid})",
                             f"a retrieval_probes row has a bad kind {_p.get('kind')!r} or a blank outcome")
            if not _probes and _i30_blank(_rc.get("retrieval_probes_none_reason")):
                rep.fail(f"{_i30_stem} (probe floor units/{_uid})",
                         "retrieval_probes is empty but retrieval_probes_none_reason is blank/whitespace")
            _external_cov = any(
                _i30_idx_ok(_ix, _n) and _et[_ix].get("source_tier") in ("T-VENDOR", "T-COMM")
                for _r in _oc if _r.get("status") in _I30_COVERED
                for _ix in (_r.get("row_refs") or []))
            if _external_cov and not _probes:
                rep.fail(f"{_i30_stem} (probe floor units/{_uid})",
                         "an owed entry is covered by T-VENDOR/T-COMM rows but retrieval_probes is empty "
                         "(the tier-independent reopen FLOOR; DT-K2 scales on top)")

            # Clause 5 (target-list floor — falsifier items (a)+(b)).
            _sc_ids = {r.get("source_id") for r in _sc if isinstance(r.get("source_id"), str)}
            _target = {e.get("source_id") for e in (_brief.get("required_sources") or [])
                       if isinstance(e, dict) and isinstance(e.get("source_id"), str)}
            _target |= {e.get("source_ref") for e in _owed_list if isinstance(e.get("source_ref"), str)}
            for _e in _owed_list:
                if isinstance(_e.get("note"), str):
                    _target |= set(re.findall(r"S[0-9]+", _e["note"]))
            for _cp in (_brief.get("context_pointers") or []):
                _m = re.match(r"^(S[0-9]+): ", _cp) if isinstance(_cp, str) else None
                if _m:
                    _target.add(_m.group(1))
            _missing_targets = sorted(_target - _sc_ids)
            if _missing_targets:
                rep.fail(f"{_i30_stem} (target-list units/{_uid})",
                         f"sources_check omits required target S-id(s) {_missing_targets} (required_sources "
                         "∪ claims_owed source_ref/note S-ids ∪ context_pointer S-ids)")

            # Clause 6 (consulted-evidenced join — RT-7/PR-1/PR-3).
            for _r in _sc:
                if _r.get("outcome") == "consulted-evidenced":
                    _sid = _r.get("source_id")
                    if not any(isinstance(_sid, str) and _sid in (_row.get("source_refs") or [])
                               for _row in _et):
                        rep.fail(f"{_i30_stem} (consulted-evidenced units/{_uid}#{_sid})",
                                 "sources_check marks this source consulted-evidenced but no debrief "
                                 "evidence row carries it in source_refs")

            # Clause 7 (unreachable-declared join — RT-5).
            _rr = [x for x in (_debrief.get("residual_risks") or []) if isinstance(x, str)]
            for _r in _sc:
                if _r.get("outcome") == "unreachable-declared":
                    _sid = _r.get("source_id")
                    _tok = f"unreachable: {_sid}"
                    if not any(_tok in x for x in _rr):
                        rep.fail(f"{_i30_stem} (unreachable-declared units/{_uid}#{_sid})",
                                 f"sources_check marks {_sid!r} unreachable-declared but the debrief "
                                 f"residual_risks carries no canonical '{_tok}' declaration")

            # ---- NOTE lines (advisory; never a non-zero exit) ----
            # N-I30 (covers_owed fan-out): >=3 owed ids covered SOLELY by one shared row_ref.
            _sole = {}
            for _r in _oc:
                if _r.get("status") in _I30_COVERED:
                    _refs = {_ix for _ix in (_r.get("row_refs") or []) if _i30_idx_ok(_ix, _n)}
                    if len(_refs) == 1:
                        _sole.setdefault(next(iter(_refs)), []).append(_r.get("owed_id"))
            for _ref, _ids in sorted(_sole.items()):
                if len(_ids) >= 3 and not args.quiet:
                    print(f"  NOTE  {_i30_note} (covers_owed fan-out): units/{_uid} row {_ref} is the sole "
                          f"coverage of {len(_ids)} owed ids {sorted(_ids)}")
            # N-I30 (covers_owed dangling): an evidence row covers_owed id matching no brief owed id.
            _dangling = sorted({_c for _row in _et for _c in (_row.get("covers_owed") or [])
                                if isinstance(_c, str) and _c not in _brief_ids})
            if _dangling and not args.quiet:
                print(f"  NOTE  {_i30_note} (covers_owed dangling): units/{_uid} evidence rows carry "
                      f"covers_owed id(s) {_dangling} matching no brief owed id")

        if len(rep.problems) == _i30_probs0:
            rep.ok(f"{_i30_stem} (adoption; {len(_i30_rc)} verify block(s); totality + coverage arithmetic "
                   "+ PASS-contradiction + probe floor + target-list + joins OK)")

    # ---- I31-I34 retrieval-standard predicates (depth 1.9.0) — offline post-hoc; NEVER a live guard ----
    # PLAN §5.6 (specs at §2.1, U01 §3/§4): I31=RL-1 rung presence, I32=RL-2 parametric-downgrade
    # consistency (RL-2's ASSUMPTION-label + residual_risks-presence + confidence-cap checks on
    # parametric-only rows), I33=RL-3 premise-
    # extraction presence (DESIGN-JUDGMENT rows ONLY, PLAN §5.0 PR-4 flag — never every row), I34=CO-1
    # per-entry owed coverage. Each block is ADOPTION-GATED / ARCHIVE-SILENT per the Limitation-O(i)
    # precedent: it fires ONLY once the run's artifacts carry the relevant NEW keys (no archived row/brief
    # does, and this release's own run adopts NEITHER a source_tier/retrieval_rung/extracted_premises row
    # NOR an owing brief — so all four stay WHOLLY SILENT here, the archive-safe leg). Every missing key is
    # read safely. Offline predicates over emitted artifacts: they gate NO FSM transition and never guard
    # LT7 => correction-loop termination (Claim D) + AO-1..7 untouched (PRESERVES; 0 REVISES); a mid-run
    # non-zero exit is a hard stop routed to ESCALATE. Reads RAW debriefs/briefs (schema-independent, the
    # I29/I30 posture). CO-2 is NOT re-added here (folded into I29-5, PLAN §5.6). I32/RL-2 enforces the
    # ASSUMPTION-label, residual_risks-presence, and confidence-cap consequences of parametric-only as
    # OFFLINE artifact-content checks (I6/D1 class, PLAN line 1576 — R-g bars only a LIVE gate keyed on
    # confidence, which these are not); RL-3 extraction ADEQUACY is residual R-f; owed-derivation
    # ADEQUACY is residual R-d.
    _rl31 = LABEL_STEM['rl_rung_presence']
    _rl32 = LABEL_STEM['rl_param_consistency']
    _rl33 = LABEL_STEM['rl_premise_presence']
    _rl34 = LABEL_STEM['co1_owed_coverage']

    def _rl_blank(x):
        return not str(x if x is not None else "").strip()

    def _rl_cache_ok(row):
        # RT-3 decidable core: a cached-copy row's evidence must name a verifier-reachable LOCAL path
        # that exists (a path the verifier cannot open is parametric-only, not a cached copy).
        _txt = str(row.get("evidence") or "")
        for _tok in re.split(r"\s+", _txt):
            _tok = _tok.strip().strip(",;\"'()[]<>")
            if not _tok or "://" in _tok or "/" not in _tok:
                continue
            _tok = re.sub(r":[0-9]+(?::[0-9]+)?$", "", _tok)       # strip a path:line[:col] locator suffix
            for _base in (rd, os.getcwd()):
                _pth = _tok if os.path.isabs(_tok) else os.path.join(_base, _tok)
                if os.path.exists(_pth):
                    return True
        return False

    # RAW debriefs (evidence-row surface for RL-1/RL-2/RL-3) + briefs (owed surface for CO-1).
    _rl_debriefs = {}
    _rl_briefs = {}
    for _uid in sorted(unit_subdirs):
        _dp = os.path.join(units_dir, str(_uid), "debrief.json")
        if os.path.exists(_dp):
            try:
                _c = load_json(_dp)
            except Exception:
                _c = None
            if isinstance(_c, dict):
                _rl_debriefs[_uid] = _c
        _bp = os.path.join(units_dir, str(_uid), "brief.json")
        if os.path.exists(_bp):
            try:
                _c = load_json(_bp)
            except Exception:
                _c = None
            if isinstance(_c, dict):
                _rl_briefs[_uid] = _c
    _rl_rows = {u: [r for r in (d.get("evidence_table") or []) if isinstance(r, dict)]
                for u, d in _rl_debriefs.items()}

    _RL_TIERS = {"T-VENDOR", "T-COMM", "T-LOCAL", "T-PARAM"}
    _RL_EXT_RUNGS = {"live-fetch", "vendored-docs", "cached-copy"}
    _RL1_ALWAYS = {"empirical-world-fact", "api-tool-contract"}
    _RL1_URL = {"provenance-quote", "numeric-quantitative"}

    # I31 = RL-1 (rung presence). ADOPTION = any evidence row carries source_tier/retrieval_rung. A
    #   TRIGGERING row (external type, or a URL-shaped-locator quote/numeric row per RT-7) must declare a
    #   coherent rung stack; a T-LOCAL row needs only a present source_tier (no ladder — PLAN §2 table).
    _rl_ret_adopt = any(("source_tier" in _r or "retrieval_rung" in _r)
                        for _rows in _rl_rows.values() for _r in _rows)
    if _rl_ret_adopt:
        _p0 = len(rep.problems)
        for _uid in sorted(_rl_rows):
            for _i, _r in enumerate(_rl_rows[_uid]):
                _ty = _r.get("type")
                _url = bool(re.search(r"https?://", str(_r.get("evidence") or "")))
                if not ((_ty in _RL1_ALWAYS) or (_ty in _RL1_URL and _url)):
                    continue
                _st = _r.get("source_tier")
                _rung = _r.get("retrieval_rung")
                if _st not in _RL_TIERS:
                    rep.fail(f"{_rl31} (source_tier units/{_uid}#{_i})",
                             f"externally-sourced {_ty!r} row omits a valid source_tier "
                             f"(got {_st!r}; enum {sorted(_RL_TIERS)})")
                    continue
                if _st in ("T-VENDOR", "T-COMM"):
                    if _rung not in _RL_EXT_RUNGS or _rl_blank(_r.get("accessed")):
                        rep.fail(f"{_rl31} (rung units/{_uid}#{_i})",
                                 f"source_tier {_st!r} requires retrieval_rung in {sorted(_RL_EXT_RUNGS)} "
                                 f"and a non-blank accessed date (got rung {_rung!r}, accessed "
                                 f"{_r.get('accessed')!r})")
                elif _st == "T-PARAM":
                    if _rung != "parametric-only":
                        rep.fail(f"{_rl31} (parametric units/{_uid}#{_i})",
                                 f"source_tier T-PARAM requires retrieval_rung 'parametric-only' "
                                 f"(got {_rung!r})")
                if _rung == "cached-copy" and not _rl_cache_ok(_r):
                    rep.fail(f"{_rl31} (cached-copy units/{_uid}#{_i})",
                             "retrieval_rung 'cached-copy' but the evidence names no verifier-reachable "
                             "local cache path that exists (RT-3: an unreachable cache is parametric-only)")
                if _r.get("vendor_silent") is True and _rl_blank(_r.get("vendor_surface_searched")):
                    rep.fail(f"{_rl31} (vendor-silent units/{_uid}#{_i})",
                             "vendor_silent is true but vendor_surface_searched is blank/absent")
        if len(rep.problems) == _p0:
            rep.ok(f"{_rl31} (adoption; {len(_rl_rows)} debrief(s); externally-sourced rows declare a "
                   "coherent source_tier/retrieval_rung/accessed stack)")

    # I32 = RL-2 (parametric downgrade consistency) — PLAN §2.1 §3 (lines 304-307), verbatim: "A
    #   `parametric-only` row carries the `ASSUMPTION:` label in its evidence text; if it covers an owed
    #   id (§4), the debrief's `residual_risks[]` names that claim (presence check — RT-8) and the
    #   debrief cannot report `confidence: 'high'`. All string/enum/set checks." THREE offline checks on
    #   every parametric-only evidence row: (a) the evidence text carries an 'ASSUMPTION:' label; (b) for
    #   each owed id it covers (covers_owed), the debrief's residual_risks[] NAMES that claim; (c) if it
    #   covers an owed id, the debrief's TOP-LEVEL confidence is not 'high'. The confidence cap is an
    #   OFFLINE artifact-content rule (I6/D1 class, PLAN line 1576), NOT a live gate — R-g's "no gate keys
    #   on confidence" bars only a LIVE FSM-transition gate on confidence; this reads the RAW debrief
    #   post-hoc and gates no transition (LT7 untouched). The T-PARAM => parametric-only coherence is
    #   RL-1/I31's, not re-checked here. ADOPTION = any evidence row is parametric-only (this run carries
    #   none => wholly silent). Every missing key is read safely.
    _rl_param_adopt = any(_r.get("retrieval_rung") == "parametric-only"
                          for _rows in _rl_rows.values() for _r in _rows)
    if _rl_param_adopt:
        _p0 = len(rep.problems)
        for _uid in sorted(_rl_rows):
            _d = _rl_debriefs.get(_uid, {})
            _rr = [str(_x) for _x in (_d.get("residual_risks") or []) if _x is not None]
            _conf = _d.get("confidence")
            _owed_covered = False
            for _i, _r in enumerate(_rl_rows[_uid]):
                if _r.get("retrieval_rung") != "parametric-only":
                    continue
                if "ASSUMPTION:" not in str(_r.get("evidence") or ""):
                    rep.fail(f"{_rl32} (assumption-label units/{_uid}#{_i})",
                             "a parametric-only evidence row omits the required 'ASSUMPTION:' label in "
                             "its evidence text (RL-2 (a))")
                _owed = [_c for _c in (_r.get("covers_owed") or []) if isinstance(_c, str)]
                if _owed:
                    _owed_covered = True
                    for _oid in _owed:
                        if not any(_oid in _s for _s in _rr):
                            rep.fail(f"{_rl32} (residual-risk units/{_uid}#{_oid})",
                                     f"a parametric-only row covers owed id {_oid!r} but the debrief's "
                                     "residual_risks[] does not name that claim (RL-2 (b) — RT-8 presence)")
            if _owed_covered and _conf == "high":
                rep.fail(f"{_rl32} (confidence-cap units/{_uid})",
                         "a parametric-only row covers an owed id but the debrief reports top-level "
                         "confidence 'high' — RL-2 (c) caps parametric-covered confidence below 'high'")
        if len(rep.problems) == _p0:
            rep.ok(f"{_rl32} (adoption; every parametric-only row is ASSUMPTION-labeled, and owed coverage "
                   "is residual_risks-named + confidence-capped)")

    # I33 = RL-3 (premise-extraction presence), scoped to DESIGN-JUDGMENT rows ONLY (PLAN §5.0 PR-4).
    #   ADOPTION = any row carries extracted_premises / extracted_premises_none_reason. Each design-
    #   judgment row carries extracted_premises: a non-empty array whose every entry equals the `claim`
    #   of ANOTHER row in the same evidence_table (I20-style verbatim membership — decidable); an empty
    #   array requires a non-blank extracted_premises_none_reason (the I21 explicit-none pattern).
    _rl_prem_adopt = any(("extracted_premises" in _r or "extracted_premises_none_reason" in _r)
                         for _rows in _rl_rows.values() for _r in _rows)
    if _rl_prem_adopt:
        _p0 = len(rep.problems)
        for _uid in sorted(_rl_rows):
            _rows = _rl_rows[_uid]
            _claims = {str(_r.get("claim")) for _r in _rows if isinstance(_r.get("claim"), str)}
            for _i, _r in enumerate(_rows):
                if _r.get("type") != "design-judgment":
                    continue
                _prem = _r.get("extracted_premises")
                if not isinstance(_prem, list) or len(_prem) == 0:
                    if _rl_blank(_r.get("extracted_premises_none_reason")):
                        rep.fail(f"{_rl33} (units/{_uid}#{_i})",
                                 "a design-judgment row carries neither a non-empty extracted_premises "
                                 "array nor a non-blank extracted_premises_none_reason (I21 explicit-none)")
                    continue
                _self = str(_r.get("claim"))
                _bad = [_pt for _pt in _prem
                        if not (isinstance(_pt, str) and _pt in _claims and _pt != _self)]
                if _bad:
                    rep.fail(f"{_rl33} (units/{_uid}#{_i})",
                             f"extracted_premises entries {_bad} are not each the verbatim claim of "
                             "ANOTHER evidence row in the same table (I20-style membership)")
        if len(rep.problems) == _p0:
            rep.ok(f"{_rl33} (adoption; every design-judgment row carries verbatim-linked "
                   "extracted_premises or an explicit none-reason)")

    # I34 = CO-1 (per-entry owed coverage) — PLAN §2.1 U01 §4. ADOPTION = any brief carries a non-empty
    #   claims_owed list (the I29 owing pattern; archives + this run carry none => silent). Fires per unit
    #   whose brief owes AND has a debrief: for EVERY owed entry E there must be >=1 debrief evidence row R
    #   with E.id in R.covers_owed, R.type == E.type, and (E.min_tier present => R satisfies it per U01's
    #   satisfaction lattice — the same existential lattice I30 uses). Verify-INDEPENDENT (PLAN §4): it
    #   catches an uncovered owed id even where no retrieval_coverage block exists — I30's complement.
    def _rl_sat(row, min_tier):
        _st = row.get("source_tier"); _rung = row.get("retrieval_rung")
        _param = (_st == "T-PARAM" or _rung == "parametric-only")
        if min_tier == "T-VENDOR":
            if _st == "T-VENDOR":
                return True
            if (_st == "T-COMM" and row.get("vendor_silent") is True
                    and not _rl_blank(row.get("vendor_surface_searched"))):
                return True
            return _param
        if min_tier == "T-COMM":
            if _st in ("T-VENDOR", "T-COMM"):
                return True
            return _param
        if min_tier == "T-LOCAL":
            return _st == "T-LOCAL"
        return False

    _rl_owed_adopt = any(isinstance(_b.get("claims_owed"), list) and len(_b.get("claims_owed")) > 0
                         for _b in _rl_briefs.values())
    if _rl_owed_adopt:
        _p0 = len(rep.problems)
        for _uid in sorted(_rl_briefs):
            _owed = [e for e in (_rl_briefs[_uid].get("claims_owed") or []) if isinstance(e, dict)]
            if not _owed or _uid not in _rl_debriefs:
                continue
            _rows = _rl_rows.get(_uid, [])
            for _e in _owed:
                _eid, _etype, _mt = _e.get("id"), _e.get("type"), _e.get("min_tier")
                if not isinstance(_eid, str):
                    continue
                _cover = [_r for _r in _rows
                          if _eid in (_r.get("covers_owed") or []) and _r.get("type") == _etype]
                if not _cover:
                    rep.fail(f"{_rl34} (units/{_uid}#{_eid})",
                             f"owed entry {_eid!r} (type {_etype!r}) is discharged by no debrief evidence "
                             "row linking it via covers_owed with a matching type")
                    continue
                if _mt is not None and not any(_rl_sat(_r, _mt) for _r in _cover):
                    rep.fail(f"{_rl34} (units/{_uid}#{_eid})",
                             f"owed entry {_eid!r} is covered but no covering row satisfies min_tier "
                             f"{_mt!r} per U01's satisfaction lattice")
        if len(rep.problems) == _p0:
            rep.ok(f"{_rl34} (adoption; every claims_owed entry discharged by a matching-type covering "
                   "row at its min_tier)")

    # ======================================================================================
    # I35 / I36 / I37 — bounded Socratic dialogue-series transcript (socratic-guardrail 1.10.0)
    # post-hoc/offline, gates no transition, never guards LT7 => PRESERVES. Trigger class mirrors
    # I27's two-level version-honest pattern (§1 trigger doctrine): T1 (presence floor) = the I-dod/I24
    # structural union on a run stamped >= the ship version (REUSES _i27_struct + _i27_semver_ge);
    # archived/unstamped runs stay SILENT. T2 (shape) = dialogues.json PRESENT (any version) — adopting
    # the artifact submits it to every shape check (the I22/I26/I27 RAW-parse posture; load_json +
    # isinstance guards, independent of the schema layer). All predicates read the RAW dialogues.json
    # (and clarifications.json for the verbatim residue joins); never crash. dialogues.json is a NEW
    # optional artifact (the sources.json/I26 zero-fsm-state precedent): no FSM edge/flag/guard, so the
    # correction-loop termination proof (Claim D), AO-1..7 and I1-I34 are UNTOUCHED. Genuineness (a human
    # spoke; q/a fidelity; move truth) stays attestation — Limitation U/V (invariants-i35plus.md §6).
    _DLG_SHIP = "1.10.0"                       # release shipping I35-I40; validator_version >= this arms T1
    _dlg_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _dlg_t1 = _i27_struct and _i27_semver_ge(_dlg_ver, _DLG_SHIP)          # mirror I27 :2657-2666
    _dlg_gates = fsm.get("gates") if isinstance(fsm, dict) else None
    _dlg_gates = _dlg_gates if isinstance(_dlg_gates, dict) else {}
    _dlg_path = os.path.join(rd, "dialogues.json")
    _dlg_present = os.path.exists(_dlg_path)
    _dlg_raw = None                            # RAW parse — the I26/I27 posture (:2669-2678)
    if _dlg_present:
        try:
            _dlg_raw = load_json(_dlg_path)
        except Exception:
            _dlg_raw = None
    _dlg_t2 = _dlg_present
    _dlg_ok = isinstance(_dlg_raw, dict) and isinstance(_dlg_raw.get("dialogues"), list)
    _dialogues = [d for d in (_dlg_raw.get("dialogues") if _dlg_ok else []) if isinstance(d, dict)]
    # clarifications RAW (verbatim residue joins) — I22/I27 raw-parse visibility posture.
    _dlg_clar = None
    _dlg_clarp = os.path.join(rd, "clarifications.json")
    if os.path.exists(_dlg_clarp):
        try:
            _dlg_clar = load_json(_dlg_clarp)
        except Exception:
            _dlg_clar = None
    _dlg_dod = [x for x in ((_dlg_clar.get("definition_of_done") if isinstance(_dlg_clar, dict) else None) or [])
                if isinstance(x, str)]
    _dlg_ng = [x for x in ((_dlg_clar.get("non_goals") if isinstance(_dlg_clar, dict) else None) or [])
               if isinstance(x, str)]
    _dlg_final = set(_dlg_dod) | set(_dlg_ng)
    _dlg_regrows = [r for r in ((_dlg_clar.get("ambiguity_register") if isinstance(_dlg_clar, dict) else None) or [])
                    if isinstance(r, dict)]
    _DLG_KINDS = {"R-OPEN", "R-FORBID", "R-CONFIRM", "R-GATE", "R-PROBE"}
    _DLG_MOVES = {"FORK", "COUNTER", "ADMIT", "PIVOT", "RESIDUAL"}
    _DLG_TOPICS = {"forbid", "fear", "rejection", "invariant"}
    _DLG_INST_RE = re.compile(r"^(p1|p2|p3-cartography|p2-r[0-9]+|p7-U[0-9]{2,}-[0-9]+|p8|bga-A[0-9]{2,})$")

    def _dlg_blank(x):
        return not str(x if x is not None else "").strip()

    def _dlg_rounds(d):
        return [r for r in (d.get("rounds") or []) if isinstance(r, dict)]

    def _dlg_kinds(d):
        return {r.get("kind") for r in _dlg_rounds(d)}

    def _dlg_list_delta(d):
        # recorded list-delta: any dod_edits/non_goals_added, or any edit/drop disposition (DP-11).
        for r in _dlg_rounds(d):
            eff = r.get("effects") if isinstance(r.get("effects"), dict) else {}
            if eff.get("dod_edits") or eff.get("non_goals_added"):
                return True
            for disp in (r.get("dispositions") or []):
                if isinstance(disp, dict) and disp.get("disposition") in ("edit", "drop"):
                    return True
        return False

    # ---- I35 dialogue transcript presence, shape & coverage (U01) — invariants-i35plus.md:102-135 ----
    # trigger class: T1 presence (version-gated) + T2 shape (adoption). PRESERVES.
    _i35_stem = LABEL_STEM['i35_dialogue']
    _i35_probs0 = len(rep.problems)

    # I35-1 [MC-1] :108-113 — presence floor (T1) + RAW-parse surface-record shape (T2).
    if _dlg_t1 and not _dlg_present:
        rep.fail(f"{_i35_stem} (missing)",
                 f"structural work + validator_version {_dlg_ver!r} (>= {_DLG_SHIP}) but no dialogues.json "
                 "— the bounded-dialogue transcript is required (version-gated; archived/unstamped runs "
                 "stay silent)")
    if _dlg_present and not _dlg_ok:
        rep.fail(f"{_i35_stem} (shape)",
                 "dialogues.json does not RAW-parse to an object carrying a dialogues[] array "
                 "(DP-22 surface-record shape)")

    if _dlg_ok:
        # I35-2 [MC-2] :114-117 — surface coverage.
        if _dlg_gates.get("clarification_resolved") is True and \
                not any(d.get("surface_id") == "DS-2" and d.get("instance") == "p2" for d in _dialogues):
            rep.fail(f"{_i35_stem} (surface coverage)",
                     "clarification_resolved is set but no DS-2 'p2' dialogue record exists (MC-2)")
        for _uid in sorted(unit_subdirs):
            _ud = os.path.join(units_dir, _uid)
            if (os.path.exists(os.path.join(_ud, "disagreement.md"))
                    or os.path.exists(os.path.join(_ud, "disagreement.json"))):
                if not any(d.get("surface_id") == "DS-4"
                           and str(d.get("instance", "")).startswith(f"p7-{_uid}-") for d in _dialogues):
                    rep.fail(f"{_i35_stem} (surface coverage DS-4 {_uid})",
                             f"units/{_uid} has a disagreement record but no DS-4 'p7-{_uid}-<n>' dialogue "
                             "record (MC-2)")
        if _dlg_gates.get("personas_confirmed") is True and \
                not any(d.get("surface_id") == "DS-1" for d in _dialogues):
            rep.fail(f"{_i35_stem} (surface coverage DS-1)",
                     "personas_confirmed is set but no DS-1 dialogue record exists (MC-2)")
        if _dlg_gates.get("signoff_confirmed") is True and \
                not any(d.get("surface_id") == "DS-5" for d in _dialogues):
            rep.fail(f"{_i35_stem} (surface coverage DS-5)",
                     "signoff_confirmed is set but no DS-5 dialogue record exists (MC-2)")

        # I35-3 [MC-3] :118-120 — rounds_used <= 3 (schema maximum mirror) AND len(rounds)==rounds_used.
        for d in _dialogues:
            _rus = _as_int(d.get("rounds_used"))
            _rn = _dlg_rounds(d)
            if _rus is None or _rus > 3:
                rep.fail(f"{_i35_stem} (rounds cap {d.get('instance')})",
                         f"rounds_used {d.get('rounds_used')!r} exceeds the cap of 3 (DP-14)")
            elif _rus != len(_rn):
                rep.fail(f"{_i35_stem} (rounds desync {d.get('instance')})",
                         f"rounds_used {_rus} != len(rounds[]) {len(_rn)} (MC-3)")

        # I35-4 [MC-4] :121-128 — per-INSTANCE mandatory-kind coverage (DP-11 instance conditioning).
        for d in _dialogues:
            _sid, _inst, _k = d.get("surface_id"), d.get("instance"), _dlg_kinds(d)
            if _sid == "DS-2" and _inst == "p2":
                _miss = [x for x in ("R-FORBID", "R-CONFIRM") if x not in _k]
                if _miss:
                    rep.fail(f"{_i35_stem} (mandatory kinds {_inst})",
                             f"DS-2 p2 must run {_miss} (DP-11 per-instance mandatory kinds)")
            elif _sid == "DS-2" and isinstance(_inst, str) and _inst.startswith("p2-r"):
                if _dlg_list_delta(d) and "R-CONFIRM" not in _k:
                    rep.fail(f"{_i35_stem} (mandatory kinds {_inst})",
                             "a p2-r<k> re-entry with a recorded list-delta must run R-CONFIRM (DP-11)")
            elif _sid in ("DS-1", "DS-4", "DS-5", "DS-6"):
                if "R-GATE" not in _k:
                    rep.fail(f"{_i35_stem} (mandatory kinds {_inst})",
                             f"{_sid} must run R-GATE once per instance (DP-11)")

        # I35-5 [MC-5] :129-132 — round/question/answer shape (.strip() bars, one layer stricter than schema).
        for d in _dialogues:
            for r in _dlg_rounds(d):
                if r.get("kind") not in _DLG_KINDS:
                    rep.fail(f"{_i35_stem} (round kind)",
                             f"round kind {r.get('kind')!r} is not in the DP-10 enum")
                for _mv in (r.get("moves_used") or []):
                    if _mv not in _DLG_MOVES:
                        rep.fail(f"{_i35_stem} (moves_used)",
                                 f"moves_used entry {_mv!r} is not in the five-move enum")
                for q in (r.get("questions") or []):
                    if not isinstance(q, dict):
                        continue
                    if _dlg_blank(q.get("q")):
                        rep.fail(f"{_i35_stem} (blank question)", "a question carries a blank/absent `q` (MC-5)")
                    if _dlg_blank(q.get("recommended")):
                        rep.fail(f"{_i35_stem} (missing recommended)",
                                 "a question carries a blank/absent `recommended` (DP-24/DP-43 — REQUIRED "
                                 "non-blank on EVERY question)")
                for a in (r.get("answers") or []):
                    if not isinstance(a, dict):
                        continue
                    if _dlg_blank(a.get("a")):
                        rep.fail(f"{_i35_stem} (blank answer)",
                                 "an answer carries a blank/absent literal `a` (DP-9 — the answer slot is "
                                 "human-only; a non-blank literal is REQUIRED, answer_ref is not a substitute)")

        # I35-6 [MC-6] :133-135 — every answer slot filled OR halt-pending with pending_questions (I25 allOf).
        for d in _dialogues:
            _term = d.get("termination") if isinstance(d.get("termination"), dict) else {}
            if _term.get("reason") == "halt-pending":
                if not [x for x in (_term.get("pending_questions") or []) if isinstance(x, str) and x.strip()]:
                    rep.fail(f"{_i35_stem} (halt-pending {d.get('instance')})",
                             "termination halt-pending but pending_questions[] is empty (MC-6/DP-19)")
                continue
            _qids, _answered = [], set()
            for r in _dlg_rounds(d):
                for q in (r.get("questions") or []):
                    if isinstance(q, dict) and isinstance(q.get("qid"), str):
                        _qids.append(q.get("qid"))
                for a in (r.get("answers") or []):
                    if isinstance(a, dict) and isinstance(a.get("q_ref"), str):
                        _answered.add(a.get("q_ref"))
            _unans = [q for q in _qids if q not in _answered]
            if _unans:
                rep.fail(f"{_i35_stem} (answer slot {d.get('instance')})",
                         f"question(s) {_unans} have no matching answer and termination is not halt-pending "
                         "(MC-6 answer-filled-or-halt)")

    if (_dlg_t1 or _dlg_t2) and len(rep.problems) == _i35_probs0:
        rep.ok(f"{_i35_stem} (T1={_dlg_t1}, transcript={'present' if _dlg_t2 else 'absent'}; "
               "presence + surface coverage + rounds cap + mandatory kinds + Q/A shape OK)")

    # ---- I36 dialogue disposition, presentation-bind & residue joins (U01) — :137-175 ----
    # trigger class: T2 shape (adoption). PRESERVES. presentation fidelity is Limitation U.
    _i36_stem = LABEL_STEM['i36_dialogue']
    _i36_note = LABEL_STEM['note_i36']
    _i36_probs0 = len(rep.problems)
    if _dlg_ok:
        # Gather the R-CONFIRM presentation surface across DS-2 records.
        _presented = set()          # every verbatim item string presented in some R-CONFIRM items_presented[]
        _q_ip = {}                  # qid -> its items_presented[]
        _confirm_present = False
        _dispositions = []          # every R-CONFIRM disposition record
        for d in _dialogues:
            if d.get("surface_id") != "DS-2":
                continue
            for r in _dlg_rounds(d):
                if r.get("kind") == "R-CONFIRM":
                    _confirm_present = True
                    _distinct = set()
                    for q in (r.get("questions") or []):
                        if not isinstance(q, dict):
                            continue
                        _ip = [x for x in (q.get("items_presented") or []) if isinstance(x, str)]
                        if len(_ip) > 4:
                            rep.fail(f"{_i36_stem} (stuffing)",
                                     f"an R-CONFIRM question presents {len(_ip)} items (>4 — the DP-29 "
                                     "anti-stuffing bound: one mega-question is not presentation)")
                        for x in _ip:
                            _presented.add(x)
                            _distinct.add(x)
                        if isinstance(q.get("qid"), str):
                            _q_ip[q.get("qid")] = _ip
                    _pages = _as_int(r.get("pages")) or 0
                    if _distinct and _pages < (len(_distinct) + 3) // 4:
                        rep.fail(f"{_i36_stem} (pages)",
                                 f"R-CONFIRM pages {_pages} < ceil({len(_distinct)}/4) distinct presented "
                                 "items (DP-29 pages arithmetic)")
                    for disp in (r.get("dispositions") or []):
                        if isinstance(disp, dict):
                            _dispositions.append(disp)

        # I36-1 [MC-7] :141-153 — three-arm presentation union + q_ref join + DISSENT-3 presentation bind.
        if _confirm_present:
            for disp in _dispositions:
                _item, _origin = disp.get("item"), disp.get("origin")
                _qref, _elic = disp.get("q_ref"), disp.get("elicited_round_ref")
                if _origin == "human-elicited":
                    # DP-31 auto-confirm: bound to its eliciting round, never re-presented (arm c).
                    if _dlg_blank(_elic) and _dlg_blank(_qref):
                        rep.fail(f"{_i36_stem} (bind {_item!r})",
                                 "a human-elicited disposition carries neither elicited_round_ref nor q_ref "
                                 "(DP-31 auto-confirm bind)")
                    continue
                # arm (a): orchestrator-authored dispositions MUST have been presented verbatim.
                if isinstance(_item, str) and _item not in _presented:
                    rep.fail(f"{_i36_stem} (unpresented {_item!r})",
                             "an orchestrator-authored disposition covers an item that appears in NO R-CONFIRM "
                             "items_presented[] (DISSENT-3 presentation bind — records cannot self-cover)")
                    continue
                if isinstance(_qref, str) and _qref in _q_ip and isinstance(_item, str) \
                        and _item not in _q_ip[_qref]:
                    rep.fail(f"{_i36_stem} (q_ref join {_item!r})",
                             f"disposition q_ref {_qref!r} names a question whose items_presented[] does not "
                             "contain the item verbatim (DP-29 per-disposition join)")
            # bijection: every FINAL DoD/NG item is covered by a (latest) disposition via the union.
            _covered = set()
            for disp in _dispositions:
                _dp, _item, _edt = disp.get("disposition"), disp.get("item"), disp.get("edited_to")
                if _dp == "edit" and isinstance(_edt, str):
                    _covered.add(_edt)
                elif _dp == "confirm" and isinstance(_item, str):
                    _covered.add(_item)
            for _fi in sorted(_dlg_final):
                if _fi not in _covered:
                    rep.fail(f"{_i36_stem} (bijection {_fi!r})",
                             "a final definition_of_done/non_goals item is covered by no R-CONFIRM disposition "
                             "(MC-7 disposition<->list bijection)")

        # I36-1b [carried U01 major dissent] :154-161 — recommended-echo counter-join (BOTH disjuncts).
        #   DISJUNCT-1 (the SPEC's PRIMARY, :154-161): a disposition claiming origin:human-elicited whose
        #   `item` is present VERBATIM in its ELICITING round's question `recommended`/`offered` text is
        #   orchestrator-offered BY CONSTRUCTION (DP-31 disjunct 1) and MUST NOT claim the human-elicited
        #   exemption — it must take a hardened draft_edits pairing or an R-CONFIRM presentation. Pure string
        #   arithmetic over already-REQUIRED literal fields; closes the proven happy-path where a "No
        #   additions beyond: NG1..NGn" recommended blob is one-clicked (a==recommended, deviation False, no
        #   probe) and every item claims human-elicited. Resolve the eliciting round via elicited_round_ref
        #   (or q_ref), SAME record only (the I17 self-corroboration bar).
        for d in _dialogues:
            _rn1b = _dlg_rounds(d)
            _round_by_key, _q_by_id = {}, {}
            for r in _rn1b:
                _k = _as_int(r.get("round"))
                if _k is not None:
                    _round_by_key[str(_k)] = r
                for q in (r.get("questions") or []):
                    if isinstance(q, dict) and isinstance(q.get("qid"), str):
                        _q_by_id[q["qid"]] = q
                        _round_by_key[re.sub(r"\.q[0-9]+$", "", q["qid"])] = r   # "p2.r2.q1" -> "p2.r2"
            for r in _rn1b:
                for disp in (r.get("dispositions") or []):
                    if not isinstance(disp, dict) or disp.get("origin") != "human-elicited":
                        continue
                    _item = disp.get("item")
                    if not (isinstance(_item, str) and _item.strip()):
                        continue
                    _texts, _qref = [], disp.get("q_ref")
                    if isinstance(_qref, str) and _qref in _q_by_id:
                        _texts += [_q_by_id[_qref].get("recommended"), _q_by_id[_qref].get("offered")]
                    _erf = disp.get("elicited_round_ref")
                    _er = _round_by_key.get(_erf) if isinstance(_erf, str) else None
                    if _er is None and _as_int(_erf) is not None:
                        _er = _round_by_key.get(str(_as_int(_erf)))
                    if isinstance(_er, dict):
                        for q in (_er.get("questions") or []):
                            if isinstance(q, dict):
                                _texts += [q.get("recommended"), q.get("offered")]
                    if any(isinstance(_t, str) and _item in _t for _t in _texts):
                        rep.fail(f"{_i36_stem} (recommended-echo launder)",
                                 f"disposition item {_item!r} claims origin:human-elicited but is present "
                                 "VERBATIM in its eliciting round's question recommended/offered text — an "
                                 "orchestrator-offered item cannot claim the human-elicited exemption "
                                 "(I36-1b disjunct-1, the SPEC's primary recommended-echo counter-join)")
        #   DISJUNCT-2 (the ADOPTED stronger draft_edits join, kept): a draft_edits `amendment` must NOT be a
        #   verbatim substring of `offered` — a genuine human edit adds text absent from the offered draft.
        for d in _dialogues:
            for r in _dlg_rounds(d):
                eff = r.get("effects") if isinstance(r.get("effects"), dict) else {}
                for de in (eff.get("draft_edits") or []):
                    if not isinstance(de, dict):
                        continue
                    _off, _amd = de.get("offered"), de.get("amendment")
                    if isinstance(_off, str) and isinstance(_amd, str) and _amd.strip() and _amd.strip() in _off:
                        rep.fail(f"{_i36_stem} (recommended-echo launder)",
                                 "a draft_edits `amendment` is a verbatim substring of the `offered` draft — "
                                 "a genuine human edit must add text absent from the offered recommendation "
                                 "(I36-1b recommended-echo counter-join, the adopted stronger bind)")

        # I36-2 [MC-8] :162-168 — forbid-round residue joins + origin bind (both DP-31 disjuncts).
        for d in _dialogues:
            if d.get("surface_id") != "DS-2":
                continue
            for r in _dlg_rounds(d):
                if r.get("kind") != "R-FORBID":
                    continue
                eff = r.get("effects") if isinstance(r.get("effects"), dict) else {}
                for nga in (eff.get("non_goals_added") or []):
                    if isinstance(nga, str) and nga not in set(_dlg_ng):
                        rep.fail(f"{_i36_stem} (forbid residue)",
                                 f"non_goals_added entry {nga!r} is not present verbatim in "
                                 "clarifications.json.non_goals (MC-8/DP-25 verbatim join)")
                _topics = {q.get("battery_topic") for q in (r.get("questions") or []) if isinstance(q, dict)}
                _misst = sorted(_DLG_TOPICS - _topics)
                if _misst:
                    rep.fail(f"{_i36_stem} (forbid battery)",
                             f"R-FORBID battery is missing battery_topic value(s) {_misst} (DP-35 all-four "
                             "coverage)")
                if eff.get("clean_sweep") is True and _dlg_blank(eff.get("clean_sweep_statement")):
                    rep.fail(f"{_i36_stem} (clean sweep)",
                             "clean_sweep true but no clean_sweep_statement (DP-36)")
                # disjunct-2 (draft_edits) hardening: `offered` == some question's `recommended` verbatim;
                #   `amendment` a verbatim substring of some answer's literal `a` (else genuineness is AR).
                _recs = {q.get("recommended") for q in (r.get("questions") or []) if isinstance(q, dict)}
                _ans = [a.get("a") for a in (r.get("answers") or []) if isinstance(a, dict)]
                for de in (eff.get("draft_edits") or []):
                    if not isinstance(de, dict):
                        continue
                    _off, _amd = de.get("offered"), de.get("amendment")
                    if isinstance(_off, str) and _off not in _recs:
                        rep.fail(f"{_i36_stem} (draftedit unbacked)",
                                 "a draft_edits `offered` does not equal any R-FORBID question's `recommended` "
                                 "verbatim (MC-8 disjunct-2 bind — a fabricable pairing)")
                    if isinstance(_amd, str) and not any(isinstance(a, str) and _amd in a for a in _ans):
                        rep.fail(f"{_i36_stem} (draftedit unbacked)",
                                 "a draft_edits `amendment` is not a verbatim substring of any answer's literal "
                                 "`a` (MC-8 disjunct-2 bind — a fabricable pairing)")

        # I36-3 [MC-11] :169-170 — never-re-ask: a verbatim-duplicate item across rounds with no reopened_by.
        _seen_items, _flagged_reask = {}, set()
        for d in _dialogues:
            for r in _dlg_rounds(d):
                _rn = _as_int(r.get("round"))
                for disp in (r.get("dispositions") or []):
                    if not isinstance(disp, dict):
                        continue
                    _it = disp.get("item")
                    if not isinstance(_it, str):
                        continue
                    _prev = _seen_items.get(_it)
                    if _prev is not None and _prev != _rn and _dlg_blank(disp.get("reopened_by")) \
                            and _it not in _flagged_reask:
                        rep.fail(f"{_i36_stem} (re-ask {_it!r})",
                                 "a settled item is re-presented in a later round with no `reopened_by` "
                                 "reference (DP-42 never-re-ask)")
                        _flagged_reask.add(_it)
                    _seen_items.setdefault(_it, _rn)

        # I36-4 [MC-14] :171-175 — register-row coverage. Every material + human-gate resolved register
        #   row resolved in a series-covered visit appears by id in some DS-2 round's register_rows_resolved[];
        #   exemption: the row carries a recorded provenance ref (round_ref — the SS-12 / DP-18 impasse path).
        if any(d.get("surface_id") == "DS-2" for d in _dialogues):
            _resolved_ids = set()
            for d in _dialogues:
                if d.get("surface_id") != "DS-2":
                    continue
                for r in _dlg_rounds(d):
                    eff = r.get("effects") if isinstance(r.get("effects"), dict) else {}
                    for rid in (eff.get("register_rows_resolved") or []):
                        if isinstance(rid, int):
                            _resolved_ids.add(rid)
            for row in _dlg_regrows:
                if (row.get("materiality") == "material" and row.get("resolution_source") == "human-gate"
                        and row.get("resolved") is True):
                    rid = row.get("id")
                    if isinstance(rid, int) and rid not in _resolved_ids and _dlg_blank(row.get("round_ref")):
                        rep.fail(f"{_i36_stem} (register-row coverage {rid})",
                                 f"material human-gate register row {rid} is resolved but is covered by no DS-2 "
                                 "round's register_rows_resolved[] and carries no recorded provenance "
                                 "round_ref (MC-14)")

        # N-I36 [MC-12] :350 §6 — fatigue telemetry (advisory NOTE, never a FAIL): every recorded answer
        #   non-deviating AND every disposition a plain confirm is the all-bulk-confirm rubber-stamp signature.
        _all_ans = [a for d in _dialogues for r in _dlg_rounds(d) for a in (r.get("answers") or [])
                    if isinstance(a, dict)]
        _all_disp = [disp for d in _dialogues for r in _dlg_rounds(d) for disp in (r.get("dispositions") or [])
                     if isinstance(disp, dict)]
        if (_confirm_present and _all_ans and _all_disp
                and all(a.get("deviation") is False for a in _all_ans)
                and all(disp.get("disposition") == "confirm" for disp in _all_disp)
                and not args.quiet):
            print(f"  NOTE  {_i36_note} (rubber-stamp signature): every recorded answer is non-deviating and "
                  "every R-CONFIRM disposition is a plain confirm — the all-bulk-confirm rubber-stamp "
                  "signature (advisory; DP-45/MC-12)")

    if _dlg_t2 and len(rep.problems) == _i36_probs0:
        rep.ok(f"{_i36_stem} (disposition bijection + three-arm presentation union + anti-stuffing + "
               "recommended-echo counter-join + forbid residue + register-row coverage OK)")

    # ---- I37 dialogue termination, probe accounting & instance closure (U01) — :177-205 ----
    # trigger class: T2 shape (adoption). PRESERVES. unrecorded-trigger residual is Limitation V.
    _i37_stem = LABEL_STEM['i37_dialogue']
    _i37_probs0 = len(rep.problems)
    if _dlg_ok:
        # I37-1 [MC-9] :181-189 — termination enum + conditional payloads + probes_lapsed rung LEGALITY.
        for d in _dialogues:
            _term = d.get("termination") if isinstance(d.get("termination"), dict) else {}
            _reason = _term.get("reason")
            _rn = _dlg_rounds(d)
            _qid_round, _rprobe_rounds, _discharge_rounds = {}, set(), set()
            for r in _rn:
                _k = _as_int(r.get("round"))
                for q in (r.get("questions") or []):
                    if isinstance(q, dict) and isinstance(q.get("qid"), str) and _k is not None:
                        _qid_round[q.get("qid")] = _k
                if r.get("kind") == "R-PROBE" and _k is not None:
                    _rprobe_rounds.add(_k)
                if isinstance(r.get("probe_discharge"), dict) and _k is not None:
                    _discharge_rounds.add(_k)
            _rnums = [_as_int(r.get("round")) for r in _rn if _as_int(r.get("round")) is not None]
            _max_round = max(_rnums) if _rnums else 0
            # conditional payloads (RAW mirror of the I25 allOf).
            if _reason == "capped-unconverged":
                if not isinstance(_term.get("impasse_dossier"), dict):
                    rep.fail(f"{_i37_stem} (capped no dossier {d.get('instance')})",
                             "termination capped-unconverged but no impasse_dossier record (DP-18/MC-9)")
                if not [x for x in (_term.get("capped_open") or []) if isinstance(x, dict)]:
                    rep.fail(f"{_i37_stem} (capped open {d.get('instance')})",
                             "termination capped-unconverged but capped_open[] is empty (DP-18)")
            if _reason == "halt-pending":
                if not [x for x in (_term.get("pending_questions") or []) if isinstance(x, str) and x.strip()]:
                    rep.fail(f"{_i37_stem} (halt pending {d.get('instance')})",
                             "termination halt-pending but pending_questions[] is empty (DP-19/MC-9)")
            if d.get("surface_id") == "DS-2" and _reason in ("converged", "human-early"):
                if _dlg_blank(_term.get("gate_answer")):
                    rep.fail(f"{_i37_stem} (gate answer {d.get('instance')})",
                             "DS-2 converged/human-early requires a non-blank termination.gate_answer "
                             "(DP-26/MC-9 — DP-16's fourth conjunct)")
            for pl in (_term.get("probes_lapsed") or []):
                if not isinstance(pl, dict):
                    continue
                _cause, _pqref = pl.get("cause"), pl.get("q_ref")
                if _cause == "human-early":
                    if _reason != "human-early":
                        rep.fail(f"{_i37_stem} (rung human-early {d.get('instance')})",
                                 "a probes_lapsed cause 'human-early' is legal only when termination.reason == "
                                 "human-early (MC-9 rung legality)")
                elif _cause == "cap-exhausted":
                    if _reason == "human-early":
                        rep.fail(f"{_i37_stem} (rung cap {d.get('instance')})",
                                 "cause 'cap-exhausted' is illegal when termination.reason == human-early "
                                 "(MC-9 rung legality)")
                    else:
                        _k = _qid_round.get(_pqref)
                        if _k is None:
                            # fail-CLOSED (mirror I37-3's dangling rollback_ref bar): a cap-exhausted lapse
                            #   whose q_ref resolves to NO recorded round cannot be shown rung-legal — an
                            #   unresolvable lapse ref must FAIL, never silently pass (the round-1 fail-open).
                            rep.fail(f"{_i37_stem} (lapse dangling q_ref {d.get('instance')})",
                                     f"probes_lapsed cause cap-exhausted names q_ref {_pqref!r} that resolves "
                                     "to no recorded round — an unresolvable lapse ref fails closed (MC-9 rung "
                                     "legality; mirror of the I37-3 dangling-ref bar)")
                        elif _k < _max_round \
                                and not (any(rr > _k for rr in _rprobe_rounds)
                                         or any(rr > _k for rr in _discharge_rounds)):
                            rep.fail(f"{_i37_stem} (lapse wrong rung {d.get('instance')})",
                                     f"probes_lapsed cause cap-exhausted but the trigger fired in round {_k} "
                                     f"with a later round on record and no probe_discharge / R-PROBE in a round "
                                     f"> {_k} — rung-choice laundering (MC-9/DP-12 legality arithmetic)")

        # I37-2 [MC-10] :190-196 — probe-obligation accounting (no-unserved via trigger (c); no-wrong-rung
        #   is I37-1's arithmetic). A halt-pending surface SUSPENDS its obligations (DP-50 row 7).
        for d in _dialogues:
            _term = d.get("termination") if isinstance(d.get("termination"), dict) else {}
            _reason = _term.get("reason")
            if _reason == "halt-pending":
                continue
            _fired_c = any(isinstance(disp, dict) and disp.get("disposition") in ("edit", "drop")
                           for r in _dlg_rounds(d) for disp in (r.get("dispositions") or []))
            if _fired_c:
                _served = (any(r.get("kind") == "R-PROBE" for r in _dlg_rounds(d))
                           or any(isinstance(r.get("probe_discharge"), dict) for r in _dlg_rounds(d))
                           or bool([x for x in (_term.get("probes_lapsed") or []) if isinstance(x, dict)])
                           or _reason == "human-early")
                if not _served:
                    rep.fail(f"{_i37_stem} (probe unserved {d.get('instance')})",
                             "an R-CONFIRM edit/drop fired a DP-12(c) probe obligation with none of "
                             "{R-PROBE round, probe_discharge, probes_lapsed entry, human-early} recorded "
                             "(MC-10 no-unserved)")

        # I37-3 [MC-13] :197-205 — instance closure: DP-49 vocabulary + uniqueness + p2-r<k> license join
        #   with INJECTIVITY + dense/ordered k; DS-4/DS-6 key-target existence joins.
        _inst_counts, _p2r, _ks, _licenses = {}, [], [], []
        for d in _dialogues:
            _inst = d.get("instance")
            if not (isinstance(_inst, str) and _DLG_INST_RE.match(_inst)):
                rep.fail(f"{_i37_stem} (instance vocabulary)",
                         f"instance {_inst!r} is not in the DP-49 closed per-surface vocabulary "
                         "(free-form minting is a transcript defect)")
                continue
            _inst_counts[_inst] = _inst_counts.get(_inst, 0) + 1
            if _inst.startswith("p2-r"):
                _p2r.append(d)
        for _inst, _n in sorted(_inst_counts.items()):
            if _n > 1:
                rep.fail(f"{_i37_stem} (instance uniqueness)",
                         f"instance {_inst!r} appears {_n}x (DP-49 per-key uniqueness / cardinality)")
        for d in _p2r:
            _inst, _rbr = d.get("instance"), d.get("rollback_ref")
            if _dlg_blank(_rbr):
                rep.fail(f"{_i37_stem} (reentry unlicensed {_inst})",
                         "a p2-r<k> re-entry carries no resolvable rollback_ref license (DP-49/MC-13 — a "
                         "re-entry must be purchased by a recorded human rollback decision)")
            else:
                _licenses.append(str(_rbr).strip())
            _m = re.match(r"^p2-r([0-9]+)$", _inst or "")
            if _m:
                _ks.append(int(_m.group(1)))
        _dupL = sorted({l for l in _licenses if _licenses.count(l) > 1})
        if _dupL:
            rep.fail(f"{_i37_stem} (reentry non-injective)",
                     f"distinct p2-r<k> re-entries share rollback_ref license(s) {_dupL} — each must "
                     "reference a DISTINCT license record (MC-13 injectivity)")
        if _ks and sorted(_ks) != list(range(1, len(_ks) + 1)):
            rep.fail(f"{_i37_stem} (reentry k-density)",
                     f"p2-r<k> indices {sorted(_ks)} are not the dense, ordered 1..{len(_ks)} sequence "
                     "(MC-13 the k-th bind)")
        for d in _dialogues:
            _sid, _inst = d.get("surface_id"), d.get("instance")
            if _sid == "DS-4" and isinstance(_inst, str):
                _m = re.match(r"^p7-(U[0-9]{2,})-[0-9]+$", _inst)
                if _m:
                    _uid = _m.group(1)
                    _ud = os.path.join(units_dir, _uid)
                    if not (os.path.exists(os.path.join(_ud, "disagreement.md"))
                            or os.path.exists(os.path.join(_ud, "disagreement.json"))):
                        rep.fail(f"{_i37_stem} (DS-4 target {_inst})",
                                 f"DS-4 {_inst} names no units/{_uid}/disagreement record (DP-49 key-target join)")
            if _sid == "DS-6" and isinstance(_inst, str):
                _m = re.match(r"^bga-(A[0-9]{2,})$", _inst)
                if _m and not os.path.exists(os.path.join(rd, "amendments", f"{_m.group(1)}.json")):
                    rep.fail(f"{_i37_stem} (DS-6 target {_inst})",
                             f"DS-6 {_inst} names no amendments/{_m.group(1)}.json (DP-49 key-target join)")

    if _dlg_t2 and len(rep.problems) == _i37_probs0:
        rep.ok(f"{_i37_stem} (termination enum + conditional payloads + rung-choice legality + probe "
               "accounting + instance closure with license injectivity OK)")

    # ---- I38 ask-first consequential-default legality (socratic-guardrail 1.10.0; U02/U04) ----
    # ask-first.md §invariant/§trigger/§laundering. OFFLINE post-hoc predicate over emitted artifacts:
    # gates NO FSM transition, adds no back-edge, never guards LT7, adds no REQUIRED_GATES flag => the
    # correction-loop termination proof (Claim D), AO-1..7 and I1-I34 are UNTOUCHED (PRESERVES; AF-22).
    # All schema deltas are OPTIONAL (archives stay schema-valid). I27 (:2645+) and I8 (:5470+) are
    # carried BYTE-UNTOUCHED: I27-6 keeps its N-I27 NOTE at all versions and I8 stays LOUD — so a
    # >=1.10.0 material consequential logged-default draws BOTH N-I27 AND this AF-14 FAIL (intended; the
    # AF-40 marker-aware I8 relaxation is DECLINED here — U06's flagged item). CC(r) = AF-1 v AF-33: K1
    # (dimension in the three ask-first classes) OR K2 (r.id fed DoD/NG/out-of-scope text via a
    # *_provenance register_ids union, incl. the AF-33 out_of_scope block so the third channel cannot
    # silently drop) — MATERIALITY-BLIND (AF-2: CC NEVER reads r.materiality; the downgrade dodge is
    # dead). Split trigger (AF-44): T1 = _i27_struct ∧ stamp>=1.10.0 (AF-16req/18/19/20); T1 v T1h
    # (AF-14/15); T1h = stamp ∧ pending_halt marker, NO struct conjunct (the true-P2 halt is pre-
    # structural — AF-35 NOTE, AF-36); T1v = stamp-only (AF-38 NOTE); T2 = adopted key present at ANY
    # version (AF-16 dangling, AF-17, AF-35 shape, AF-42, AF-45). Reads clarifications.json opt keys RAW
    # (the I22/I25/I26/I27 raw-parse posture; reuses I27's _i27_clar_raw); never crashes.
    _AF_SHIP = "1.10.0"                        # release shipping I38; validator_version >= arms T1/T1v
    _af_stem = LABEL_STEM['i38_askfirst']
    _af_note = LABEL_STEM['note_i38']
    _AF_KDIM = {"success-criteria", "scope-boundaries", "failure-modes"}   # AF-1 K1 (register-#2 classes)
    _AF_PROV_BLOCKS = ("definition_of_done_provenance", "non_goals_provenance", "out_of_scope_provenance")

    def _af_blank(x):
        return not str(x if x is not None else "").strip()

    _af_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _af_t1v = _i27_semver_ge(_af_ver, _AF_SHIP)                 # stamp-only arm (AF-44 _i35_t1v)
    _af_t1 = _i27_struct and _af_t1v                            # version-gated presence (AF-23; reuse _i27_struct)
    _af_clar = _i27_clar_raw if isinstance(_i27_clar_raw, dict) else None   # RAW clarifications (reuse I27 parse)
    _af_halt = _af_clar.get("pending_halt") if isinstance(_af_clar, dict) else None
    _af_halt = _af_halt if isinstance(_af_halt, dict) else None
    _af_t1h = _af_t1v and _af_halt is not None                  # halt arm: stamp ∧ marker (AF-44 _i35_t1h)

    _af_reg = [r for r in ((_af_clar.get("ambiguity_register") if isinstance(_af_clar, dict) else None) or [])
               if isinstance(r, dict)]
    _af_regids = {r.get("id") for r in _af_reg if isinstance(r.get("id"), int)}
    _af_dod = set(x for x in ((_af_clar.get("definition_of_done") if isinstance(_af_clar, dict) else None) or [])
                  if isinstance(x, str))
    _af_ng = set(x for x in ((_af_clar.get("non_goals") if isinstance(_af_clar, dict) else None) or [])
                 if isinstance(x, str))
    _af_scope = _af_clar.get("scope") if isinstance(_af_clar, dict) else None
    _af_oos = set(x for x in ((_af_scope.get("out_of_scope") if isinstance(_af_scope, dict) else None) or [])
                  if isinstance(x, str))
    _AF_MIRROR = {"definition_of_done_provenance": _af_dod,
                  "non_goals_provenance": _af_ng,
                  "out_of_scope_provenance": _af_oos}

    # provenance blocks (RAW) + the K2 register_ids union across ALL THREE blocks (AF-1 + AF-33).
    _af_prov_items = []            # list of (block_name, item_dict)
    _af_provids = set()
    for _bn in _AF_PROV_BLOCKS:
        for _pi in ((_af_clar.get(_bn) if isinstance(_af_clar, dict) else None) or []):
            if isinstance(_pi, dict):
                _af_prov_items.append((_bn, _pi))
                for _rid in (_pi.get("register_ids") or []):
                    if isinstance(_rid, int):
                        _af_provids.add(_rid)
    _af_prov_present = bool(_af_prov_items)

    def _af_prong(r):
        _p = []
        if r.get("dimension") in _AF_KDIM:
            _p.append("K1")
        if isinstance(r.get("id"), int) and r.get("id") in _af_provids:
            _p.append("K2")
        return "/".join(_p)

    def _af_cc(r):
        # CC(r) = K1(r) v K2(r); MATERIALITY-BLIND (AF-2 — never reads r.materiality).
        return bool(_af_prong(r))

    # transcript round-id set (opaque strings; AF-28) — instance, instance.r<k>, qids + qid prefixes.
    _af_round_ids = set()
    for d in _dialogues:
        _inst = d.get("instance")
        if isinstance(_inst, str) and _inst.strip():
            _af_round_ids.add(_inst.strip())
        for r in _dlg_rounds(d):
            _k = _as_int(r.get("round"))
            if isinstance(_inst, str) and _k is not None:
                _af_round_ids.add(f"{_inst}.r{_k}")
            for q in (r.get("questions") or []):
                if isinstance(q, dict) and isinstance(q.get("qid"), str) and q["qid"].strip():
                    _qid = q["qid"].strip()
                    _af_round_ids.add(_qid)
                    _af_round_ids.add(re.sub(r"\.q[0-9]+$", "", _qid))

    def _af_resolves(ref):
        return (not _af_blank(ref)) and str(ref).strip() in _af_round_ids

    _af_t2any = (_af_prov_present or _af_halt is not None
                 or any(not _af_blank(r.get("round_ref")) for r in _af_reg))
    _af_probs0 = len(rep.problems)

    # halt-freshness (AF-42): a run cannot be "halted at the clarification surface" with EXECUTED work
    # on disk. Cartography/graph presence alone does NOT violate freshness (a P3-round halt is legit).
    _af_synth = os.path.exists(os.path.join(rd, "SYNTHESIS.md"))
    _af_debrief = any(os.path.exists(os.path.join(units_dir, _u, "debrief.json")) for _u in unit_subdirs)
    _af_fresh = (not _af_synth) and phase not in ("P8_SYNTHESIS", "DONE") and (not _af_debrief)

    if isinstance(_af_clar, dict):
        # AF-14 illegal default (T1 v T1h) — a CC row resolved logged-default is ILLEGAL (register #2).
        if _af_t1 or _af_t1h:
            for r in _af_reg:
                if _af_cc(r) and r.get("resolution_source") == "logged-default":
                    rep.fail(f"{_af_stem} (illegal default {r.get('id', '?')})",
                             f"consequential-class row ({_af_prong(r)} prong) is logged-default; register #2 "
                             "makes this class ask-first (AF-14; CC is materiality-blind)")
        # AF-15 dimension required (T1 v T1h) — every register row must carry an enum dimension.
        if _af_t1 or _af_t1h:
            for r in _af_reg:
                if r.get("dimension") not in _I27_DIMS:
                    rep.fail(f"{_af_stem} (dimension missing {r.get('id', '?')})",
                             f"register row carries dimension {r.get('dimension')!r} not in the nine-literal "
                             "enum — an untagged row silently evades K1 (AF-15; version-gated requiredness)")
        # AF-16 unlinked human-gate (T1 requiredness) + dangling round_ref (T2 adoption, any version).
        for r in _af_reg:
            _rr = r.get("round_ref")
            if _af_t1 and _af_cc(r) and r.get("resolution_source") == "human-gate":
                if not _af_resolves(_rr):
                    rep.fail(f"{_af_stem} (unlinked human-gate {r.get('id', '?')})",
                             "consequential human-gate row has no round_ref resolving into the dialogue "
                             "transcript round-id set (AF-16; human-gate without dialogue residue is LP-5)")
            elif (not _af_blank(_rr)) and not _af_resolves(_rr):
                rep.fail(f"{_af_stem} (dangling round_ref {r.get('id', '?')})",
                         f"round_ref {_rr!r} resolves into no dialogue transcript round id "
                         "(AF-16 T2 adoption arm — writing the key submits to the check)")
        # AF-17 provenance well-formedness (T2 adoption) — all three blocks checked identically.
        if _af_prov_present:
            for _bn, _pi in _af_prov_items:
                _dangling = sorted(i for i in (_pi.get("register_ids") or [])
                                   if isinstance(i, int) and i not in _af_regids)
                if _dangling:
                    rep.fail(f"{_af_stem} (provenance dangling)",
                             f"{_bn} item register_ids {_dangling} resolve into no register row (AF-17)")
                _item = _pi.get("item")
                if isinstance(_item, str) and _item not in _AF_MIRROR[_bn]:
                    rep.fail(f"{_af_stem} (provenance dangling)",
                             f"{_bn} item {_item!r} is not a verbatim member of its mirror anchor list (AF-17)")
        # AF-45 provenance attribution coherence + round-resolution (T2 adoption).
        if _af_prov_present:
            for _bn, _pi in _af_prov_items:
                _src, _rr = _pi.get("source"), _pi.get("round_ref")
                if _src == "register-row" and not [i for i in (_pi.get("register_ids") or [])
                                                   if isinstance(i, int)]:
                    rep.fail(f"{_af_stem} (provenance attribution)",
                             f"{_bn} item claims source 'register-row' but carries no register_ids (AF-45)")
                if _src == "human-round" and _af_blank(_rr):
                    rep.fail(f"{_af_stem} (provenance attribution)",
                             f"{_bn} item claims source 'human-round' but carries no round_ref (AF-45)")
                if (not _af_blank(_rr)) and not _af_resolves(_rr):
                    rep.fail(f"{_af_stem} (provenance round dangling)",
                             f"{_bn} item round_ref {_rr!r} resolves into no transcript round id (AF-45)")
        # AF-35 halt-marker shape (T2 adoption, any version) — register_ids must resolve.
        if _af_halt is not None:
            _hd = sorted(i for i in (_af_halt.get("register_ids") or [])
                         if isinstance(i, int) and i not in _af_regids)
            if _hd:
                rep.fail(f"{_af_stem} (halt dangling {_hd})",
                         f"pending_halt.register_ids {_hd} resolve into no register row (AF-35)")
        # AF-36 halt-materiality coherence (T1h) — EVERY marker-listed row must be materiality:material.
        if _af_t1h:
            _byid = {r.get("id"): r for r in _af_reg if isinstance(r.get("id"), int)}
            for _hi in [i for i in (_af_halt.get("register_ids") or []) if isinstance(i, int)]:
                _hr = _byid.get(_hi)
                if _hr is not None and _hr.get("materiality") != "material":
                    rep.fail(f"{_af_stem} (halt materiality {_hi})",
                             "a pending_halt-listed row is not materiality:material — a gap the run halted "
                             "for is material by that act; declaring it minor is the clean-exit dodge (AF-36)")
        # AF-42 halt-freshness / anti-forgery (T2 marker adoption, any version).
        if _af_halt is not None and not _af_fresh:
            rep.fail(f"{_af_stem} (halt after work)",
                     "pending_halt present but the run carries completed-work evidence (SYNTHESIS.md / P8 "
                     "phase / a unit debrief.json) — a run cannot be halted at the clarification surface "
                     "with executed work on disk (AF-42 park-and-ship closure)")
        # AF-18 open consequential with structural evidence (T1) — freshness-conditional marker exemption.
        if _af_t1:
            _af_listed = set()
            if _af_halt is not None and _af_fresh:
                _af_listed = {i for i in (_af_halt.get("register_ids") or []) if isinstance(i, int)}
            for r in _af_reg:
                if _af_cc(r) and r.get("resolved") is False and r.get("id") not in _af_listed:
                    rep.fail(f"{_af_stem} (open consequential {r.get('id', '?')})",
                             "consequential row is open (resolved:false) and unlisted while structural work "
                             "exists — proceeding on a consequential gap is illegal (AF-18; the marker "
                             "exemption is halt-freshness-conditional)")
        # AF-19 verbatim spot-check (T1 ∧ phase in {P8_SYNTHESIS, DONE}).
        if _af_t1 and phase in ("P8_SYNTHESIS", "DONE"):
            _af_vc = None
            _af_vp = os.path.join(rd, "verify.json")
            if os.path.exists(_af_vp):
                try:
                    _af_vc = load_json(_af_vp)
                except Exception:
                    _af_vc = None
            _af_checked = {s.get("register_id") for s in
                           ((_af_vc.get("consequential_verbatim_check") if isinstance(_af_vc, dict) else None) or [])
                           if isinstance(s, dict) and not _af_blank(s.get("outcome"))}
            for r in _af_reg:
                if _af_cc(r) and r.get("resolution_source") == "prompt-verbatim" and r.get("id") not in _af_checked:
                    rep.fail(f"{_af_stem} (verbatim spot-check {r.get('id', '?')})",
                             "consequential prompt-verbatim row is not enumerated with a non-blank outcome in "
                             "verify.json consequential_verbatim_check[] (AF-19)")

        # ---- NOTE lines (advisory; never a non-zero exit) ----
        # AF-35 NOTE (T1h): a well-formed marker listing >=1 CC row reports the pending question + the
        #   AF-43 structural-artifact count (the R8 discriminator) — visibility, never a clean exit.
        if _af_t1h and not args.quiet:
            _hids = [i for i in (_af_halt.get("register_ids") or []) if isinstance(i, int)]
            _byid = {r.get("id"): r for r in _af_reg if isinstance(r.get("id"), int)}
            if (_hids and not [i for i in _hids if i not in _af_regids]
                    and any(_af_cc(_byid[i]) for i in _hids if i in _byid)):
                _nstruct = (sum(1 for _p in ("CARTOGRAPHY.md", "GRAPH.md", "SYNTHESIS.md")
                                if os.path.exists(os.path.join(rd, _p)))
                            + (1 if (docs.get("cartography") is not None or graph_json_exists) else 0)
                            + len(unit_subdirs))
                print(f"  NOTE  {_af_note} (halted pending human): row(s) {_hids} pending at "
                      f"{_af_halt.get('surface')!r}; {_nstruct} structural artifact(s)")
        # AF-20 verbatim-heavy NOTE (T1): > half of consequential rows resolved prompt-verbatim.
        if _af_t1 and not args.quiet:
            _cc_rows = [r for r in _af_reg if _af_cc(r)]
            _cc_pv = [r for r in _cc_rows if r.get("resolution_source") == "prompt-verbatim"]
            if _cc_rows and len(_cc_pv) * 2 > len(_cc_rows):
                print(f"  NOTE  {_af_note} (verbatim-heavy): {len(_cc_pv)}/{len(_cc_rows)} consequential "
                      "rows resolved prompt-verbatim — stretch-laundering suspect (AF-20; LP-4)")
        # AF-38 unsolicited-authorship NOTE (T1v stamp-only): self-declared orchestrator-draft items.
        if _af_t1v and _af_prov_present and not args.quiet:
            _auth = [_pi.get("item") for _bn, _pi in _af_prov_items if _pi.get("source") == "orchestrator-draft"]
            if _auth:
                print(f"  NOTE  {_af_note} (unsolicited authorship): {_auth} item(s) authored from neither a "
                      "register row nor a dialogue round (AF-38; self-declared authorship only)")

    # AF-21 success line (armed via T1 or an adopted key + no clause failed). Zero-trigger runs (stamp
    # unarmed / stamp-only with no adopted key) emit nothing (adoption-scoped emission).
    if (_af_t1 or _af_t2any) and isinstance(_af_clar, dict) and len(rep.problems) == _af_probs0:
        _cc_n = sum(1 for r in _af_reg if _af_cc(r))
        rep.ok(f"{_af_stem} (T1={_af_t1}, {_cc_n} consequential row(s); keying + linkage + legality OK)")

    # ---- I39 anchor confirmation, provenance & baseline integrity (socratic-guardrail 1.10.0; U03/U04/U06) ----
    # governance.md §1-§2/§5 (GV-3/7/8/9/11/23/34/35). OFFLINE post-hoc predicate over emitted
    # artifacts: gates NO FSM transition, adds no back-edge, NEVER guards LT7, adds no REQUIRED_GATES
    # flag => the correction-loop termination proof (Claim D), AO-1..7 and I1-I34 are UNTOUCHED
    # (PRESERVES; GV-28/GV-33). All schema deltas are OPTIONAL (archives stay schema-valid). Reads
    # clarifications.json.item_confirmations[]/anchors_retired[]/definition_of_done/non_goals RAW
    # (reuses I27's _i27_clar_raw) and dialogues.json.anchors_baseline RAW (reuses _dlg_raw) — the
    # I22/I25/I26/I27 raw-parse posture; never crashes. Two-level trigger (§1 doctrine): _gov_t1 =
    # _i27_struct ∧ stamp>=1.10.0 (GV-9 fail-closed item_confirmations presence); _gov_semver1 =
    # stamp>=1.10.0 (the anchors_baseline fail-closed dissent-1 arm on clarification_resolved).
    # Adoption arms (T2) fire on item_confirmations/anchors_baseline PRESENCE at ANY version. GV-8(d)/
    # GV-23 replay is anchored to the IMMUTABLE anchors_baseline (the I17 baseline_units pattern,
    # :1835+) so a same-file coordinated list+record rewrite (dissent 2) cannot move the baseline it is
    # judged against — closed up to transcript-file integrity (Limitation X: a fully-coordinated
    # baseline+hash rewrite in the one transcript file is git-only-witnessed, unread). GV-29
    # required-once-stamped presence is a flagged REVISES of the clarifications artifact contract for
    # NEW runs only (archives silent via the version gate); no live guard, no FSM edge => PRESERVES.
    _gov_stem = LABEL_STEM['i39_anchor']
    _gov_note = LABEL_STEM['note_i39']
    _GOV_SHIP = "1.10.0"
    _gov_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _gov_semver1 = _i27_semver_ge(_gov_ver, _GOV_SHIP)          # stamp-only arm (dissent 1)
    _gov_t1 = _i27_struct and _gov_semver1                      # version-gated presence (GV-9; reuse _i27_struct)
    _gov_gates = fsm.get("gates") if isinstance(fsm, dict) else None
    _gov_gates = _gov_gates if isinstance(_gov_gates, dict) else {}
    _gov_resolved = _gov_gates.get("clarification_resolved") is True
    _gov_clar = _i27_clar_raw if isinstance(_i27_clar_raw, dict) else None   # RAW clarifications (reuse I27)
    _gov_ic_present = isinstance(_gov_clar, dict) and "item_confirmations" in _gov_clar
    _gov_ic = [r for r in ((_gov_clar.get("item_confirmations") if isinstance(_gov_clar, dict) else None) or [])
               if isinstance(r, dict)]
    _gov_retired = [r for r in ((_gov_clar.get("anchors_retired") if isinstance(_gov_clar, dict) else None) or [])
                    if isinstance(r, dict)]
    _gov_dod = [x for x in ((_gov_clar.get("definition_of_done") if isinstance(_gov_clar, dict) else None) or [])
                if isinstance(x, str)]
    _gov_ng = [x for x in ((_gov_clar.get("non_goals") if isinstance(_gov_clar, dict) else None) or [])
               if isinstance(x, str)]
    _gov_baseline = _dlg_raw.get("anchors_baseline") if isinstance(_dlg_raw, dict) else None
    _gov_baseline = _gov_baseline if isinstance(_gov_baseline, dict) else None

    def _gov_blank(x):
        return not str(x if x is not None else "").strip()

    def _gov_anchor_hash(dod, ng):
        # content hash over the two verbatim lists (GV-34); a self-inconsistent hash is a FAIL (§E).
        canon = json.dumps({"definition_of_done": list(dod), "non_goals": list(ng)},
                           ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def _gov_superseded(idx):
        # GV-35: r is superseded iff a LATER record carries prior_text == r.item on the same list.
        r = _gov_ic[idx]
        for j in range(idx + 1, len(_gov_ic)):
            r2 = _gov_ic[j]
            if r2.get("list") == r.get("list") and r2.get("prior_text") == r.get("item"):
                return True
        return False

    def _gov_current_records(x, L):
        # GV-35: the current record(s) for (x, L) — non-superseded records with item==x, list==L.
        return [_gov_ic[i] for i in range(len(_gov_ic))
                if _gov_ic[i].get("item") == x and _gov_ic[i].get("list") == L
                and not _gov_superseded(i)]

    def _gov_human_confirmed(x, L):
        # GV-7: current record with disposition in {confirmed,edited,added} + a human evidence ref.
        for r in _gov_current_records(x, L):
            if r.get("disposition") in ("confirmed", "edited", "added") and (
                    not _gov_blank(r.get("transcript_ref")) or not _gov_blank(r.get("amendment_ref"))):
                return True
        return False

    _gov_probs0 = len(rep.problems)

    # I39-4(i) [GV-9] — fail-closed item_confirmations presence on a stamped structural run.
    if _gov_t1 and not _gov_ic_present:
        rep.fail(f"{_gov_stem} (item_confirmations missing)",
                 f"structural work + validator_version {_gov_ver!r} (>= {_GOV_SHIP}) but "
                 "clarifications.json carries no item_confirmations[] — anchor confirmation is now "
                 "required (GV-9 fail-closed; archived/unstamped runs stay silent)")

    # I39-4(ii) [DISSENT 1] — anchors_baseline fail-closed: on a stamped clarification_resolved run an
    # ABSENT baseline OR a self-inconsistent content_hash disarms the coordinated-rewrite layer => FAIL.
    if _gov_semver1 and _gov_resolved:
        if _gov_baseline is None:
            rep.fail(f"{_gov_stem} (baseline missing)",
                     "clarification_resolved on a >=1.10.0 run but dialogues.json carries no "
                     "anchors_baseline — omission must not disarm the immutable-baseline layer "
                     "(dissent 1; the I17 amend_missing_baseline / GV-34 fail-closed posture)")
        else:
            _bl_dod = [x for x in (_gov_baseline.get("definition_of_done") or []) if isinstance(x, str)]
            _bl_ng = [x for x in (_gov_baseline.get("non_goals") or []) if isinstance(x, str)]
            _bl_hash = _gov_baseline.get("content_hash")
            if _gov_blank(_bl_hash) or _bl_hash != _gov_anchor_hash(_bl_dod, _bl_ng):
                rep.fail(f"{_gov_stem} (baseline hash)",
                         f"anchors_baseline.content_hash {_bl_hash!r} is not self-consistent with its "
                         "own verbatim lists — a tampered/forged snapshot cannot anchor the replay "
                         "(dissent 1; GV-34 content-hash self-consistency)")

    # I39-2 [GV-7/GV-35] — record currency: two non-superseded records for one (item,list) => FAIL.
    if _gov_ic_present:
        _seen_cur = {}
        for i in range(len(_gov_ic)):
            if _gov_superseded(i):
                continue
            _key = (_gov_ic[i].get("item"), _gov_ic[i].get("list"))
            _seen_cur[_key] = _seen_cur.get(_key, 0) + 1
        for _key in sorted(_seen_cur, key=lambda k: str(k)):
            _it, _L = _key
            if _seen_cur[_key] > 1 and isinstance(_it, str) and isinstance(_L, str):
                rep.fail(f"{_gov_stem} (duplicate currency {_it!r})",
                         f"{_seen_cur[_key]} non-superseded item_confirmations records for ({_it!r}, "
                         f"{_L!r}) — a re-clarified item must SUPERSEDE the earlier record (GV-35)")

    # I39-3 [GV-8(a-d)] — list <-> record <-> baseline reconciliation.
    if _gov_ic_present:
        _dod_set, _ng_set = set(_gov_dod), set(_gov_ng)
        # (a) every list item has a current confirming (confirmed|edited|added) record.
        for _L, _items, _lset in (("definition_of_done", _gov_dod, _dod_set),
                                  ("non_goals", _gov_ng, _ng_set)):
            for _it in _items:
                if not [r for r in _gov_current_records(_it, _L)
                        if r.get("disposition") in ("confirmed", "edited", "added")]:
                    rep.fail(f"{_gov_stem} (unreconciled {_it!r})",
                             f"{_L} item {_it!r} has no current confirming item_confirmations record "
                             "(GV-8(a))")
        # (b) a `removed` current record must have NO matching list item; (c) a non-superseded,
        #     non-removed record matching no list item is dangling (superseded records are history).
        for i in range(len(_gov_ic)):
            if _gov_superseded(i):
                continue
            r = _gov_ic[i]
            _L, _it, _disp = r.get("list"), r.get("item"), r.get("disposition")
            _lset = _dod_set if _L == "definition_of_done" else (_ng_set if _L == "non_goals" else set())
            if _disp == "removed" and _it in _lset:
                rep.fail(f"{_gov_stem} (removed present {_it!r})",
                         f"a current `removed` record for {_it!r} but the item is still in {_L} (GV-8(b))")
            if _disp in ("confirmed", "edited", "added") and _it not in _lset:
                rep.fail(f"{_gov_stem} (dangling record {_it!r})",
                         f"non-superseded {_disp} record for {_it!r} matches no {_L} item — a dangling "
                         "record (GV-8(c); superseded records are history, not dangling)")
        # (d) replay the POST-baseline record sequence forward from the IMMUTABLE anchors_baseline; the
        #     result must reproduce EXACTLY the current lists (GV-8(d), dissent 2 — the coordinated-
        #     rewrite catch anchored to a baseline a same-file edit cannot move).
        if _gov_baseline is not None:
            _rp_dod = [x for x in (_gov_baseline.get("definition_of_done") or []) if isinstance(x, str)]
            _rp_ng = [x for x in (_gov_baseline.get("non_goals") or []) if isinstance(x, str)]
            for r in _gov_ic:
                if _gov_blank(r.get("amendment_ref")):
                    continue                       # a gate/baseline-establishing record, not a post-baseline mutation
                _L = r.get("list")
                _tgt = _rp_dod if _L == "definition_of_done" else (_rp_ng if _L == "non_goals" else None)
                if _tgt is None:
                    continue
                _disp, _it, _prior = r.get("disposition"), r.get("item"), r.get("prior_text")
                if _disp == "added" and _it not in _tgt:
                    _tgt.append(_it)
                elif _disp == "edited":
                    if _prior in _tgt:
                        _tgt[_tgt.index(_prior)] = _it
                    elif _it not in _tgt:
                        _tgt.append(_it)
                elif _disp == "removed" and _prior in _tgt:
                    _tgt.remove(_prior)
            if set(_rp_dod) != _dod_set or set(_rp_ng) != _ng_set:
                rep.fail(f"{_gov_stem} (baseline replay mismatch)",
                         "replaying post-baseline item_confirmations forward from the immutable "
                         f"anchors_baseline yields dod={sorted(set(_rp_dod))}/ng={sorted(set(_rp_ng))} "
                         f"!= current dod={sorted(_dod_set)}/ng={sorted(_ng_set)} — a coordinated "
                         "list+record rewrite cannot move the baseline it is judged against (GV-8(d); dissent 2)")

    # I39-1 [GV-3] — forbid-round residue lands: every non_goal a transcript R-FORBID round added must
    # carry a current elicited-forbid-round confirmation record (never silently merged as an
    # orchestrator item). Reads the RAW transcript effects.non_goals_added + item_confirmations.
    if _gov_ic_present:
        _forbid_added = []
        for d in _dialogues:
            for r in _dlg_rounds(d):
                if r.get("kind") == "R-FORBID":
                    eff = r.get("effects") if isinstance(r.get("effects"), dict) else {}
                    _forbid_added += [s for s in (eff.get("non_goals_added") or []) if isinstance(s, str)]
        for s in _forbid_added:
            if not [r for r in _gov_current_records(s, "non_goals")
                    if r.get("origin") == "elicited-forbid-round" and not _gov_blank(r.get("transcript_ref"))]:
                rep.fail(f"{_gov_stem} (forbid residue lost {s!r})",
                         f"forbid-round non_goal {s!r} has no current elicited-forbid-round "
                         "item_confirmations record with a transcript_ref — the residue was silently "
                         "merged, not deposited as a candidate item (GV-3)")

    # I39-5 [GV-11] — no unconfirmed anchor item past the P2 gate (clarification_resolved).
    if _gov_ic_present and _gov_resolved:
        for _L, _items in (("definition_of_done", _gov_dod), ("non_goals", _gov_ng)):
            for _it in _items:
                if not _gov_human_confirmed(_it, _L):
                    rep.fail(f"{_gov_stem} (unconfirmed past gate {_it!r})",
                             f"clarification_resolved but {_L} item {_it!r} fails human_confirmed "
                             "(GV-11; the item-by-item confirmation gate is mechanical, offline)")

    # I39-6 [GV-23] — baseline-anchored totality: every current-vs-baseline anchor delta must be
    # explained by a post-baseline receipt (an amendment-referencing added/edited/removed record).
    if _gov_ic_present and _gov_baseline is not None:
        _blt_dod = set(x for x in (_gov_baseline.get("definition_of_done") or []) if isinstance(x, str))
        _blt_ng = set(x for x in (_gov_baseline.get("non_goals") or []) if isinstance(x, str))
        _post = [r for r in _gov_ic if not _gov_blank(r.get("amendment_ref"))]
        for _L, _cur, _base in (("definition_of_done", set(_gov_dod), _blt_dod),
                                ("non_goals", set(_gov_ng), _blt_ng)):
            for _it in sorted(_cur - _base):
                if not any(r.get("list") == _L and r.get("item") == _it
                           and r.get("disposition") in ("added", "edited") for r in _post):
                    rep.fail(f"{_gov_stem} (unexplained delta {_it!r})",
                             f"{_L} item {_it!r} is not in the immutable anchors_baseline and no "
                             "post-baseline add/edit receipt explains it — a seventh unenumerated "
                             "route cannot exist silently (GV-23)")
            for _it in sorted(_base - _cur):
                if not any(r.get("list") == _L and r.get("prior_text") == _it
                           and r.get("disposition") in ("removed", "edited") for r in _post):
                    rep.fail(f"{_gov_stem} (unexplained delta {_it!r})",
                             f"{_L} baseline item {_it!r} left the current list with no post-baseline "
                             "remove/edit receipt (GV-23)")

    # I39-7 [Limitation X hardening; 1.10.1] — OPTIONAL ledger-side mirror cross-check. When
    # fsm-state.anchors_baseline_hash is present it MUST equal dialogues.json.anchors_baseline.content_hash
    # — raising the coordinated-rewrite cost from two files (clarifications + dialogues) to three
    # (fsm-state too). ADOPTION-gated on mirror PRESENCE (fires at ANY version; ABSENT => silent,
    # archive-safe — the zero-delta primary posture). This does NOT "Close" Limitation X (git remains the
    # ONLY mutation witness) — it NARROWS it. Offline post-hoc: gates NO transition, adds no back-edge,
    # NEVER guards LT7 => PRESERVES (GV-28 write-once-mirror pattern; classification in state-machine.md §5).
    _gov_abh = fsm.get("anchors_baseline_hash") if isinstance(fsm, dict) else None
    if not _gov_blank(_gov_abh):
        _gov_bl_ch = _gov_baseline.get("content_hash") if isinstance(_gov_baseline, dict) else None
        if _gov_baseline is None or _gov_abh != _gov_bl_ch:
            rep.fail(f"{_gov_stem} (baseline mirror)",
                     f"fsm-state.anchors_baseline_hash {_gov_abh!r} does not equal "
                     f"dialogues.json.anchors_baseline.content_hash {_gov_bl_ch!r} — the OPTIONAL "
                     "ledger-side mirror, once present, must corroborate the transcript baseline "
                     "(Limitation X hardening: a coordinated rewrite must now also rewrite fsm-state; git "
                     "remains the only witness, so X is NARROWED, not Closed)")

    # N-I39 [GV-9/GV-26] — unstamped-disarm NOTE: a structural run that ADOPTED governance artifacts
    # (item_confirmations/anchors_baseline/anchors_retired) but is NOT stamped >=1.10.0 disarms the
    # fail-closed layer; emit an advisory NOTE so the disarm is visible, never silent (the honest
    # residual — a stripped scaffold bypasses the version gate). True pre-1.10.0 archives (no
    # governance artifact) stay SILENT (§1 posture). Exit-neutral (print, gated on --quiet).
    if (_i27_struct and not _gov_semver1
            and (_gov_ic_present or _gov_baseline is not None or _gov_retired) and not args.quiet):
        print(f"  NOTE  {_gov_note} (governance disarmed; unstamped): structural work adopted anchor "
              "governance artifacts but validator_version is absent/<1.10.0 — only the I39-4 version-"
              "gated layer (item_confirmations/anchors_baseline presence-requiredness + the GV-34 "
              "baseline content-hash self-consistency) is advisory here; the adoption-armed checks — "
              "I39 confirmation/reconciliation/forbid-residue/replay and all I40 mutation-gating — stay "
              "armed and still FAIL (GV-9/GV-26 honest residual)")

    # I39 success line (armed via T1 or an adopted governance artifact + no clause failed).
    if ((_gov_t1 or _gov_ic_present or _gov_baseline is not None or _gov_retired)
            and len(rep.problems) == _gov_probs0):
        rep.ok(f"{_gov_stem} (t1={_gov_t1}, {len(_gov_ic)} confirmation record(s); reconciliation + "
               "baseline integrity + provenance OK)")

    # ---- I40 anchor mutation gating (socratic-guardrail 1.10.0; U03/U04/U06) ----
    # governance.md §3-§5 (GV-13/14/15/16/17/18/21/25/36). OFFLINE post-hoc predicate over emitted
    # artifacts: gates NO FSM transition, NEVER guards LT7 => PRESERVES per-unit Claims A-D (GV-30: no
    # back-edge, adds no units, revise_anchors fuel cost >=1 keeps amendment events <= fuel_0; N <=
    # N0+fuel_0 verbatim). **I18 (:1990+) is carried BYTE-VERBATIM — NO fuel REVISES here:** the
    # revise_anchors fuel cost == max(1,0-0) == 1 and the fuel-0-unwritable corner (GV-14/GV-36) are
    # enforced ENTIRELY by the EXISTING I18 arithmetic; I40-2 DELEGATES to it (gov_revise_fuel_cost /
    # amend_fuel0_revise_unwritable pin that composition under the I18 label, not a duplicated formula).
    # Adoption-armed on revise_anchors / item_confirmations / anchors_retired presence (AF-25 pattern;
    # archive-safe — no archive carries the kind). GV-16 membership-union is applied at I20/I21/I22
    # above; I40-4 adds the later-record ordering rule. Reads amendment records + item_confirmations +
    # anchors_retired + graph units + verify guardrail rows RAW; never crashes.
    _gov40_stem = LABEL_STEM['i40_anchor']
    _gov40_probs0 = len(rep.problems)
    _amend_recs = [(fn, rec) for fn, rec in amendments if isinstance(rec, dict)]
    _revise_recs = [(fn, rec) for fn, rec in _amend_recs if rec.get("kind") == "revise_anchors"]
    _addunit_recs = [(fn, rec) for fn, rec in _amend_recs if rec.get("kind") == "add_units"]
    _gov40_units = ([u for u in (graph_doc.get("units") or []) if isinstance(u, dict)]
                    if graph_doc is not None else [])
    _gov40_byid = {u.get("id"): u for u in _gov40_units}

    def _gov40_executed(uid):
        return os.path.exists(os.path.join(units_dir, str(uid), "debrief.json"))

    def _gov40_refs(u, listname):
        _key = "dod_refs" if listname == "definition_of_done" else "non_goal_refs"
        _v = u.get(_key)
        return [r for r in _v if isinstance(r, str)] if isinstance(_v, list) else []

    # I40-1 [GV-13] — every revise_anchors record is human_gate:true + carries a transcript_ref.
    for _fn, rec in _revise_recs:
        if rec.get("human_gate") is not True:
            rep.fail(f"{_gov40_stem} (revise ungated {rec.get('id')})",
                     "revise_anchors record without human_gate==true — anchor mutation has no "
                     "autonomous branch, for any list, for any op (GV-13)")
        if _gov_blank(rec.get("transcript_ref")):
            rep.fail(f"{_gov40_stem} (revise no transcript {rec.get('id')})",
                     "revise_anchors record carries no transcript_ref to the gate-dialogue residue (GV-13)")

    # I40-3 [GV-15(4a-c)] — ref-reconciliation in the transaction: after an edit/remove, no UNEXECUTED
    # unit may still bind the retired text (4b rewrite / 4c sole-ref disposition); a sole dod_refs
    # element removed must be re-pointed or paired with cancel_unit (never left [] under I20 minItems:1).
    _cancelled = set()
    _added_at = {}                                 # uid -> index of the amendment that added it
    for _fn, rec in _amend_recs:
        if rec.get("kind") == "cancel_unit":
            _cancelled |= set(rec.get("units_retired") or [])
    for _idx, (_fn, rec) in enumerate(_amend_recs):
        for _uid in (rec.get("units_added") or []):
            _added_at[_uid] = _idx
    _revise_idx = {rec.get("id"): _idx for _idx, (_fn, rec) in enumerate(_amend_recs)}
    for _fn, rec in _revise_recs:
        _L = rec.get("list")
        _ri = _revise_idx.get(rec.get("id"), -1)
        for op in (rec.get("revise_ops") or []):
            if not isinstance(op, dict) or op.get("op") not in ("edit", "remove"):
                continue
            _prior = op.get("prior_text")
            if not isinstance(_prior, str):
                continue
            for u in _gov40_units:
                _uid = u.get("id")
                if _gov40_executed(_uid):
                    continue                       # frozen prefix (I17/GV-16) — retired text allowed
                if _added_at.get(_uid, -1) > _ri:
                    continue                       # a unit added AFTER this revise is I40-4's domain, not the
                                                   # in-transaction sweep's (GV-15 reconciles existing units only)
                _refs = _gov40_refs(u, _L)
                if _prior in _refs:
                    if op.get("op") == "remove" and _refs == [_prior] and _uid not in _cancelled:
                        rep.fail(f"{_gov40_stem} (sole-ref stranded {_uid})",
                                 f"revise_anchors removed {_prior!r} but unexecuted unit {_uid} binds it "
                                 "as its SOLE ref — re-point it or pair a cancel_unit; it may not be left "
                                 "[] under I20 minItems:1 (GV-15 4c)")
                    else:
                        rep.fail(f"{_gov40_stem} (ref not reconciled {_uid})",
                                 f"revise_anchors {op.get('op')} of {_prior!r} but unexecuted unit "
                                 f"{_uid} still binds the retired text — refs must be rewritten/dropped "
                                 "in the same transaction (GV-15 4a-c; brief/graph mirror)")

    # I40-4 [GV-16] — a unit ADDED by an amendment ordered AFTER a retirement may not cite retired text
    # (amendments are in sorted/chronological filename order; the retiring id is the anchors_retired
    # entry's amendment_ref). The frozen-prefix union (I20/I21/I22) does NOT license a later add.
    _amend_order = {rec.get("id"): idx for idx, (_fn, rec) in enumerate(_amend_recs)}
    for r in _gov_retired:
        _prior = r.get("prior_text")
        _L = r.get("list")
        _ret_amd = r.get("amendment_ref")
        if not isinstance(_prior, str) or _ret_amd not in _amend_order:
            continue
        _ret_idx = _amend_order[_ret_amd]
        for _fn, rec in _amend_recs:
            if _amend_order.get(rec.get("id"), -1) <= _ret_idx:
                continue
            for _uid in (rec.get("units_added") or []):
                u = _gov40_byid.get(_uid)
                if u is not None and _prior in _gov40_refs(u, _L):
                    rep.fail(f"{_gov40_stem} (later unit cites retired {_uid})",
                             f"unit {_uid} was ADDED by {rec.get('id')} (ordered after the {_ret_amd} "
                             f"retirement) yet binds retired text {_prior!r} — the frozen-prefix union "
                             "does not license a later-added unit to cite retired anchors (GV-16)")

    # I40-5 [GV-17] — a revise_anchors `add` op must name >=1 propagation_target OR record
    # propagation:remaining-scope-none; silence at the I23 successor is a FAIL.
    for _fn, rec in _revise_recs:
        if any(isinstance(op, dict) and op.get("op") == "add" for op in (rec.get("revise_ops") or [])):
            if not (rec.get("propagation_targets") or rec.get("propagation") == "remaining-scope-none"):
                rep.fail(f"{_gov40_stem} (added item stranded {rec.get('id')})",
                         "revise_anchors add op names no propagation_targets and records no "
                         "propagation:remaining-scope-none — a mid-run added anchor must close at P8 (GV-17)")

    # I40-6 [GV-18] — ANY op (remove OR edit) whose target NG carries a `violated` row anywhere must
    # route to P7 (disagreement dossier), never a P6 gate approval (a violated-on-PASS row stays an I22
    # FAIL regardless of later edits; GV-16 keeps the old attestation binding).
    _violated_ng = set()
    for _u2 in sorted(unit_subdirs):
        _vp2 = os.path.join(units_dir, _u2, "verify.json")
        if os.path.exists(_vp2):
            try:
                _vd2 = load_json(_vp2)
            except Exception:
                _vd2 = None
            for _row in ((_vd2.get("guardrail_compliance") if isinstance(_vd2, dict) else None) or []):
                if isinstance(_row, dict) and _row.get("status") == "violated" and isinstance(_row.get("non_goal"), str):
                    _violated_ng.add(_row.get("non_goal"))
    for _fn, rec in _revise_recs:
        if rec.get("list") != "non_goals":
            continue
        _trig = (rec.get("origin") or {}).get("trigger") if isinstance(rec.get("origin"), dict) else None
        for op in (rec.get("revise_ops") or []):
            if isinstance(op, dict) and op.get("op") in ("edit", "remove") and op.get("prior_text") in _violated_ng:
                if _trig != "p7_resolution":
                    rep.fail(f"{_gov40_stem} (violated-target {rec.get('id')})",
                             f"revise_anchors {op.get('op')} targets non-goal {op.get('prior_text')!r} "
                             "that a unit already VIOLATED — this must route to P7 (disagreement "
                             "dossier), not a P6 gate approval (GV-18; ESCALATE)")

    # I40-7 [GV-21] — a scope_change add produces a transcript_ref on the amendment + an `added`
    # confirmation record for the appended DoD item (human-confirmed by construction).
    for _fn, rec in _amend_recs:
        if rec.get("scope_change") is True:
            _aid = rec.get("id")
            if _gov_blank(rec.get("transcript_ref")):
                rep.fail(f"{_gov40_stem} (scope_change no transcript {_aid})",
                         "scope_change amendment carries no transcript_ref to its gate residue (GV-21)")
            if not any(r.get("disposition") == "added" and r.get("amendment_ref") == _aid for r in _gov_ic):
                rep.fail(f"{_gov40_stem} (scope_change no confirmation {_aid})",
                         "scope_change amendment appends a DoD item but no `added` item_confirmations "
                         "record references it (amendment_ref) — the appended item is not "
                         "human-confirmed by construction (GV-21)")

    # I40-8 [GV-25] — an autonomous add_units record (human_gate absent/false) must have EVERY dod_refs
    # element human_confirmed once item_confirmations is adopted (downgrade-laundering guard: verbatim
    # presence is not confirmation).
    if _gov_ic_present:
        for _fn, rec in _addunit_recs:
            if rec.get("human_gate") is True:
                continue
            for x in (rec.get("dod_refs") or []):
                if isinstance(x, str) and not _gov_human_confirmed(x, "definition_of_done"):
                    rep.fail(f"{_gov40_stem} (autonomous unconfirmed {rec.get('id')})",
                             f"autonomous add_units cites DoD item {x!r} that is not human_confirmed "
                             "(GV-25 downgrade-laundering guard; even a verbatim-present item needs standing)")

    # I40 success line (armed via a revise record or an adopted governance artifact + no clause failed).
    if ((_revise_recs or _gov_ic_present or _gov_retired) and len(rep.problems) == _gov40_probs0):
        rep.ok(f"{_gov40_stem} ({len(_revise_recs)} revise record(s); gating + ref-reconciliation + "
               "membership-ordering + narrowed autonomy OK)")

    # I9 MISSING VERIFICATION (MUST-FIX D; status-aware per WP6/B10) — a debrief without a verify is a
    # DEFECT everywhere EXCEPT the one legitimate transient: a unit still IN the correction loop at P6.
    # Prime directive 7 mandates validating after each unit's debrief+verify PAIR, and parallel waves keep
    # several units mid-loop; so when phase==P6_EXECUTE_VERIFY and fsm-state marks the unit
    # `executing`/`verifying`, a not-yet-written verify is EXPECTED — emit a NOTE, not a FAIL. Everywhere
    # else (any other phase, any other status, and ALWAYS at P8/DONE) it stays a hard FAIL; I10 still
    # hard-fails unverified units at synthesis and WP5's I2 ledger cross-check catches a dishonest
    # `passed`/`failed` status, so terminal verdicts are unchanged. REVISES I9's firing condition only.
    _fsm_unit_status = {}
    if fsm and isinstance(fsm.get("units"), list):
        for _u in fsm["units"]:
            if isinstance(_u, dict):
                _fsm_unit_status[_u.get("unit_id")] = _u.get("status")
    for uid in sorted(unit_dirs_with_debrief):
        vpath = os.path.join(units_dir, uid, "verify.json")
        if not os.path.exists(vpath):
            _st = _fsm_unit_status.get(uid)
            if phase == "P6_EXECUTE_VERIFY" and _st in ("executing", "verifying"):
                if not args.quiet:
                    print(f"  NOTE  {LABEL_STEM['i9_missing']} (units/{uid}): debrief present, verify PENDING "
                          f"(fsm status {_st!r} at P6) — an in-flight unit mid-loop, not yet a defect")
            else:
                rep.fail(f"{LABEL_STEM['i9_missing']} (units/{uid})",
                         f"debrief present but verify.json is MISSING (fsm status {_st!r}, phase {phase}) — "
                         "an executed unit must be adversarially verified before the loop closes "
                         "(only an executing/verifying unit at P6 is an expected mid-loop NOTE)")
        else:
            vd = unit_docs.get(uid, {}).get("verify")
            if vd is None:
                rep.fail(f"{LABEL_STEM['i9_missing']} (units/{uid})",
                         "verify.json present but INVALID — no usable verdict")
            elif "verdict" not in vd:
                rep.fail(f"{LABEL_STEM['i9_missing']} (units/{uid})", "verify.json has no verdict")
            else:
                rep.ok(f"{LABEL_STEM['i9_present']} (units/{uid}: verdict={vd['verdict']})")

    # I9 verify-without-debrief (IMP-17) — the CONVERSE of the missing-verification check above: a
    # unit dir carrying a verify.json but NO debrief is incoherent (a verifier attested to a unit that
    # produced no debrief to verify). Fail closed. Offline/post-hoc.
    for uid in sorted(unit_subdirs):
        udir = os.path.join(units_dir, uid)
        if (os.path.exists(os.path.join(udir, "verify.json")) or os.path.exists(os.path.join(udir, "verify.md"))) \
           and uid not in unit_dirs_with_debrief:
            rep.fail(f"{LABEL_STEM['i9_verify_wo_debrief']} (units/{uid})",
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
            rep.fail(f"{LABEL_STEM['gbrief']} (units/{uid})",
                     "unit has a debrief/verify but NO brief.json — I5/I6/I11/I12/I16 all key off the "
                     "brief and SILENTLY skip this unit without it (T8: every ready unit has a "
                     "schema-valid brief.json)")
    if phase in ("P8_SYNTHESIS", "DONE") and graph_doc is not None and unit_subdirs:
        for u in graph_doc.get("units", []):
            uid = u.get("id")
            if not os.path.exists(os.path.join(units_dir, uid, "brief.json")):
                rep.fail(f"{LABEL_STEM['gbrief']} (units/{uid})",
                         f"phase {phase}: graph unit has no brief.json — briefs are a Phase-5 "
                         "obligation, present for every unit by synthesis (T8)")
            elif unit_docs.get(uid, {}).get("brief") is None:
                rep.fail(f"{LABEL_STEM['gbrief']} (units/{uid})",
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
                rep.fail(f"{LABEL_STEM['i10_synth']} (units/{uid})",
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
                rep.fail(f"{LABEL_STEM['i10_synth']} (units/{uid})",
                         f"phase {phase}: {', '.join(missing)} — every graph unit must be "
                         "debriefed and PASS-verified before DONE (T12)")
            else:
                rep.ok(f"{LABEL_STEM['i10_synth']} (units/{uid}: debriefed + PASS)")
        # Out-of-graph unit dirs (extra work not declared in graph.json) — keep the existing
        # debrief-keyed completeness check so a stray non-PASS unit can't slip through at DONE.
        for uid in sorted(unit_dirs_with_debrief - set(graph_unit_ids)):
            vd = unit_docs.get(uid, {}).get("verify")
            if not vd or vd.get("verdict") != "PASS":
                got = (vd or {}).get("verdict", "MISSING")
                rep.fail(f"{LABEL_STEM['i10_synth']} (units/{uid})",
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
                rep.fail(f"{LABEL_STEM['i11_global_reg']}", f"~/.claude/dag/tags.json not valid JSON: {e}")
            if _traw is not None:
                _tschema = schemas.get("tags.schema.json")
                errs = validate(_traw, _tschema) if _tschema is not None else []
                if errs:
                    for e in errs:
                        rep.fail(f"{LABEL_STEM['i11_global_reg']}", f"~/.claude/dag/tags.json: {e}")
                else:
                    global_tags = {t for t in _traw.get("tags", []) if isinstance(t, str)}
                    rep.ok(f"{LABEL_STEM['i11_global_reg']} loaded ({len(global_tags)} tag(s) from "
                           f"~/.claude/dag/tags.json — widening V_tag_eff)")
        v_tag_eff = v_tag | global_tags   # V_tag_eff = global ∪ run_local (project tier admits trivially)

        gunits = graph_doc.get("units", [])
        unit_tags = {u.get("id"): set(u.get("tags", [])) for u in gunits}
        tag_ok = True
        for u in gunits:
            bad = sorted(t for t in u.get("tags", []) if t not in v_tag_eff)
            if bad:
                tag_ok = False
                rep.fail(f"{LABEL_STEM['i11_tag_vocab']} (graph)", f"{u.get('id')} tags {bad} not in V_tag_eff {sorted(v_tag_eff)}")
        for uid, d in unit_docs.items():
            b = d.get("brief")
            if b:
                bad = sorted(t for t in b.get("tags", []) if t not in v_tag_eff)
                if bad:
                    tag_ok = False
                    rep.fail(f"{LABEL_STEM['i11_tag_vocab']} (units/{uid}/brief)", f"tags {bad} not in V_tag_eff {sorted(v_tag_eff)}")
        if tag_ok:
            rep.ok(f"{LABEL_STEM['i11_tag_vocab']} (all tags drawn from V_tag_eff, |V_tag_eff|={len(v_tag_eff)}"
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
            # G8 (WP5): the import carve-out (advisory tier + exemption from the >=2-carrier admission
            # gate) may NOT be claimed by id spelling alone. An entry is a genuine import iff it was
            # actually loaded from a store THIS run (eid in store_ids) OR it carries an explicit
            # origin.store provenance stamp (written by the Phase-0.5 intake). A G#-id entry with
            # NEITHER is forged provenance — fail CLOSED so a run-local L1 renamed G7 cannot dodge I12.
            def _import_provenance_ok(E, eid):
                # WP-C/B2: an origin.store stamp is trusted ONLY when CORROBORATED by actual store
                # membership (eid in store_ids — the loaders now record even shadowed/folded ids, A4).
                # An uncorroborated origin.store self-stamp grants NOTHING; the id-in-store test is the
                # single source of import provenance, so a run-local entry can no longer self-exempt.
                return eid in store_ids
            active, advisory = [], []
            for E in learnings:
                eid = E.get("id") if isinstance(E, dict) else None
                _o = E.get("origin") if isinstance(E, dict) else None
                _stamped = isinstance(_o, dict) and _o.get("store") in ("user", "project")
                # WP-C/B2: an origin.store stamp with NO corroborating store entry is forged provenance
                # — closing the sibling of the G8 id-spelling hole (adding origin.store to a run-local
                # entry used to (a) exempt it from I12 propagation and (b) defeat the G8 import check).
                if _stamped and eid not in store_ids:
                    rep.fail(f"{LABEL_STEM['i12_provenance']}",
                             f"{eid} carries an origin.store={_o.get('store')!r} stamp but its id is in NO "
                             "learnings store (uncorroborated) — an origin.store self-stamp cannot forge "
                             "import provenance (B2)")
                if isinstance(eid, str) and eid.startswith("G") and not _import_provenance_ok(E, eid):
                    rep.fail(f"{LABEL_STEM['i12_provenance']}",
                             f"{eid} claims the import carve-out (G#-id) but was not loaded from a store "
                             "and carries no corroborated origin.store provenance — the advisory/exempt tier "
                             "cannot be forged by id spelling (G8)")
                _imported = _import_provenance_ok(E, eid) if isinstance(eid, str) else (eid in store_ids)
                if isinstance(E, dict) and _imported and not _is_regrounded(E):
                    advisory.append(E)
                else:
                    active.append(E)
            for E in advisory:
                rep.ok(f"{LABEL_STEM['advisory_import']}: {E.get('id')} — imported cross-run "
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
                    rep.fail(f"{LABEL_STEM['i12_since_wave']}",
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
                    rep.ok(f"{LABEL_STEM['i12_model_narrow']}: {eid} scope.model={_e_model!r} does not match run "
                           f"model {run_model!r} — EXCLUDED from propagation this run (narrowing conjunct)")
                    continue
                # G1 FLAG: authored-vs-imported admission carve-out (widens I11/I12 domain — see
                # 04-global.md/roadmap §d). The >=2-current-run-carrier admission gate below is a
                # RE-GENERALIZATION test: it rejects a one-off authored THIS run before it can bind
                # later units. An IMPORTED/GLOBAL entry is ALREADY generalized (it survived a prior
                # run's admission and was persisted), so re-imposing the >=2-run re-proof would
                # WRONGLY reject it. An entry is imported/global iff its id was loaded from the
                # project/global store rather than authored in-run (`eid in store_ids`), OR it bears
                # the global-scoped `G#` id marker — but ONLY with genuine provenance (WP5/G8: store
                # membership or an origin.store stamp; a bare G#-id already FAILed I12 provenance above).
                # Such entries are EXEMPT from the >=2-run re-proof — but are STILL FULLY governed by
                # the propagation predicate below (force-inject only where the tag actually appears).
                # The exemption is EXPLICIT (reported as a PASS-level carve-out line), NEVER silent.
                _is_imported = _import_provenance_ok(E, eid)
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
                        rep.fail(f"{LABEL_STEM['i12_selector']}", f"{eid} scope.applies_to has a non-string selector {sel!r}")
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
                        rep.fail(f"{LABEL_STEM['i12_selector']}",
                                 f"{eid} scope.applies_to selector {sel!r} is not a recognized kind "
                                 "(all | U0X | tag:T) — `phaseN` was removed as unevaluable (BRK-09)")
                        continue
                    if not admissible:                  # admission gate (generalizability re-proof)
                        if _is_imported:
                            # G1 FLAG carve-out: already-generalized imported/global entry — EXEMPT
                            # from the re-proof, still propagation-governed (never silent).
                            rep.ok(f"{LABEL_STEM['i12_admission_carveout']}: {eid} scope {sel} is imported/global "
                                   f"({'store-loaded' if eid in store_ids else 'G#-id'}) — exempt from the "
                                   f"generalizability re-proof ({adm_desc}); still governed by the propagation predicate")
                        else:
                            prop_ok = False
                            rep.fail(f"{LABEL_STEM['i12_admission_gate']}",
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
                            rep.fail(f"{LABEL_STEM['i12_propagation']}",
                                     f"units/{uid} {match_desc} at wave {w} "
                                     f">= since_wave {since}: MUST list {eid} in learnings_applied "
                                     f"(has {b.get('learnings_applied')})")
            if prop_ok:
                rep.ok(f"{LABEL_STEM['i12_propagation']} ({len(active)} active entr(y/ies): admission + selector-scope "
                       f"(all|U0X|tag) propagation hold{f'; {len(advisory)} advisory import(s) not force-injected (03/P4)' if advisory else ''})")
        elif not args.quiet:
            print("  SKIP  I12 learnings propagation: no learnings.json present")

    # I7 disagreement: exactly one recommended option
    for uid, d in unit_docs.items():
        dis = d.get("disagreement")
        if dis is not None:
            n = sum(1 for o in dis.get("options", []) if o.get("recommended") is True)
            if n == 1:
                rep.ok(f"{LABEL_STEM['i7_single_rec']} (units/{uid})")
            else:
                rep.fail(f"{LABEL_STEM['i7_single_rec']} (units/{uid})",
                         f"{n} options marked recommended (need exactly 1)")

    # I8 no OPEN material ambiguity
    cl = docs.get("clarifications")
    if cl:
        open_material = [r for r in cl.get("ambiguity_register", [])
                         if r.get("materiality") == "material" and not r.get("resolved", False)]
        if open_material:
            rep.fail(f"{LABEL_STEM['i8_open']}",
                     f"{len(open_material)} unresolved material item(s): "
                     + ", ".join(str(r.get('id')) for r in open_material))
        else:
            rep.ok(f"{LABEL_STEM['i8_noopen']}")

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
            rep.fail(f"{LABEL_STEM['idod']}",
                     "a post-clarification artifact (cartography / graph / units / synthesis) is "
                     "present (Phase 3+) but no VALID clarifications.json carrying a non-empty "
                     "definition_of_done + non_goals (file absent or schema-invalid) — Definition "
                     "of Done and Non-Goals are required clarification outputs once any structure "
                     "beyond clarification exists")
        else:
            missing = [k for k in ("definition_of_done", "non_goals")
                       if not _nonempty_strlist(cl.get(k))]
            if missing:
                rep.fail(f"{LABEL_STEM['idod']}",
                         f"clarifications.json lacks non-empty {missing} — Definition of Done and "
                         "Non-Goals are required once any post-clarification artifact "
                         "(cartography / graph / units / synthesis) exists")
            else:
                rep.ok(f"{LABEL_STEM['idod']} (non-empty definition_of_done + non_goals)")

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
        rep.fail(f"{LABEL_STEM['i2_ledger']}",
                 "fsm-state.json absent but run artifacts exist "
                 f"({_i2_signals}) — the FSM state must live on disk")

    # I2 ledger-is-truth extensions (WP5) — the ledger must not LIE about what the artifacts show.
    # G4: a units[] status of passed/failed must match the unit's verify.json verdict PASS/FAIL, and
    #     loop.last_verdict must match loop.unit_id's verdict; G10: fsm units[] must be a subset of the
    #     graph units (+ retired ids); G5: artifacts imply a minimum phase (the ledger can't under-report
    #     `phase` to duck phase-keyed checks). All post-hoc/offline; REVISES the I2 surface upward.
    _STATUS_VERDICT = {"passed": "PASS", "failed": "FAIL"}
    if fsm and isinstance(fsm.get("units"), list):
        for _u in fsm["units"]:
            if not isinstance(_u, dict):
                continue
            _exp_v = _STATUS_VERDICT.get(_u.get("status"))
            if _exp_v is None:
                continue                       # pending/retired/etc — no terminal verdict to match
            _vd = unit_docs.get(_u.get("unit_id"), {}).get("verify")
            if _vd is None:
                # WP-C/C5: fail CLOSED — a TERMINAL ledger status (passed/failed) with no VALID
                # verify.json is an unverifiable claim (the ledger asserts a verdict no verifier
                # produced). The old `continue` let a run parked at P6 claim `U0X: passed` with zero
                # evidence and still exit 0 (I9 only fires when a debrief exists; I10 only at P8/DONE).
                # `executing`/`verifying` are NOT terminal (they map to None above), so the mid-loop
                # NOTE case is untouched.
                rep.fail(f"{LABEL_STEM['i2_status_verdict']} (units/{_u.get('unit_id')})",
                         f"fsm units[] status {_u.get('status')!r} (terminal, expects verdict {_exp_v}) but "
                         "no VALID verify.json — a passed/failed ledger status must be backed by the "
                         "verifier's verdict")
                continue
            if _vd.get("verdict") != _exp_v:
                rep.fail(f"{LABEL_STEM['i2_status_verdict']} (units/{_u.get('unit_id')})",
                         f"fsm units[] status {_u.get('status')!r} but verify.json verdict={_vd.get('verdict')!r} "
                         f"(expected {_exp_v}) — the ledger must match the verifier")
            else:
                rep.ok(f"{LABEL_STEM['i2_status_verdict']} (units/{_u.get('unit_id')}: status matches verdict {_exp_v})")
    if fsm and isinstance(fsm.get("loop"), dict):
        _lp = fsm["loop"]
        _lvd = unit_docs.get(_lp.get("unit_id"), {}).get("verify")
        if _lp.get("last_verdict") is not None and _lvd is not None and _lvd.get("verdict") != _lp.get("last_verdict"):
            rep.fail(f"{LABEL_STEM['i2_status_verdict']}",
                     f"fsm loop.last_verdict={_lp.get('last_verdict')!r} != {_lp.get('unit_id')} "
                     f"verify.json verdict={_lvd.get('verdict')!r} — the ledger must match the verifier")
    # B5 (WP-A): duplicate unit_id in fsm-state.units[] makes every last-wins consumer
    # (_fsm_unit_status for the I9 mid-loop NOTE, _unit_retries for the I4/escalate cross-checks,
    # the I2 subset check) ORDER-DEPENDENT — a shadowing duplicate can downgrade an I9 FAIL to a NOTE.
    # This mirrors the I3 graph.json unit-id uniqueness fix (round 1); JSON Schema cannot express
    # cross-item uniqueness on a derived key, so the validator is the only enforcement point.
    # Offline/post-hoc — gates no transition.
    if fsm and isinstance(fsm.get("units"), list):
        _fids = [_u.get("unit_id") for _u in fsm["units"] if isinstance(_u, dict) and _u.get("unit_id") is not None]
        if len(_fids) != len(set(_fids)):
            _fdupes = sorted({x for x in _fids if _fids.count(x) > 1})
            rep.fail(f"{LABEL_STEM['i2_fsm_unit_unique']}",
                     f"duplicate unit_id(s) {_fdupes} in fsm-state.units[] — ids must be unique "
                     "(status/retries consumers collapse duplicates last-wins, making I9/I4 verdicts "
                     "order-dependent)")
        else:
            rep.ok(f"{LABEL_STEM['i2_fsm_unit_unique']} ({len(_fids)} unique fsm unit_id(s))")
    if fsm and isinstance(fsm.get("units"), list) and graph_doc is not None:
        _allowed_ids = {u.get("id") for u in graph_doc.get("units", [])}
        for _ru in (graph_doc.get("retired_units", []) or []):   # retired units legitimately leave units[]
            if isinstance(_ru, dict) and _ru.get("id"):
                _allowed_ids.add(_ru.get("id"))
        _phantom = sorted(_u.get("unit_id") for _u in fsm["units"]
                          if isinstance(_u, dict) and _u.get("unit_id") not in _allowed_ids)
        if _phantom:
            rep.fail(f"{LABEL_STEM['i2_units_subset']}",
                     f"fsm-state units[] names {_phantom} absent from graph units[] (and not retired) "
                     "— the ledger must not invent units")
        else:
            rep.ok(f"{LABEL_STEM['i2_units_subset']} ({len(fsm['units'])} fsm unit(s) all in graph or retired)")
    # G5: artifact-driven phase floor (mirrors the I-dod / G-personas artifact triggers).
    _PHASE_RANK = {"P0_BOOTSTRAP": 0, "P1_PERSONAS": 1, "P2_CLARIFICATION": 2, "P3_CARTOGRAPHY": 3,
                   "P4_DECOMPOSITION": 4, "P5_BRIEFING": 5, "P6_EXECUTE_VERIFY": 6,
                   "P7_DISAGREEMENT_GATE": 7, "P8_SYNTHESIS": 8, "DONE": 9}
    _prank = _PHASE_RANK.get(phase)
    _executed = bool(unit_dirs_with_debrief) or any(unit_docs.get(u, {}).get("verify") for u in unit_docs)
    if _executed and _prank is not None:
        if _prank < 5:
            rep.fail(f"{LABEL_STEM['i2_phase_floor']}",
                     f"executed unit artifacts (debrief/verify) present but fsm phase={phase!r} (rank {_prank}) "
                     "< P5_BRIEFING — the ledger under-reports the phase to duck phase-keyed checks")
        if gates.get("decomposition_approved") is not True:
            rep.fail(f"{LABEL_STEM['i2_phase_floor']}",
                     "executed unit artifacts present but gates.decomposition_approved != true — "
                     "execution cannot precede the decomposition gate")
    if _exists("SYNTHESIS.md") and _prank is not None and phase not in ("P8_SYNTHESIS", "DONE"):
        rep.fail(f"{LABEL_STEM['i2_phase_floor']}",
                 f"SYNTHESIS.md present but fsm phase={phase!r} not in {{P8_SYNTHESIS, DONE}} — "
                 "synthesis is a Phase-8 artifact")

    # B9 (WP6): ESCALATE loop-state provenance — a unit recorded in loop-state ESCALATE must carry one of
    # the THREE documented origins: retries==2 with a FAIL verify (LT5), a DISAGREE verify (LT6), or a
    # disagreement dossier citing amendment-fuel exhaustion (the BGA third origin). Without this, an
    # ESCALATE loop-state is unverifiable provenance. Post-hoc/offline; gates no transition — PRESERVES
    # termination (fuel exhaustion halts either way). Inert unless a unit is actually in ESCALATE.
    _escalated = set()
    _unit_retries = {}
    if fsm and isinstance(fsm.get("loop"), dict):
        if fsm["loop"].get("state") == "ESCALATE":
            _escalated.add(fsm["loop"].get("unit_id"))
        if fsm["loop"].get("unit_id"):
            _unit_retries[fsm["loop"].get("unit_id")] = _as_int(fsm["loop"].get("retries"))
    if fsm and isinstance(fsm.get("units"), list):
        for _u in fsm["units"]:
            if not isinstance(_u, dict):
                continue
            if _u.get("loop_state") == "ESCALATE" or _u.get("status") == "escalated":
                _escalated.add(_u.get("unit_id"))
            if _u.get("retries") is not None:
                _unit_retries[_u.get("unit_id")] = _as_int(_u.get("retries"))
    for _euid in sorted(x for x in _escalated if x):
        _ev = unit_docs.get(_euid, {}).get("verify")
        _everdict = _ev.get("verdict") if isinstance(_ev, dict) else None
        _er = _unit_retries.get(_euid)
        _why = None
        if _everdict == "DISAGREE":
            _why = "DISAGREE verify (LT6)"
        elif _everdict == "FAIL" and _er == 2:
            _why = "retries==2 with FAIL verify (LT5)"
        else:
            # WP-C/C3: the amendment-fuel-exhaustion origin (BGA third origin) is proven by STRUCTURAL
            # evidence, not a substring grep over dossier prose. The old check matched "fuel" + ("exhaust"
            # | "amendment") anywhere in the dossier — so a dossier explicitly DENYING fuel use ("burned
            # NO fuel at all") satisfied it. Require the fsm-state expansion object to show fuel actually
            # exhausted: expansion present AND fuel_remaining == 0 (I18 accounting). Prose is no longer
            # sufficient; migration note: an ESCALATE that formerly relied on dossier wording now needs
            # the structural fuel evidence (consistent with F1's version-skew policy).
            _exp = fsm.get("expansion") if isinstance(fsm, dict) else None
            if isinstance(_exp, dict) and _as_int(_exp.get("fuel_remaining")) == 0:
                _why = "amendment fuel exhausted (expansion.fuel_remaining == 0; BGA origin)"
        if _why:
            rep.ok(f"{LABEL_STEM['escalate_origin']} (units/{_euid}: {_why})")
        else:
            rep.fail(f"{LABEL_STEM['escalate_origin']} (units/{_euid})",
                     f"unit is in loop-state ESCALATE but no valid origin (verify verdict={_everdict!r}, "
                     f"retries={_er}) — ESCALATE requires (retries==2 ∧ FAIL) or DISAGREE or structural "
                     "amendment-fuel exhaustion (expansion.fuel_remaining == 0); the three T10 origins")

    if post_p1:
        missing = []
        if docs.get("personas") is None:
            missing.append("no VALID personas.json")
        if gates.get("personas_confirmed") is not True:
            missing.append("gates.personas_confirmed != true (needs a valid fsm-state.json)")
        if missing:
            rep.fail(f"{LABEL_STEM['gpersonas_nonskip']}",
                     f"run shows post-Phase-1 work {post_p1} but {'; '.join(missing)} — the human "
                     "persona-selection gate (Phase 1) cannot be skipped; it precedes all these "
                     "artifacts (T2)")
        else:
            rep.ok(f"{LABEL_STEM['gpersonas_nonskip']} (post-Phase-1 work present; roster confirmed + personas.json valid)")
    elif fsm and gates.get("personas_confirmed") and docs.get("personas") is None:
        # Flag set true with no roster and no downstream work yet — still a fail-closed tie.
        rep.fail(f"{LABEL_STEM['gpersonas_failclosed']}",
                 "gates.personas_confirmed=true but no VALID personas.json (T2)")

    # Gate ordering: phase requires prior gates true. personas_confirmed is the FIRST
    # gate (Phase 1) and is required from P2 onward — the human persona gate is not skippable.
    # D-06/BRK-13: `signoff_confirmed` (the Phase-8 human sign-off, G-signoff/T12) is added to the
    # DONE row, so a run cannot reach phase DONE without the flag — closing the skip-the-human hole
    # where the validator previously could not tell sign-off happened. Like personas_confirmed, this
    # is a POST-HOC/OFFLINE gate-ordering predicate over the emitted fsm-state.json (it gates no live
    # transition and never guards LT7); the flag is a human attestation whose PRESENCE — not
    # genuineness — is checked. REVISES the gate contract: a DONE run without it is now INVALID.
    REQUIRED_GATES = {
        "P2_CLARIFICATION": ["personas_confirmed"],
        "P3_CARTOGRAPHY": ["personas_confirmed", "clarification_resolved"],
        "P4_DECOMPOSITION": ["personas_confirmed", "clarification_resolved", "cartography_done"],
        "P5_BRIEFING": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P6_EXECUTE_VERIFY": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P7_DISAGREEMENT_GATE": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "P8_SYNTHESIS": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved"],
        "DONE": ["personas_confirmed", "clarification_resolved", "cartography_done", "decomposition_approved", "signoff_confirmed"],
    }
    if fsm:
        gates = fsm.get("gates", {})
        need = REQUIRED_GATES.get(phase, [])
        missing = [g for g in need if not gates.get(g, False)]
        if missing:
            rep.fail(f"{LABEL_STEM['gate_ordering']}", f"phase {phase} requires gates {missing} = true")
        elif need:
            rep.ok(f"{LABEL_STEM['gate_ordering']} (phase {phase}: prior gates satisfied)")

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
