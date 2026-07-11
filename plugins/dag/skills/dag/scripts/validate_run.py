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
        _i20_dset = {x for x in _i20_clar.get("definition_of_done", []) if isinstance(x, str)}
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
        _i21_ngset = {x for x in _i20_clar.get("non_goals", []) if isinstance(x, str)}
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
