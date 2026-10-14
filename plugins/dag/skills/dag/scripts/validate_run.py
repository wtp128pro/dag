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

# Sibling import (1.15.0 blast radius): frame_match.py is the ONE path matcher (the frame-pattern
# language and the pattern-overlap check); this file must never hold a copy of it. HERE is put on
# sys.path explicitly (idempotently) so the import also resolves under `python3 -I` / -P /
# PYTHONSAFEPATH, which do not prepend the script's directory. A missing or broken matcher is an
# environment error (exit 3), never a traceback.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    import frame_match
except ImportError as _fm_err:
    sys.stderr.write(f"validate_run.py: cannot import frame_match from {HERE}: {_fm_err}\n")
    sys.exit(3)

TOP_ARTIFACTS = {
    "personas.json": "personas.schema.json",
    "clarifications.json": "clarifications.schema.json",
    "cartography.json": "cartography.schema.json",
    "graph.json": "graph.schema.json",
    "fsm-state.json": "fsm-state.schema.json",
    "sources.json": "sources.schema.json",
    "dialogues.json": "dialogues.schema.json",
    "machine-decisions.json": "machine-decisions.schema.json",
    # 1.15.0 blast radius: whole-run integration record (integrate.py) and the run's blast config.
    "integration.json": "integration.schema.json",
    "blast-config.json": "blast-config.schema.json",
}
UNIT_ARTIFACTS = {
    "brief.json": "brief.schema.json",
    "debrief.json": "debrief.schema.json",
    "verify.json": "verify.schema.json",
    "disagreement.json": "disagreement.schema.json",
    # 1.15.0 blast radius: the unit's captured FILE footprint (footprint.py). Validate-if-present here;
    # whether it MUST exist is decided by the version-gated I60-3, which also raw-reads it so a
    # schema-invalid footprint still FAILs there.
    "footprint.json": "footprint.schema.json",
    # 1.15.0 blast radius: the unit's impact scan (impact_scan.py). Validate-if-present, like the
    # footprint; whether it MUST exist is decided by the version-gated I62-1, which raw-reads it too.
    "impact.json": "impact.schema.json",
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
#   * "hoisted-var" (U25) => hoisted like the absent case AND read back from
#                 LABEL_STEM[<key>] into a local alias, so the rep.ok/rep.fail call
#                 site carries a VARIABLE rather than the literal stem. Recorded
#                 distinctly because the absent case's promise ("the stem IS
#                 interpolated into a rep label") is satisfied by a literal at the
#                 call site, and a reader grepping for the stem text will not find
#                 it there; the registry is the only copy of the string.
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
    # FSM invariants — panel dissent accounting / evidence digest integrity (cross-repo-lessons 1.11.0; U05/U07)
    {"key": "i41_dissent", "stem": "I41 panel dissent", "invariant": "I41"},
    {"key": "note_i41", "stem": "N-I41", "invariant": "I41", "emitted_via": "print"},
    {"key": "i42_digest", "stem": "I42 evidence digest", "invariant": "I42"},
    {"key": "note_i42", "stem": "N-I42", "invariant": "I42", "emitted_via": "print"},
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
    {"key": "i43_currency", "stem": "I43 verification currency", "invariant": "I43"},
    {"key": "note_i43", "stem": "N-I43 verification currency", "invariant": "I43", "emitted_via": "print"},
    {"key": "i44_signoff_closure", "stem": "I44 sign-off closure", "invariant": "I44"},
    {"key": "note_i44", "stem": "N-I44 sign-off closure", "invariant": "I44", "emitted_via": "print"},
    {"key": "i45_version_skew", "stem": "N-I45 version-skew visibility", "invariant": "I45", "emitted_via": "print"},
    {"key": "i46_nonconverged_pass", "stem": "I46 non-converged PASS", "invariant": "I46"},
    {"key": "note_i46", "stem": "N-I46 non-converged PASS", "invariant": "I46", "emitted_via": "print"},
    {"key": "note_i47", "stem": "N-I47 ledger desync at sign-off", "invariant": "I47", "emitted_via": "print"},
    # FSM invariants — case-set contract (independent-test-authorship 1.13.0; U24 authors, U25 registers)
    {"key": "i48_case_set", "stem": "I48 case-set contract", "invariant": "I48", "emitted_via": "hoisted-var"},
    # FSM invariants — drift & autonomy (1.14.0). Every one is an OFFLINE, POST-HOC predicate over
    # emitted artifacts: none appears in a transition-admission path and none is a live guard on the
    # correction loop's sole back-edge LT7 (RETRY->EXECUTE), where a guard that can be false leaves
    # RETRY with no enabled out-edge => deadlock, breaking Claim D of the termination proof.
    {"key": "i49_horizon", "stem": "I49 horizon record", "invariant": "I49"},
    {"key": "i50_prose_bounds", "stem": "I50 prose bounds", "invariant": "I50"},
    {"key": "note_i50", "stem": "N-I50 prose bounds", "invariant": "I50", "emitted_via": "print"},
    {"key": "i51_machine_gate", "stem": "I51 machine-decision channel", "invariant": "I51"},
    {"key": "i52_projection", "stem": "I52 projection ceiling", "invariant": "I52"},
    {"key": "i53_directive", "stem": "I53 directive provenance", "invariant": "I53"},
    {"key": "i54_clock", "stem": "I54 deliverable clock", "invariant": "I54"},
    {"key": "i56_starvation", "stem": "I56 requirement-starvation disclosure", "invariant": "I56"},
    {"key": "note_i56", "stem": "N-I56 requirement-starvation disclosure", "invariant": "I56", "emitted_via": "print"},
    {"key": "note_i57", "stem": "N-I57 run composition", "invariant": "I57", "emitted_via": "print"},
    {"key": "i58_resequence", "stem": "I58 re-sequencing eligibility", "invariant": "I58"},
    {"key": "i59_obligation_source", "stem": "I59 obligation source-naming", "invariant": "I59"},
    # FSM invariants — blast radius (1.15.0). Every one is an OFFLINE, POST-HOC predicate over
    # emitted artifacts (graph frames, brief frames, units/<U>/footprint.json, fsm-state.blast):
    # none appears in a transition-admission path and none is a live guard on the correction loop's
    # sole back-edge LT7 (RETRY->EXECUTE). Armed only on runs stamped >= _BLAST_SHIP.
    {"key": "i60_write_scope", "stem": "I60 write scope", "invariant": "I60", "emitted_via": "hoisted-var"},
    {"key": "i61_wave_disjoint", "stem": "I61 wave write disjointness", "invariant": "I61", "emitted_via": "hoisted-var"},
    {"key": "note_i61", "stem": "N-I61 declared frame overlap", "invariant": "I61", "emitted_via": "print"},
    {"key": "i62_impact", "stem": "I62 impact settled", "invariant": "I62", "emitted_via": "hoisted-var"},
    {"key": "i63_replay", "stem": "I63 end re-run", "invariant": "I63", "emitted_via": "hoisted-var"},
    {"key": "i64_integration", "stem": "I64 integration", "invariant": "I64", "emitted_via": "hoisted-var"},
    {"key": "note_i64", "stem": "N-I64 blast accepted", "invariant": "I64", "emitted_via": "print"},
    {"key": "note_i65", "stem": "N-I65 blast summary", "invariant": "I65", "emitted_via": "print"},
]
LABEL_STEM = {e["key"]: e["stem"] for e in LABELS}


def _frame_canon(frame):
    """Canonical, order-insensitive form of a unit `frame` (graph.json units[].frame / brief.json frame)
    for equality tests: None when absent; every list value becomes its members sorted by their JSON
    text; any other value is kept as-is. Never raises on a wrong-typed frame (a non-object compares by
    its JSON text), so a drifted or malformed frame is a mismatch, not a traceback."""
    if frame is None:
        return None
    if not isinstance(frame, dict):
        return ("<non-object>", json.dumps(frame, sort_keys=True, default=str))
    canon = {}
    for key, val in frame.items():
        if isinstance(val, list):
            canon[key] = sorted(json.dumps(x, sort_keys=True, default=str) for x in val)
        else:
            canon[key] = val
    return canon

# N-I45 version-skew visibility (P3) — shadow accumulator of version-gated ARMS that THIS run's own
# `validator_version` stamp suppressed while the arm's non-version precondition HELD. Module-level per
# spec §3.1(1); `main()` clears it at entry to `_skew_record`'s definition site so a repeated in-process
# main() call cannot accumulate across runs. NOTHING existing is renamed and nothing reads _SKEW except
# the exit-neutral NOTE emitted immediately before `return _finish(rep)` — it touches neither
# rep.problems nor rep.checked, so it can never move an exit code. THE TWO SINKS ARE CITED BY CONTENT,
# never by offset (§9-R18 caught the previous form asserting `:507-518`, which is the tail of the LABELS
# list and holds no sink at all): `grep -n 'self\.problems\.append\|self\.checked\.append' validate_run.py`
# -> exactly 2 hits, the only mutations of either list outside `Report.__init__`.
_SKEW = []

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
            # READABILITY PROBE (top of the loop, before ANY per-unit read). A units/<id>/ the
            # process cannot read fails this block TWO ways, and the quieter one arrives first:
            # os.path.isdir() returns True (stat only needs the PARENT), the os.path.exists()
            # probes below return a SILENT False so the unit reads as EMPTY and is dropped, and
            # only the os.listdir() further down raises — aborting main() before any RESULT: line
            # and silently disabling every predicate after it. So probe by ATTEMPTING the read
            # (os.access() lies under some mount/container configurations and would re-introduce
            # the silent path), emit a row NAMING the unit, and skip it: unreadability is
            # REPORTED, never inferred from absence. The except clause below names the whole error
            # CLASS (EACCES, EIO, ELOOP, ENOENT on a racing delete, …) rather than the single
            # PermissionError that reproduced — and this comment deliberately does NOT spell that
            # class's name, so a token grep over this block cannot be satisfied by prose while the
            # clause itself is narrowed. uid stays in unit_subdirs so the structural triggers that read it
            # (A8/I-dod) keep firing fail-closed — a dir we cannot read is not a dir that is absent.
            try:
                udir_entries = sorted(os.listdir(udir))
            except OSError as e:
                rep.fail(f"units/{uid}/ unreadable",
                         f"unit directory could not be read ({e.__class__.__name__}: {e}); "
                         f"unit {uid} was SKIPPED — its artifacts are unvalidated, so treat this "
                         f"run as unchecked for {uid} rather than as a unit with no work")
                continue
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
            # Reuses the readability probe's listing rather than re-reading the directory: the
            # probe above is the ONLY os.listdir of udir now, so this line cannot raise even if
            # the directory's mode changes mid-run (the crash locus that reproduced).
            for prel in sorted(f for f in udir_entries
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
                # 1.15.0: the declared write scope is frozen content too (each list compared as a set).
                if _frame_canon(gu.get("frame")) != _frame_canon(b.get("frame")):
                    _mism.append("frame differs from brief frame")
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

    # N-I45 (P3 §3.1) — the recorder for the skew shadow count. Records an arm as STAMP-SUPPRESSED iff
    # its non-version precondition HELD while the semver comparison returned False; a suppressed arm is
    # therefore an UPPER BOUND on suppressed FAILs (an armed clause may well have passed) — §3.2/L16.
    # SCOPE NOTE (declared deviation from §3.1(1)'s "module-level ... recorder helper"): `_i27_semver_ge`
    # is itself a `main()`-local closure (`grep -n '^ *def _i27_semver_ge' validate_run.py` -> exactly 1
    # hit; the LEADING-`def` anchor is load-bearing, because the bare string ALSO matches this very
    # comment and would report 2 —
    # cited by CONTENT, never by offset — the `:2688` this line used to carry was already off by one
    # against the def it named), so a module-level recorder could not call the ONE
    # canonical semver comparison without duplicating its parser — a divergence risk worse than the scope
    # difference. The ACCUMULATOR is module-level exactly as specified; only the def is nested, and the
    # signature is verbatim §3.1(1). P3 READS `validator_version` (it is P3's subject matter) but P3's
    # own emission is not gated on the stamp being >= anything: calling P3 "version-gated" is a category
    # error (§3.4). The dev-time completeness assertion lives in spec_check.py SC8 (§3.1(4)).
    del _SKEW[:]

    def _skew_record(arm_id, precondition_held, ship, stamp):
        if precondition_held and not _i27_semver_ge(stamp, ship):
            _SKEW.append({"arm": arm_id, "ship": ship})

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
    _skew_record("I27-T1", _i27_struct, _I27_SHIP, _i27_ver)          # N-I45 shadow count (P3 §3.1(2))

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
    _skew_record("I35-I40-T1", _i27_struct, _DLG_SHIP, _dlg_ver)      # N-I45 shadow count (P3 §3.1(2))
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
    _skew_record("I38-T1v", True, _AF_SHIP, _af_ver)            # N-I45 shadow count; stamp-only arm => precondition True
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
    _skew_record("I39-4-semver1", True, _GOV_SHIP, _gov_ver)    # N-I45 shadow count; stamp-only arm => precondition True
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

    # ---- I41 panel dissent accounting & adjudication (cross-repo-lessons 1.11.0; U05/U07) ----
    # invariant-spec.md §2 (run-experience candidate (b); DAG-L11(c); DAG-L4; R15 kernel; AO-5). The hole:
    # I16 (:1568-1677) forces `top_verdict == discrete majority`, so on a [PASS,PASS,FAIL] panel the ONLY
    # legal top verdict is PASS, and I6 (:1463-1478) lets a PASS carry only `minor` — a dissenting lens'
    # major finding must therefore be downgraded, dropped or buried in prose, and every one of those is
    # invisible to every shipped predicate. I41 makes the accounting auditable. OFFLINE post-hoc predicate
    # over emitted artifacts: reads units/<uid>/verify.json RAW, gates NO FSM transition, is evaluated on
    # NO edge and **NEVER guards LT7** (the correction loop's sole back-edge — a live guard there leaves
    # RETRY with no enabled out-edge and deadlocks, breaking Property 2 Claim D), writes no `retries` and
    # no `fuel`, adds no state/edge/gate flag => PRESERVES the termination proof (Claims A-D) and
    # AO-1/-2/-4/-6/-7; `formal/` byte-untouched (no run_formal.sh re-run). THREE REVISES are carried
    # openly (formal-models.md §1.11.0, with migration arguments): (i) **AO-5 doctrine** — a BOUNDED
    # intra-node re-poll becomes a sanctioned PRE-escalation path; capped by the EXISTING verify_rounds<=3
    # (I16-(c), byte-untouched — I41 adds no bound and no counter), and I41-4c makes "re-run the dissenter
    # until it flips" (exactly what AO-5 prohibits) a hard FAIL where it was previously unconstrained.
    # (ii) **the I16 verify ARTIFACT CONTRACT** — a verify recording PASS + a dissenting member + no
    # panel_adjudication was VALID and becomes INVALID; version-gated to >=_I41_SHIP via _i27_semver_ge
    # (:2668-2681) so no archive newly flags (the 4 archived dissent-on-PASS verifies live in a run stamped
    # 1.9.0), strictly narrowing, every schema delta OPTIONAL. (iii) **AO-3's `DISAGREE` route** — AO-3 is
    # SPLIT: the `FAIL` arm PRESERVES (I41-2a/b extends "a FAIL names a criterion" to panel members, which
    # previously escaped AO-3 entirely), but the 1.11.0 pre-release predicate ALSO bound `DISAGREE`-voting
    # members to cite a criterion, and AO-3 (self-learning-loops.md:299-302, :601-604) makes `DISAGREE` the
    # MANDATED route for a critique that cannot name one — leaving NO compliant artifact (the A2
    # no-compliant-path shape, :584-591). Resolved by NARROWING the criterion obligation to `FAIL` members
    # (_I41_CRITERION_BOUND below) and substantiating a `DISAGREE` member via I41-2(c) instead; the
    # correction is legality-WIDENING and is disclosed as such, on a set measured EMPTY (0 fixtures / 0
    # archived verifies carry a `DISAGREE` panel member, so the withdrawn arm never fired on any artifact).
    # I16's own predicate is byte-untouched;
    # I41-4d RE-USES its `_discrete_majority` rather than replacing it, and pins the previously-unspecified
    # semantic that panel[].verdict holds the FINAL vote. Trigger: T1 (presence floor; clauses I41-1/-2a)
    # arms only at validator_version >= _I41_SHIP; T2 (shape; clauses I41-2b/-3/-4/-5/-6) arms on ADOPTION
    # (a panel_adjudication OR any member defects[]), any version — DATED AND NOW EXPIRED, re-measure rather than inheriting: 0/292 at the 1.11.0 release, but 301 archived verify docs today of which 1 carries panel_adjudication and 9 carry member defects[], so the T2 arms are genuinely armed on an archived run (DECISIONS#51) -- historically 0/292 archived verifies carried
    # either key, so the T2 ADOPTION arm is unarmed on every archive. T1 stays silent on a SECOND,
    # separately measured ground: T1 arms on validator_version >= _I41_SHIP (1.11.0) and the MAXIMUM stamp
    # across the 17 archived fsm-state.json files is 1.10.1 (9 unstamped, then 1.7.0 / 1.8.0 x2 / 1.9.0 x3 /
    # 1.10.0 / 1.10.1), so no archive reaches the floor. Both arms are silent, but on TWO facts, not one —
    # an adoption count alone says NOTHING about T1. And the zero is DATED, NOT STRUCTURAL: the in-flight
    # run excluded from the denominator is itself stamped 1.12.0 and already carries panel_adjudication
    # records, so T1 WILL arm on it the moment it archives. No clause fires on a verify with no panel[].
    # CENSUS (re-measured 2026-07-29, re-derived IDENTICALLY 2026-07-30; the earlier 0/156 denominator was
    # stale, the CONCLUSION is not —
    # zero adopters then, zero adopters now). One command derives it for I41 AND I42, printing
    # `docs elements string-elements verifies-with-panel_adjudication verifies-with-member-defects`.
    # SELF-CONTAINED: the excluded run dir is named LITERALLY, so the published integers are re-derivable
    # from the published mechanism with no external knowledge (a free variable `RUN` would raise NameError):
    #   python3 -c "import json,glob;RUN='2026-07-29_183514';V=[p for p in
    #   sorted(glob.glob('.wip/*/units/*/verify*.json')) if RUN not in p];D=[json.load(open(p)) for p in V];
    #   E=[e for d in D for e in (d.get('inputs_reviewed') or [])];print(len(V),len(E),
    #   sum(isinstance(e,str) for e in E),sum('panel_adjudication' in d for d in D),
    #   sum(any(m.get('defects') for m in d.get('panel') or []) for d in D))"
    #   # -> 292 2179 2179 0 0   at 2026-07-30T03:10:51Z on tree 23c9962, and IDENTICALLY at
    #   # 2026-07-30T03:15:41Z on tree 1bf2626 — the axis held across a tree change mid-repair, which is
    #   # the point of excluding the in-flight run. The command above was extracted VERBATIM from this
    #   # file's sibling copy in state-machine.md and executed: exit 0, output `292 2179 2179 0 0`.
    #   # RUN = 2026-07-29_183514, the then-in-flight run, excluded because it is not yet archived.
    #   # ADJACENT AXES, so a reader who measures a different number can tell WHICH axis they are on:
    #   # 295 docs / 2179 elements with the looser recursive glob '.wip/**/verify*.json' (same archived
    #   # population, +3 run-root verify.json files that carry ZERO inputs_reviewed elements — the ELEMENT
    #   # count is axis-insensitive here, only I41's denominator moves). Both figures above EXCLUDE the
    #   # in-flight run and are therefore STABLE. Any in-flight-INCLUSIVE count is NOT durable and must not
    #   # be quoted forward: measured 346 total under .wip / 343 under units/ at 2026-07-30T03:10:51Z, up
    #   # from 321/318 roughly forty minutes earlier — it moved DURING this very repair. COMPOSITION of the
    #   # 292: 159 unit-final `verify.json` + 133 panelist `verify_p*.json` across 159 archived unit dirs —
    #   # so this is "no DOCUMENT adopted", which entails but is stronger than "no UNIT adopted".
    # Limitation Y: an UNRECORDED dissent is invisible; only the latest verify per unit survives a retry
    # (Limitation F/L1); tested_defect / rationale genuineness stay attestation (validity != correctness);
    # (iv) a dissenter that rewrites its FINAL vote to PASS and drops its defects arms ZERO clauses.
    _I41_SHIP = "1.11.0"                 # release shipping I41; validator_version >= this arms T1
    _I41_DISSENT = ("FAIL", "DISAGREE")
    # The DISSENT set (above) is what I41-1 / I41-4c / N-I41 read and MUST stay as it is: a `DISAGREE`
    # member is a full dissent for adjudication-presence, re-poll legality and the rubber-stamp NOTE.
    # The CRITERION obligation (I41-2a/b) is deliberately NARROWER — see REVISES (iii) above. Narrowing
    # _I41_DISSENT itself would silently weaken those three other clauses instead.
    _I41_CRITERION_BOUND = ("FAIL",)
    _I41_RESOLUTIONS = ("repoll", "withdrawn", "escalated-p7")
    _I41_EXCUSED = ("downgraded-minor", "withdrawn", "overruled-by-repoll")
    _i41_stem = LABEL_STEM['i41_dissent']
    _i41_note = LABEL_STEM['note_i41']
    _i41_probs0 = len(rep.problems)
    _i41_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _i41_t1 = _i27_semver_ge(_i41_ver, _I41_SHIP)
    _skew_record("I41-T1", True, _I41_SHIP, _i41_ver)                 # N-I45 shadow count; stamp-only arm

    def _i41_blank(x):
        return not str(x if x is not None else "").strip()

    def _i41_norm(s):
        # whitespace-normalized criterion comparison (the I29 clause-4 idiom)
        return " ".join(str(s).split()) if isinstance(s, str) else None

    # RAW reads (load_json + isinstance guards, the I26/I27/I40-6 posture) — never the schema-filtered
    # unit_docs, so a schema-invalid verify still gets accounted rather than silently skipped.
    _i41_verifies = []                   # [(uid, verify_dict)] in sorted unit order
    for _u41 in sorted(unit_subdirs):
        _vp41 = os.path.join(units_dir, _u41, "verify.json")
        if not os.path.exists(_vp41):
            continue
        try:
            _vd41 = load_json(_vp41)
        except Exception:
            _vd41 = None
        if isinstance(_vd41, dict):
            _i41_verifies.append((_u41, _vd41))

    def _i41_members(v):
        _p = v.get("panel")
        return [m for m in _p if isinstance(m, dict)] if isinstance(_p, list) else []

    def _i41_defects(m):
        _d = m.get("defects")
        return [x for x in _d if isinstance(x, dict)] if isinstance(_d, list) else []

    def _i41_adj(v):
        _a = v.get("panel_adjudication")
        return _a if isinstance(_a, dict) else None

    def _i41_rows(a, key):
        _r = a.get(key)
        return [x for x in _r if isinstance(x, dict)] if isinstance(_r, list) else []

    # verdict-bearing verifies (the I22/I30 adoption-closure domain)
    _i41_vb = [(u, v) for u, v in _i41_verifies if isinstance(v.get("verdict"), str)]
    _i41_vb_uids = {u for u, _v in _i41_vb}
    # T2 adoption arm — ANY panel_adjudication OR ANY member-level defects[] anywhere in the run.
    _i41_adopted = any(_i41_adj(v) is not None or any("defects" in m for m in _i41_members(v))
                       for _u, v in _i41_verifies)
    # I41-2(b) closure arm — armed once ANY member on ANY verdict-bearing verify RECORDS findings.
    _i41_defects_adopted = any(_i41_defects(m) for _u, v in _i41_vb for m in _i41_members(v))

    for uid, v in _i41_verifies:
        _mem = _i41_members(v)
        if not _mem:
            continue                     # a verify with no panel[] is entirely outside I41
        _adj = _i41_adj(v)
        _top = v.get("verdict")
        _dis = [m for m in _mem if m.get("verdict") in _I41_DISSENT]

        # I41-1 [T1] — dissent on an aggregate PASS requires an adjudication record.
        if _i41_t1 and _top == "PASS" and _dis and _adj is None:
            _lenses = sorted(str(m.get("lens")) for m in _dis)
            rep.fail(f"{_i41_stem} (unadjudicated {uid})",
                     f"verify records verdict=PASS with {len(_dis)} dissenting panel member(s) {_lenses} "
                     "but no panel_adjudication record — under I16 a 2-1 majority FORCES the PASS, so the "
                     "dissent must be resolved at panel level (re-poll / withdrawal) and recorded, never "
                     "absorbed silently (I41-1)")

        # I41-2 — a dissenting vote must be substantiated. (a) version floor; (b) adoption closure;
        # (c) a `DISAGREE` member substantiates WITHOUT a criterion. (a)/(b) bind _I41_CRITERION_BOUND
        # (`FAIL`) only: AO-3 makes `DISAGREE` the MANDATED route for a critique that cannot name a
        # criterion, so binding it here would leave no compliant artifact (REVISES (iii) above). The
        # purpose survives — a bare `{lens, verdict}` row is still unauditable and still FAILs — and the
        # obligation (a) actually imposes is only "a non-blank string", which (c) extracts too.
        for m in _dis:
            _lens = m.get("lens")
            # (a) version floor, any verify; (b) adoption closure, verdict-bearing verifies, any version.
            _arm = "a" if _i41_t1 else ("b" if (_i41_defects_adopted and uid in _i41_vb_uids) else None)
            if _arm is None:
                continue
            if m.get("verdict") in _I41_CRITERION_BOUND:
                if any(not _i41_blank(d.get("criterion")) for d in _i41_defects(m)):
                    continue
                rep.fail(f"{_i41_stem} (bare dissent {uid}/{_lens})",
                         f"panel member with lens={_lens!r} voted {m.get('verdict')} but records no "
                         "defects[] entry — a dissenting vote with no recorded finding is unauditable and "
                         f"cannot be adjudicated (I41-2{_arm})")
                continue
            # (c) a DISAGREE member: a non-blank `summary`, OR a defects[] entry with a non-blank
            # `minimal_repro`. Never a criterion — that is the route AO-3 designated for exactly this
            # critique. A DISAGREE member is WELCOME to name a criterion, but naming one does not by
            # itself satisfy (c): the two disjuncts are exactly `summary` and `minimal_repro`, as the
            # clause's failure message states. (spec 2.4's aside "satisfies (c) trivially via defects" is
            # inconsistent with its own predicate — reported as DIVERGENCE 8, not silently widened here.
            # WHY the aside is false, stated rather than implied: it holds only if a `defects` entry
            # NECESSARILY carries a `minimal_repro`, and it does not — `verify.schema.json` requires only
            # ['severity','criterion'] on a member defects item and leaves `minimal_repro` OPTIONAL, so a
            # criterion-bearing entry with no `minimal_repro` and no `summary` is schema-VALID and
            # satisfies NEITHER disjunct. The PREDICATE below is correct and unchanged; only the aside is
            # wrong. Anywhere else phrased as "a DISAGREE without `defects` fails (c)", read: without a
            # `minimal_repro`-bearing `defects` entry AND without a `summary`.)
            if (not _i41_blank(m.get("summary"))
                    or any(not _i41_blank(d.get("minimal_repro")) for d in _i41_defects(m))):
                continue
            rep.fail(f"{_i41_stem} (bare disagree {uid}/{_lens})",
                     f"panel member with lens={_lens!r} voted DISAGREE but records neither a non-blank "
                     "summary nor a defects[] entry with a minimal_repro — AO-3 lets a DISAGREE name no "
                     "criterion, it does not let it say nothing (I41-2c)")

        if not _i41_adopted:
            continue                     # T2 clauses below are adoption-armed only (archive-silent)

        _dispos = _i41_rows(_adj, "dispositions") if _adj is not None else []

        # I41-3 [T2] — no unexplained member blocker/major on an aggregate PASS. Deliberately NOT a flat
        # ban: banning member majors on a PASS reproduces the pathology (severity laundering); the honest
        # artifact KEEPS the member's severity and records the disposition. `upheld` on a PASS is a FAIL
        # (an upheld major contradicts the verdict), so it is not in _I41_EXCUSED.
        if _top == "PASS":
            for m in _mem:
                _lens = m.get("lens")
                for _j, _df in enumerate(_i41_defects(m)):
                    if _df.get("severity") not in ("blocker", "major"):
                        continue
                    if any(x.get("lens") == _lens and x.get("defect_index") == _j
                           and x.get("disposition") in _I41_EXCUSED
                           and not _i41_blank(x.get("rationale")) for x in _dispos):
                        continue
                    rep.fail(f"{_i41_stem} (unexplained major {uid}/{_lens}#{_j})",
                             f"panel member lens={_lens!r} records a {_df.get('severity')} defect on "
                             f"criterion {_df.get('criterion')!r} but the PASS carries no "
                             "panel_adjudication disposition for it — a mechanical majority may not "
                             "absorb a member's own blocker/major (I41-3; DAG-L11(c))")

        if _adj is None:
            continue

        # I41-4a [T2] — adjudication enum + rationale.
        _res = _adj.get("resolution")
        if _res not in _I41_RESOLUTIONS:
            rep.fail(f"{_i41_stem} (bad resolution {uid})",
                     f"panel_adjudication.resolution={_res!r} is not one of "
                     f"{list(_I41_RESOLUTIONS)} — an adjudication with no legal resolution disposes of "
                     "nothing (I41-4a)")
        if _i41_blank(_adj.get("rationale")):
            rep.fail(f"{_i41_stem} (no rationale {uid})",
                     "panel_adjudication carries no non-blank rationale — an unreasoned adjudication is "
                     "the laundering surface it exists to close (I41-4a)")

        # I41-4b [T2] — dissent_refs[]/dispositions[] must resolve to a real (lens, defect_index).
        _bylens = {}
        for m in _mem:
            _bylens.setdefault(m.get("lens"), m)
        for _key in ("dissent_refs", "dispositions"):
            for _r in _i41_rows(_adj, _key):
                _L, _ix = _r.get("lens"), _r.get("defect_index")
                _m = _bylens.get(_L)
                _ok = (_m is not None and isinstance(_ix, int) and not isinstance(_ix, bool)
                       and 0 <= _ix < len(_i41_defects(_m)))
                if not _ok:
                    rep.fail(f"{_i41_stem} (dangling ref {uid}/{_L}#{_ix})",
                             f"panel_adjudication.{_key} names lens={_L!r} defect_index={_ix!r}, which "
                             "does not resolve to a panel member's recorded defect — an adjudication may "
                             "only dispose of findings that exist (I41-4b)")

        _repoll = _i41_rows(_adj, "repoll")

        # I41-4c [T2] — the dissenter may not be re-polled. A lens "cast a dissenting vote" if its FINAL
        # panel verdict dissents OR the re-poll record's own pre_verdict does; the flip-the-dissenter
        # pathology lives entirely in pre_verdict, so the final-vote reading alone would never see it.
        if _res == "repoll":
            for _r in _repoll:
                _L = _r.get("lens")
                _m = _bylens.get(_L)
                _cast = ((_m is not None and _m.get("verdict") in _I41_DISSENT)
                         or _r.get("pre_verdict") in _I41_DISSENT)
                if _cast or _r.get("tested_defect") is True:
                    rep.fail(f"{_i41_stem} (repoll of dissenter {uid}/{_L})",
                             f"panel_adjudication re-polls lens={_L!r}, which itself dissented (or had "
                             "already tested the finding) — only lenses that never tested the disputed "
                             "defect may be re-polled; re-running the dissenter until it flips is the "
                             "AO-5 prohibition (I41-4c)")

        # I41-4d [T2] — panel[] records the FINAL vote (pre_verdict preserves the original), and the
        # discrete majority recomputed over that final list with I16's OWN rule must equal the top verdict.
        for _r in _repoll:
            _L, _post = _r.get("lens"), _r.get("post_verdict")
            _m = _bylens.get(_L)
            if _m is not None and _m.get("verdict") != _post:
                rep.fail(f"{_i41_stem} (repoll desync {uid}/{_L})",
                         f"panel_adjudication records post_verdict={_post!r} for lens={_L!r} but "
                         f"panel[] records {_m.get('verdict')!r} — panel[] holds the FINAL vote "
                         "(pre_verdict preserves the original), so the two must agree (I41-4d)")
        if _repoll:
            _maj41 = _discrete_majority([m.get("verdict") for m in _mem])
            if _maj41 != _top:
                rep.fail(f"{_i41_stem} (post-repoll majority {uid})",
                         f"the discrete majority recomputed over the FINAL panel verdicts is {_maj41!r} "
                         f"but the top-level verdict is {_top!r} — a re-poll must be carried through to "
                         "the aggregate under I16's own majority rule, never left half-applied (I41-4d)")

        # I41-4e [T2] — the re-poll rides verify_rounds (a second loop-until-dry round). I41 introduces NO
        # new bound: verify_rounds stays policed by I16-(c) at <=3, and at 3 no further re-poll is legal.
        if _res == "repoll":
            _vr41 = _as_int(v.get("verify_rounds"))
            if _vr41 is None or _vr41 < 2:
                rep.fail(f"{_i41_stem} (repoll unrounded {uid})",
                         f"panel_adjudication.resolution=repoll but verify_rounds={v.get('verify_rounds')!r} "
                         "— a re-poll IS a second loop-until-dry round and must be counted against the "
                         "existing I16-(c) bound of 3 (I41-4e)")

        # I41-5 [T2] — a downgrade must surface at the top level. Coverage-first: a downgrade that leaves
        # no trace in the canonical defects[] is a deletion wearing a downgrade's label. The mandated echo
        # is a `minor`, which I6 permits and which I14/AO-2 deliberately does not scope (A2: do_not_touch
        # intersects blocker|major only — fixture i14_minor_on_sealed).
        _topdef = [d for d in (v.get("defects") or []) if isinstance(d, dict)]
        _topminor = {_i41_norm(d.get("criterion")) for d in _topdef if d.get("severity") == "minor"}
        for _r in _dispos:
            if _r.get("disposition") != "downgraded-minor":
                continue
            _L, _ix = _r.get("lens"), _r.get("defect_index")
            _m = _bylens.get(_L)
            if _m is None or not isinstance(_ix, int) or isinstance(_ix, bool):
                continue                 # dangling ref is I41-4b's clause, not I41-5's
            _md = _i41_defects(_m)
            if not (0 <= _ix < len(_md)):
                continue
            _crit = _i41_norm(_md[_ix].get("criterion"))
            if _crit not in _topminor:
                rep.fail(f"{_i41_stem} (downgrade unechoed {uid}/{_L}#{_ix})",
                         f"panel_adjudication downgrades a {_md[_ix].get('severity')} on criterion "
                         f"{_md[_ix].get('criterion')!r} to minor, but no top-level minor defect records "
                         "it — a downgrade with no coverage-first echo is a silent deletion (I41-5)")

        # I41-6 [T2] — escalation is incompatible with a PASS. It deliberately does NOT demand a
        # `disagreement` block: the schema enforces `disagreement` present IFF verdict==DISAGREE in BOTH
        # directions (PR-6/N-06), so demanding a dossier on a FAIL would mandate a schema-INVALID artifact.
        if _res == "escalated-p7" and _top == "PASS":
            rep.fail(f"{_i41_stem} (escalate on PASS {uid})",
                     "panel_adjudication records resolution=escalated-p7 while the top-level verdict is "
                     "PASS — an escalation and a pass cannot be the same artifact; under I16 escalation "
                     "requires the FINAL panel to carry a FAIL majority or no strict majority (I41-6)")

        # N-I41 (advisory NOTE, exit-neutral, gated on --quiet) — the rubber-stamp signature (N-I36
        # precedent). A NOTE never appends to rep.problems, so it is exit-neutral by construction.
        if _res == "withdrawn" and not _repoll and _dis and not args.quiet:
            print(f"  NOTE  {_i41_note} (dissent withdrawn without re-poll) (units/{uid}): lens "
                  f"{sorted(str(m.get('lens')) for m in _dis)} recorded a dissent that was withdrawn with "
                  "no independent re-poll — the rubber-stamp signature (N-I36 precedent); genuineness "
                  "stays verifier judgment")

    # I41 success line (adoption-armed + no clause failed) — a zero-adoption run emits NOTHING.
    if _i41_adopted and len(rep.problems) == _i41_probs0:
        _i41_n = sum(1 for _u, v in _i41_verifies if _i41_adj(v) is not None)
        rep.ok(f"{_i41_stem} ({_i41_n} adjudicated dissent(s); accounting + re-poll legality + "
               "downgrade echo OK)")

    # ---- I42 evidence digest integrity (cross-repo-lessons 1.11.0; U05/U07) ----
    # invariant-spec.md §3 (R18 / BB-L46: a verifier gets content DIGESTS, not just paths). OFFLINE
    # post-hoc predicate: a digest of a RUN-DIR-RELATIVE path is recomputable from the run dir alone, so
    # it clears the "decidable from emitted artifacts alone" bar; out-of-run paths deliberately do NOT and
    # are an honest NOTE (I42-5), never a FAIL. Gates NO FSM transition, appears on no edge and **NEVER
    # guards LT7**; writes no `retries`/`fuel`; adds no state/edge/gate => PRESERVES the termination proof
    # and AO-1..AO-7 and I1..I41, all of them; `formal/` byte-untouched. The schema delta is a WIDENING
    # (inputs_reviewed items become string|object via oneOf), so no previously-valid artifact becomes
    # invalid — this is NOT the I25/GV-29 contract-revision class; the closest neighbour is I22's
    # adoption-closure, whose pattern I42-1b copies. T2 adoption only (armed when ANY inputs_reviewed
    # element on ANY verdict-bearing AGGREGATED `units/<uid>/verify.json` is an object -- panelist
    # `verify_p<N>.json` files are out of domain by the same decision I43 records); measured 2179/2179
    # archived inputs_reviewed elements across 292 archived verify documents are strings, so archives are
    # silent with no version gate needed. THAT ZERO IS DATED, NOT STRUCTURAL: nothing prevents an object
    # element from being archived, and this repository's own in-flight run already carries them, so the
    # arm arms the moment such a run archives. Re-measure rather than inheriting the zero. (Re-measured 2026-07-29 by the CENSUS command at the I41 header above, which prints
    # `292 2179 2179 0 0`; the previously published 964/964-across-156 denominators were stale. Both
    # numbers MOVED; the safety conclusion did NOT — every element is still a string, so the adoption
    # arm is still unarmed on every archive.) _I42_SHIP gates the CLOSURE arm (I42-1b) alone,
    # so a half-adopted pre-1.11.0 experiment is a NOTE rather than a FAIL. Limitation Z: a digest proves
    # the bytes match NOW; it does not prove the verifier ever READ them, and a verifier that fabricates a
    # digest from the current file passes trivially. I42 detects DRIFT, not READING. Stated, not implied.
    _I42_SHIP = "1.11.0"
    _I42_HEX = re.compile(r"^[0-9a-f]{64}$")
    _i42_stem = LABEL_STEM['i42_digest']
    _i42_note = LABEL_STEM['note_i42']
    _i42_probs0 = len(rep.problems)
    _i42_t1 = _i27_semver_ge(_i41_ver, _I42_SHIP)
    _skew_record("I42-1b-T1", True, _I42_SHIP, _i41_ver)              # N-I45 shadow count; stamp-only arm
    _i42_rows = []                       # [(uid, index, element)] over verdict-bearing verifies
    for uid, v in _i41_vb:
        _ir = v.get("inputs_reviewed")
        if not isinstance(_ir, list):
            continue
        for _ix, _el in enumerate(_ir):
            _i42_rows.append((uid, _ix, _el))
    _i42_armed = any(isinstance(_el, dict) for _u, _ix, _el in _i42_rows)
    _i42_status = {}
    if isinstance(fsm, dict) and isinstance(fsm.get("units"), list):
        for _u42 in fsm["units"]:
            if isinstance(_u42, dict):
                _i42_status[_u42.get("unit_id")] = _u42.get("status")

    def _i42_relok(p):
        # run-dir-relative == not absolute AND no `..` segment (the only shape whose bytes the run dir
        # owns; anything else is I42-5's NOTE, never a FAIL).
        if not isinstance(p, str) or not p.strip() or p.startswith("/"):
            return False
        return ".." not in p.replace("\\", "/").split("/")

    def _i42_owner(p):
        # The unit that owns the DIGESTED PATH (`units/<uid>/…`), NOT the unit that owns the verify. The
        # I9 rationale I42-3's transient window copies is "unit B is still rewriting that file", which is
        # a property of B; keying the status on the verify's own unit false-excuses a stale digest of a
        # settled sibling and false-FAILs a legitimate mid-flight rewrite cited cross-unit (a citation
        # R18/BB-L46 positively invites). Returns None for a run-root artifact (graph.json, fsm-state.json,
        # …) that no unit owns — there the PHASE conjunct alone decides, so an absent status is never read
        # as "not in flight".
        _seg = str(p).replace("\\", "/").split("/")
        return _seg[1] if len(_seg) >= 2 and _seg[0] == "units" and _seg[1] else None

    _i42_outofrun = []
    _i42_digested = 0
    if _i42_armed:
        for uid, _ix, _el in _i42_rows:
            # I42-1b — adoption closure: once armed, EVERY element of EVERY verdict-bearing AGGREGATED
            # `units/<uid>/verify.json` must be an object (partial adoption is the laundering surface).
            # THE WORD "AGGREGATED" IS THE DOMAIN, NOT A FLOURISH: panelist `verify_p<N>.json` files are
            # OUT OF DOMAIN, and the mechanism is the collection loop above, which opens the LITERAL
            # filename "verify.json" and nothing else -- NO CODE LINE in the whole I41/I42 region names
            # `verify_p`. That narrower claim is the one the mechanism argument needs and the one that is
            # TRUE; a comment-INCLUSIVE count is NOT zero and RISES every time anyone documents the
            # exclusion, this paragraph included, which is exactly how an earlier revision's false "occurs
            # ZERO times" was born (it was already wrong when measured: the 292-document composition
            # comment above was inside the region at the time). So no comment-inclusive figure is published
            # here. Re-derive both over a region delimited by CONTENT anchors, never by offset -- each
            # anchor below matches exactly once, so `grep -c` on either pattern returns 1:
            #     A="/^ *# ---- I41 panel dissent accounting/" ; B="/^ *# I9 MISSING VERIFICATION/"
            #     awk "$A,$B" validate_run.py | grep verify_p | grep -vc '^[[:space:]]*#'   # -> 0  (CODE)
            #     awk "$A,$B" validate_run.py | grep -c verify_p                # -> >0, and rising
            # (It is NOT the D-04/IMP-20 unit_docs carve-out: I41/I42 read RAW and
            # never consult unit_docs at all, as the collection comment says in terms. Anyone documenting
            # this exclusion should cite the filename literal, not unit_docs.) This matches I43's domain
            # decision deliberately -- per-member panel files are a per-iteration audit trail that
            # legitimately lags -- so it is a DOCUMENTED SCOPE, not an oversight. Live witness at the time
            # of writing: 3 panelist files in this repository's in-flight run
            # (units/U01/verify_p5.json, units/U02/verify_p4.json, units/U02/verify_p7.json) carry the
            # MIXED string/object shape and emit ZERO I42 rows of any severity, exactly as scoped. FAIL at
            # >=_I42_SHIP; below it an exit-neutral NOTE, so a pre-ship experiment is not punished.
            if not isinstance(_el, dict):
                if _i42_t1:
                    rep.fail(f"{_i42_stem} (mixed shape {uid}#{_ix})",
                             f"inputs_reviewed[{_ix}]={_el!r} is a bare string while this run has adopted "
                             "digested evidence objects — partial adoption lets an undigested input ride "
                             "along unchecked (I42-1b; the I22 adoption-closure pattern)")
                elif not args.quiet:
                    print(f"  NOTE  {_i42_note} (partial adoption) (units/{uid}): inputs_reviewed[{_ix}] "
                          f"is a bare string on a run stamped {_i41_ver!r} (< {_I42_SHIP}) — the closure "
                          "arm is advisory below the ship version (I42-1b)")
                continue
            _p = _el.get("path")
            # I42-1a — every object element carries a non-blank path.
            if _i41_blank(_p):
                rep.fail(f"{_i42_stem} (no path {uid}#{_ix})",
                         f"inputs_reviewed[{_ix}] is an evidence object with no non-blank `path` — a "
                         "digest that names nothing cannot be re-checked (I42-1a)")
                continue
            _sha = _el.get("sha256")
            _shaok = None
            if _sha is not None:
                # I42-2 — digest well-formedness; a malformed digest is fail-CLOSED, never silently
                # skipped (a typo'd hash must not read as "no digest recorded").
                _shaok = isinstance(_sha, str) and bool(_I42_HEX.match(_sha))
                if not _shaok:
                    rep.fail(f"{_i42_stem} (malformed digest {uid}/{_p})",
                             f"inputs_reviewed[{_ix}] records sha256={_sha!r}, which is not 64 lowercase "
                             "hex characters — a malformed digest is fail-closed, never treated as absent "
                             "(I42-2)")
                    continue
            # I42-5 — an absolute path / a path escaping the run dir is NOT decidable from emitted
            # artifacts (it may legitimately have changed, or not exist on the validating machine):
            # an honest exit-neutral NOTE, never a FAIL.
            if not _i42_relok(_p):
                _i42_outofrun.append(f"units/{uid}#{_ix}:{_p}")
                continue
            _fp42 = os.path.join(rd, _p)
            # I42-4 — dangling evidence: the verifier cites evidence that is not in the run.
            if not os.path.isfile(_fp42):
                rep.fail(f"{_i42_stem} (dangling evidence {uid}/{_p})",
                         f"inputs_reviewed[{_ix}] cites run-relative path {_p!r}, which does not exist "
                         "under the run dir — a verifier cannot have adjudicated an artifact the run "
                         "never emitted (I42-4)")
                continue
            if not _shaok:
                continue
            # Counted HERE, not at the well-formedness check: `digested` in the success line means "this
            # digest was actually RE-COMPUTED against run bytes". Incrementing earlier let an out-of-run
            # element (I42-5, explicitly reported as UNDIGESTABLE) be counted as `integrity OK` in the
            # same run — the OK line contradicting the NOTE two lines above it.
            _i42_digested += 1
            # I42-3 — integrity. Mismatch is a hard FAIL EXCEPT inside the I9 transient window
            # (:5126-5133 posture, copied verbatim for the same reason: a retry legitimately rewrites
            # debrief.json under a verify that has not yet been re-written). At every other phase, every
            # other status, and ALWAYS at P8/DONE, it is a FAIL. The window is a CONJUNCTION and its
            # status conjunct is keyed on the unit owning the DIGESTED PATH (`_i42_owner`), not on the
            # unit owning the verify; a run-root path no unit owns leaves the phase conjunct to decide.
            try:
                with open(_fp42, "rb") as _fh42:
                    _act42 = hashlib.sha256(_fh42.read()).hexdigest()
            except Exception:
                _act42 = None
            if _act42 is None or _act42 == _sha:
                continue
            _own42 = _i42_owner(_p)
            _st42 = _i42_status.get(_own42) if _own42 is not None else None
            if phase == "P6_EXECUTE_VERIFY" and (_own42 is None
                                                 or _st42 in ("executing", "verifying")):
                if not args.quiet:
                    print(f"  NOTE  {_i42_note} (digest drift mid-loop) (units/{uid}): {_p} hashes to "
                          f"{_act42[:12]}… but the verify records {_sha[:12]}… — the unit that owns the "
                          f"PATH ({_own42 or 'run root'}, fsm status {_st42!r} at P6) may legitimately "
                          "have rewritten it; not yet a defect (I42-3 transient, the I9 window)")
            else:
                rep.fail(f"{_i42_stem} (digest mismatch {uid}/{_p})",
                         f"verify records sha256={_sha[:12]}… for {_p!r} but the file now hashes to "
                         f"{_act42[:12]}… — the evidence moved under the verification (BB-L46); a finding "
                         "adjudicated against a superseded artifact is not a finding (I42-3)")

        if _i42_outofrun and not args.quiet:
            print(f"  NOTE  {_i42_note} (undigestable evidence): {len(_i42_outofrun)} inputs_reviewed "
                  f"entry/entries name a path outside the run dir {sorted(_i42_outofrun)} — integrity is "
                  "not decidable from emitted artifacts alone, so it is recorded, never failed (I42-5)")

    # I42 success line (adoption-armed + no clause failed) — an unadopted run emits NOTHING.
    if _i42_armed and len(rep.problems) == _i42_probs0:
        rep.ok(f"{_i42_stem} ({_i42_digested} digested input(s) across "
               f"{len({u for u, _i, _e in _i42_rows})} verify file(s); integrity OK)")

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

    # ═══ I43 verification currency · I44 sign-off closure · I46 non-converged PASS ═══════════════════
    # Three OFFLINE, POST-HOC predicates over already-emitted artifacts. None reads or writes `retries`,
    # `iteration`, `fuel` or any FSM variable; none adds a state, edge, gate flag or back-edge; none is
    # evaluated on any transition. In particular NOTHING here guards LT7 (RETRY->EXECUTE), whose out-edge
    # stays UNCONDITIONAL => the correction-loop termination proof Claims A-D and AO-1..7 all PRESERVE.
    # Two REVISES are filed, not smuggled: (1) I43 makes `verify.iteration == debrief.iteration` a
    # normative verify-artifact contract that no schema/predicate/doc previously stated; (2) I44 gives
    # `gates.signoff_confirmed` an artifact-level obligation at ANY phase. Both carry migration arguments
    # in the unit's spec (§5.4/§5.5); neither edits a schema, so no archived artifact becomes invalid.
    # UNGATED by `validator_version` (§0.4): measured 159/159 archived debrief/verify pairs across 5
    # distinct stamps (None -> 1.10.1) satisfy currency — EVERY archived pair complies, none excepted.
    # NAME THE AXIS, because several different counts have been published in this repository and only one
    # is this one. THIS IS A PAIR CENSUS, NOT A DOCUMENT COUNT: over the 17 ARCHIVED run dirs under this
    # repository's `.wip/` (18 dirs carry fsm-state.json; the 18th is the in-flight run, excluded), there
    # are 159 co-present debrief.json/verify.json PAIRS, of which 159 are iteration-matched and 0 are not.
    # THE THREE EXCEPTIONS ARE HISTORICAL, NOT PRESENT — and naming what closed them is the point. An
    # earlier revision of this comment published "156 iteration-matched and exactly 3 are not — and those 3
    # are the repair target's U05/U07/U08". That was TRUE WHEN WRITTEN and is FALSE NOW. Under a maintainer
    # waiver (this branch's run ledger, DECISIONS#44 extended by #46) the repair target's U05 iteration 2,
    # U07 iteration 3 and U08 iteration 2 were each re-verified by a panel of three on 2026-07-30; all
    # three became iteration-current, so those 3 exceptions are DISCHARGED, not reclassified or waived.
    # DIRECTION, because it is easy to misread a moved number as a retreat: this makes the ungated-arming
    # case STRONGER. The ground for shipping I43 ungated is that legitimately-closed archived pairs already
    # comply; they did (156 of 156), and now EVERY archived pair does (159 of 159). Only the ex-defect
    # subset moved — no complying pair became non-complying, and the arming decision is unchanged.
    # THE FIGURE IS A PROPERTY OF A MUTABLE, GITIGNORED DIRECTORY AND WILL MOVE AGAIN. `.wip/` is
    # gitignored (`.gitignore:7`), carries NO version identity, and is written to by every run — so this is
    # a TIMESTAMPED SAMPLE, never a property of a commit. Re-derive; do not inherit. And the cheap durable
    # remedy, which mtime-plus-file-count is NOT (that is a change DETECTOR, not an identity), is a digest:
    #     tar cf - .wip/<run-dir> | shasum -a 256     # one command, witnesses the pre-image permanently
    # (that digests the archive STREAM, so it covers metadata as well as bytes; the content-only variant is
    # `shasum -a 256 $(find <dir> -type f | sort) | shasum -a 256`. Either is strictly stronger than
    # mtime-plus-file-count.) Had such a digest been taken when the 156/3 figure was published, the
    # pre-image would still be checkable; it was not, so that figure is now unverifiable in principle.
    # RE-DERIVE THIS CENSUS from the repo root (prints `PAIRS MATCHED MISMATCHED`):
    #   python3 -c "import json,glob,os;IN='2026-07-29_183514';P=[d for d in glob.glob('.wip/*/units/*') \
    #     if IN not in d and os.path.exists(d+'/debrief.json') and os.path.exists(d+'/verify.json')]; \
    #     it=lambda p:json.load(open(p)).get('iteration'); \
    #     m=sum(it(d+'/debrief.json')==it(d+'/verify.json') and it(d+'/verify.json') is not None \
    #     for d in P);print(len(P),m,len(P)-m)"
    # -> `159 159 0`, executed 2026-07-30 at tree 0db7b03 + this change.
    # It is NOT the retired "156 archived verify DOCUMENTS" denominator that I41/I42 once published and
    # withdrew (that axis counts DOCUMENTS and its census command lives at the I41 header; it read 292 when
    # that cell was written and reads 301 today, having gained the 9 waived re-verification panel files
    # described above — the SAME mutable tree, sampled twice) — a reader who measures 301, or 292, or 159,
    # or 173, is on a DIFFERENT AXIS, not looking at a regression.
    # STAMP AXIS, likewise named: 5 distinct `validator_version` values across the 14 archived
    # dirs that hold >=1 pair; 6 across all 17 archived dirs; 6 across the 15 pair-carrying dirs including
    # the in-flight run; 7 across all 18 dirs. An earlier revision of this comment published "8 distinct
    # stamps", which is reproducible under NONE of those four readings — it was wrong, not mis-scoped. The
    # four-row census command is published in references/state-machine.md §5 ("The stamp census").
    # ARCHIVE-SAFETY FIGURE — DATED. READ THE HISTORICAL AND CURRENT FORMS IN ORDER, BECAUSE THE TWO
    # ZEROS BELOW ARE NOT THE SAME CLAIM, and that is exactly why the historical form is kept rather than
    # overwritten. Population first, for both: all 18 run dirs under THIS REPOSITORY's `.wip/` — of which
    # 17 are ARCHIVED and the 18th is the in-flight repair run itself, which I43's `not SIGNED_OFF`
    # conjunct carves out BY CONSTRUCTION, so counting it in a false-positive tally would count the one
    # member that structurally cannot supply that evidence.
    # HISTORICAL (measured 2026-07-29 against the SHIPPED code): 1 OF THE 17 ARCHIVED RUNS WAS NEWLY RED
    # IN THIS REPOSITORY — `2026-07-29_090706_cross-repo-lessons-intake`, this branch's own REPAIR TARGET,
    # carrying 8 rows (I43 on U05/U07/U08, I44 on U05/U07/U08, I46 on U03/U07) — with ZERO FALSE
    # POSITIVES: no other run in the population emitted any I43/I44/I46 FAIL row at all.
    # CURRENT (measured 2026-07-30 at tree 0db7b03 + this change): ZERO archived runs are newly RED, and
    # NO run in the population emits a class FAIL row of ANY severity. Under a maintainer waiver (this
    # branch's run ledger, DECISIONS#44 extended by #46) the repair target's U05 iteration 2, U07
    # iteration 3 and U08 iteration 2 were each re-verified by a panel of three, which discharged all 8
    # rows; that run now validates at 282 checks / 0 problems / RESULT: PASS.
    # DIRECTION — THE POINT MOST EASILY MISREAD: this STRENGTHENS the property A FORTIORI. The claim was
    # "only one archived run newly REDs, and it is the one we exist to repair"; the measured position is
    # "zero archived runs are newly RED". What was lost is the ILLUSTRATIVE INSTANCE, never the property,
    # and the instance was consumed by REPAIRING it. The arming decision is unchanged.
    # AND IT IS NOT A RETURN TO THE RETRACTED WORDING. An earlier revision of this comment claimed ungated
    # arming "newly REDs ZERO archived runs". That was FALSE WHEN WRITTEN, and stating "0" was a defect IN
    # THOSE WORDS: it rested an ungated arming decision on a number a reader who checked it would find
    # false. Arriving at zero BY MEASUREMENT, HAVING REPAIRED THE EXCEPTION, is a different claim from
    # asserting zero BEFORE MEASURING — the first is a receipt, the second was a guess — and a reader must
    # be able to tell which one this is. Hence: never publish a bare "zero" here; publish it with its
    # population, its date and the command.
    # THE WORD "FAIL" IS LOAD-BEARING: the class is NOT silent elsewhere, and that is what distinguishes
    # this zero from an inert predicate. `Report.ok` positive assertions fire on every iteration-matched
    # pair, so 15 of the 18 dirs emit 7-18 class PASS rows in the DEFAULT (non-quiet) invocation and 18 of
    # 18 emit at least one class NOTE; the only three dirs that emit nothing at all are the
    # empty-`units/` runs (see the materialization residual in references/state-machine.md §5). "No other
    # run emits a row" would be FALSE AS WRITTEN.
    # "Newly RED" means every FAIL row on the run is an I43/I44/I46 row, i.e. the run was GREEN
    # before these three predicates existed. SCOPE CAVEAT, stated rather than
    # implied: the population is this repository's own `.wip/` archive and nothing else. Another
    # installation's archive is a different population and may yield a different figure — re-run the
    # command below against it rather than assuming this number transfers.
    # THE NARROWER PROPERTY, WHICH HELD ALL ALONG AND IS NOW THE WHOLE STORY: ZERO LEGITIMATELY-CLOSED
    # archived runs are newly RED. That clause was true when the figure was 1, because the one exception
    # was not legitimately closed; it is true now because that run has since been closed.
    # MUTABILITY, load-bearing for both forms: `.wip/` is gitignored (`.gitignore:7`) and carries NO
    # version identity, so every figure here is a TIMESTAMPED SAMPLE, not a property of a commit — it has
    # already moved once and will move again. Re-derive; do not inherit. Per DECISIONS#50 the cheap anchor
    # that would make any such figure permanently checkable is `tar cf - .wip/<run-dir> | shasum -a 256`,
    # which mtime-plus-file-count (a change DETECTOR, not an identity) is not.
    # Re-derive from the repo root with:
    #   for d in .wip/*/; do o=$(python3 plugins/dag/skills/dag/scripts/validate_run.py "$d"); \
    #     n=$(printf '%s' "$o" | grep -cE '^ +FAIL +(I43|I44|I46) '); \
    #     t=$(printf '%s' "$o" | grep -cE '^ +FAIL +'); \
    #     [ "$n" -gt 0 ] && [ "$n" -eq "$t" ] && echo "NEWLY RED $d ($n rows)"; done
    # (Measured 2026-07-29 at tree f575911 + that change: ONE line, `.wip/2026-07-29_090706_...` 8 rows.
    #  Re-measured 2026-07-30 at tree 0db7b03 + this change: NO OUTPUT — the loop prints nothing, because
    #  the waiver-driven re-verification above discharged the only member. An empty result here is the
    #  CURRENT expected result; if you get a line, a run has regressed or a new run has archived dirty.
    #  Corollary worth stating because a silent loop is indistinguishable from a broken one: confirm the
    #  instrument by dropping the `[ "$n" -eq "$t" ]` conjunct, which then prints the 13 archived runs that
    #  are RED from PRE-EXISTING, unrelated invariants — never green-washed by this release, and expected
    #  version skew per references/state-machine.md §5, not defects.)
    #  CORRECTION, INSERTED BY U19 (the corollary above is left standing, not rewritten): the conjunct
    #  it names is the WRONG one, so as published the confirmation recipe is ITSELF SILENT — the exact
    #  failure the corollary exists to prevent. Dropping `[ "$n" -eq "$t" ]` leaves `[ "$n" -gt 0 ]`,
    #  and `$n` (the I43/I44/I46 CLASS FAIL count) is 0 on all 18 of this repository's `.wip/` run dirs,
    #  so that variant prints ZERO lines. The conjunct to key on is `$t`, the TOTAL FAIL count. Confirm
    #  the instrument from the repo root with:
    #    for d in .wip/*/; do o=$(python3 plugins/dag/skills/dag/scripts/validate_run.py "$d"); \
    #      t=$(printf '%s' "$o" | grep -cE '^ +FAIL +'); \
    #      [ "$t" -gt 0 ] && echo "RED $d ($t rows)"; done
    #  Measured 2026-07-30 at tree aefa9c2 + this change, over all 18 `.wip/` run dirs in THIS
    #  repository: 13 lines, all archived runs, all with n=0 class rows — 2026-07-05_111828 (4),
    #  2026-07-05_134959 (6), 2026-07-05_143454 (25), 2026-07-05_170505 (6), 2026-07-05_175148 (1),
    #  2026-07-06_110152 (15), 2026-07-06_134656 (51), 2026-07-06_200420 (13), 2026-07-10_133732 (21),
    #  2026-07-11_134440 (22), 2026-07-16_014443 (16), 2026-07-16_095126 (17), 2026-07-16_163411 (1).
    #  The `13` the corollary published is therefore right; only the conjunct naming it was wrong. Like
    #  every figure in this banner it is a TIMESTAMPED SAMPLE over a gitignored tree — re-derive.
    # A >=1.12.0 gate was REJECTED. THE REASON THIS COMMENT USED TO GIVE IS RETRACTED IN FULL, not
    # re-anchored: it asserted that init_run.sh writes the stamp only at scaffold time and never
    # refreshes it, hence a version gate could not arm on the run authoring the predicate. BOTH HALVES
    # ARE FALSE AT THIS TREE, and the unit that wrote the sentence is the one retracting it. (a) A
    # refresh path exists: `grep -n 'RE-STAMP mode' init_run.sh` -> exactly 1 hit, the header of
    # `init_run.sh --restamp <RUN_DIR>`, shipped by this run's own U08. (b) It has been applied here —
    # this run's fsm-state.json reads validator_version 1.12.0 against plugin.json 1.12.0 — so a
    # >=1.12.0 gate WOULD arm on the authoring run. The scaffold-time stamp itself is at
    # `grep -n 'F1(a): stamp validator_version' init_run.sh` -> exactly 1 hit; the `:161-163` an earlier
    # revision of this line carried landed in a PLAN.md heredoc, not on the stamp. Spec §0.4-a quotes the
    # retracted sentence verbatim and refutes it; §9-R16 names this locus.
    #
    # THE DECISION STANDS, on three replacement reasons (spec §0.4-a), each checkable:
    #   (1) --restamp is MANUAL and OPT-IN, so the archive is still unarmed. Measured 2026-07-30 over the
    #       18 run dirs under THIS repository's .wip/: a >=1.12.0 gate would arm on 1 of them (this run)
    #       and on NONE of the 17 archived ones unless a human retroactively restamped each — including
    #       the repair target, whose pairs are the defect class these predicates were commissioned to
    #       find. Suppressing a predicate on every run that CONTAINS the defect it was written for is the
    #       L4 failure mode arriving through the ARMING rather than through the clause.
    #   (2) The ratchet only ever RAISES a stamp, so no archive can silently arm:
    #       `grep -n 'ratchet, not lowered' init_run.sh` -> exactly 1 hit (it exits 0 rather than
    #       lowering a recorded stamp). Gating would therefore make arming depend on a monotone,
    #       human-invoked act — legible, but not evidence.
    #   (3) Restamping the authoring run so that its own predicate arms is CIRCULAR: the gate would be
    #       satisfied by an act of the run being judged. Ungated arming needs no such act, and its safety
    #       is MEASURED — the pair census and the newly-RED sweep above — rather than asserted.
    # Ungated is therefore not a concession but the stronger posture. What survives of the retracted
    # claim is a real divergence, filed as spec §9-R16: MANUAL re-stamp has landed; DoD 18's AUTOMATIC
    # re-stamp-on-phase-advance has not.
    #
    # IN-FLIGHT WINDOW — CITED, NOT HOISTED (R3). Two window sites already exist and are BYTE-UNTOUCHED.
    # CITED BY CONJUNCT, NEVER BY LINE NUMBER: every offset in this file drifts (the correct pair moved
    # twice in eleven minutes during this very repair, and an earlier revision of THIS comment cited
    # `:5649`/`:5555`, neither of which matched). Locate both, and only both, with one command:
    #     grep -n '^ *if phase == "P6_EXECUTE_VERIFY"' validate_run.py     # -> exactly 2 hits
    # The leading-`if` anchor is what makes it exact: the bare conjunct string ALSO matches this comment
    # (the recipe line above and both bullets below quote it) and I43's own `return (phase == ...` window,
    # so the bare form OVER-MATCHES and is not a locator. NO COUNT OF THE BARE FORM IS PUBLISHED HERE, on
    # purpose: this comment's own text is part of what that form would count, so the number moves whenever
    # the comment is edited -- it was exactly 4 at tree 35f44a0 and moved the moment the comment explaining
    # why was written. If you need today's figure, `grep -c` it; do not inherit one from prose. The two
    # hits, in file order, are:
    #   * I42-3 digest drift (the FIRST hit): `phase == "P6_EXECUTE_VERIFY" and (_own42 is None ...` —
    #     the same two conjuncts, copied verbatim for the same reason, keyed on the PATH OWNER's status.
    #   * I9 missing-verification (the SECOND hit): `phase == "P6_EXECUTE_VERIFY" and _st in
    #     ("executing", "verifying")`.
    # Hoisting them into one shared helper was DECLINED: pure insertion is a confirmed guardrail for this
    # change (Non-Goal 9), and a hoist would re-condition two shipped predicates to buy nothing. I43
    # therefore defines its OWN window — I9's two conjuncts PLUS `not SIGNED_OFF` — as a sibling, not a
    # shared function. That third conjunct is LOAD-BEARING in both directions. Without the first two, a
    # hard FAIL would halt a compliant orchestrator — a de-facto live guard on the sole back-edge. THE
    # PROOF STEP THIS COMMENT USED TO GIVE FOR THAT IS WITHDRAWN (spec §1.3-a, §9-R18): it claimed the
    # newest verify still attests to `N-1` at every legal RETRY, which substitutes the FSM COUNTER for
    # the ARTIFACT FIELD this predicate actually reads. LT7 increments the counter on the edge OUT of
    # RETRY and the executor writes the next debrief afterwards, inside EXECUTE, so AT RETRY the on-disk
    # pair is (N-1, N-1) and CURRENT is TRUE — a predicate evaluated at RETRY is satisfied, not violated.
    # THE CONCLUSION SURVIVES ON THE ARTIFACT TIMELINE INSTEAD: the transient is real but differently
    # located, opening when EXECUTE writes debrief N and closing when the aggregated verify N is written,
    # i.e. it spans the EXECUTE->VERIFY leg and the interior of VERIFY — exactly the interval the two
    # copied conjuncts `status in {executing, verifying}` cover. The hazard is PARALLEL WAVES, and the
    # load-bearing form is a PROPERTY, not a count: prime directive 7 has orchestrators validate after
    # every debrief+verify pair, and while the unit whose pair just closed is clean at (N, N), sibling
    # units of the same wave sitting between their own debrief-write and verify-write are at (N, N-1).
    # This run holds MULTIPLE units at `verifying` and MULTIPLE at `executing` simultaneously, so a
    # per-unit predicate is always evaluated while siblings are mid-loop; the argument is indifferent to
    # which multiset it is, which is why the property and not the census is asserted here.
    # Without `not SIGNED_OFF`, the three units that motivate the predicate (all `verifying` at
    # P6) downgrade to NOTEs that `--quiet` (mandated by SKILL.md) then eats, leaving the predicate INERT
    # on exactly the run it was written for. Rule made precise: mid-loop staleness is legal; staleness once
    # the run CLAIMS to be finished is not.
    # CRASH DISCIPLINE (§0.5): every read below is isinstance-guarded and `.get`-only (no indexing), because
    # an exception here would abort the linear pass and SILENTLY DISABLE every downstream predicate — a
    # failure mode already observed in this codebase (I35 raising TypeError on a schema-invalid integer).
    # An iteration is accepted iff `isinstance(v, int) and not isinstance(v, bool)`; the bool exclusion is
    # currently unreachable through unit_docs, and the MECHANISM is the schema, not an offset (L16): both
    # debrief.schema.json and verify.schema.json type `iteration` as `{"type": "integer", "minimum": 1}`,
    # JSON Schema excludes booleans from `integer`, and a doc with validation errors is FAILed and never
    # reaches the `unit_docs.setdefault(...) = inst` insertion. Verify the schema half without reading
    # this file at all:
    #     python3 -c "import json;print(json.load(open('plugins/dag/skills/dag/schemas/debrief.schema.json'))['properties']['iteration'])"
    # The guard is kept so it survives a future schema relaxation. (The `:670-673` an earlier revision of
    # this sentence carried landed on the isdir/UNIT_ARTIFACTS loop, not on the bool drop — retired, and
    # named here rather than deleted silently, because a pointer removed without a forwarding address is
    # how the next reader re-derives it wrong.) NO per-member panel verify file (the
    # numbered audit-trail siblings of the aggregated verify.json, excluded from unit_docs at the loop
    # `grep -n '^ *if f\.startswith("verify_p")' validate_run.py` locates -> exactly 1 hit; as everywhere
    # in this block the LEADING anchor is what makes the count true, since the bare string also matches
    # this comment; the `:687-694` an earlier revision of this clause carried landed on the errs/D21
    # block) is opened, statted or globbed by ANY clause below,
    # and this block contains no textual reference to their filename prefix (§0.3): they are a
    # per-iteration AUDIT TRAIL BY DESIGN, deliberately kept out of unit_docs, and 27 of 133 archived
    # member files legitimately sit behind their own unit's debrief — a freshness check over them would
    # RED-flag the best audit trail in the archive (18 of those 27 are one signed-off run's 3x3 panel).
    _vc_f = fsm if isinstance(fsm, dict) else {}
    _vc_gates = _vc_f.get("gates") if isinstance(_vc_f.get("gates"), dict) else {}
    _vc_signed_off = _vc_gates.get("signoff_confirmed") is True      # IDENTITY to True, never truthiness

    def _vc_doc_iter(_u, _kind):
        _d = unit_docs.get(_u)
        _doc = _d.get(_kind) if isinstance(_d, dict) else None
        _it = _doc.get("iteration") if isinstance(_doc, dict) else None
        return _it if isinstance(_it, int) and not isinstance(_it, bool) else None

    def _vc_agg(_u):
        # AGG(u): the AGGREGATED verify.json only — parsed, schema-valid and unit_id-matched by the
        # D21 branch: `grep -n 'D21: an artifact.s declared unit_id' validate_run.py` -> exactly 2 hits,
        # the FIRST being the branch itself and the SECOND this citation of it. THE COUNT IS 2, NOT 1,
        # AND IS PUBLISHED RATHER THAN ASSUMED: the `.` dodges shell quoting of the apostrophe and also
        # matches the `.` on this very line, so this anchor SELF-MATCHES BY CONSTRUCTION — the same trap
        # the leading-anchor forms elsewhere in this block avoid, named here with its ordinal instead —
        # the same publish-the-ordinal precedent the dated archive-safety figure and the artifact-keying
        # note in this file already use. THEIR HEADING STRINGS ARE DELIBERATELY NOT REPRODUCED ON THIS
        # LINE: each publishes a `grep -n` count OF ITS OWN HEADING (-> 2 hits), so quoting either one
        # here to credit it would silently make both published counts read 3 and false. Citing a
        # convention by description rather than by its anchor text is what keeps that from happening —
        # the first draft of this very line did quote them, and did exactly that.
        # Cited by CONTENT: the `:684` this line used to carry pointed at a `no schema loaded` FAIL.
        _d = unit_docs.get(_u)
        _v = _d.get("verify") if isinstance(_d, dict) else None
        return _v if isinstance(_v, dict) else None

    def _vc_in_flight(_u):
        # I9's window — the SECOND of the two hits the banner's `grep -n '^ *if phase ==
        # "P6_EXECUTE_VERIFY"'` recipe returns, cited by CONTENT because the `:5649` this line used
        # to carry had already drifted — PLUS the third conjunct. The carve-out EXPIRES at claimed
        # completion.
        # LIMITATION, WINDOW COVERAGE (residual R-U06-W1, filed not fixed): the window keys on the two
        # status labels I9 uses. fsm-state.schema.json's status enum has nine members, so a unit encoded
        # as {status: "failed", loop_state: "RETRY"} — a legal encoding of a unit mid-correction-loop —
        # is OUTSIDE the window and takes a hard I43-a FAIL instead of the mid-loop NOTE. Reproduce:
        # copy scripts/tests/i43_inflight_signoff_false, set units[0] to {"unit_id": "U01", "status":
        # "failed", "loop_state": "RETRY", "retries": 1}, change nothing else => exit 0 flips to 1.
        # The spec's §9-R11 repair (widen WINDOW to loop_state in {EXECUTE,VERIFY,ADJUDICATE,RETRY} OR
        # status in {briefed,executing,verifying,failed,blocked}, phase-independent, still conjoined
        # with `not SIGNED_OFF`) is a strict WIDENING of a carve-out, so the FAIL set shrinks
        # monotonically and it can newly RED zero runs by construction.
        # THE FENCE, STATED CORRECTLY — an earlier revision of this comment said the widening was "out of
        # U06's pure-insertion remit", and THAT FENCE DOES NOT EXIST: `_vc_in_flight` is U06's own
        # insertion (it is absent from 935f8e6^), so the no-refactoring-existing-predicates non-goal does
        # not reach it. A fence that does not exist would either block in-scope work or be discovered
        # false and discredit this residual, so the two that DO hold are named instead: (1) the brief's
        # "Do NOT write fixtures — a different unit authors those from the spec", and a widening whose
        # RED->GREEN discriminator is P1-K1 cannot land unpinned; and (2) spec §9-R11 DEFERS this itself
        # and adds that I9's and I42-3's own windows must then be decided too — "three sibling windows,
        # widened one at a time, each with its own fixture". Filed here, taken there.
        return (phase == "P6_EXECUTE_VERIFY"
                and _fsm_unit_status.get(_u) in ("executing", "verifying")
                and not _vc_signed_off)

    # ── fsm-state.json.accepted_incomplete — the recorded human override (§2.3), computed ONCE here so
    # I44 and I46 share ONE override shape. Computation only: nothing is emitted unless SIGNED_OFF holds.
    # Six conditions, evaluated in order so a malformed override can name THE FIRST unmet one by number.
    # `accepted_at` / `accepted_by` are deliberately NEVER read — they exist for the human reader, and
    # enforcing them would invent an attestation.
    _ai_present = "accepted_incomplete" in _vc_f
    _ai = _vc_f.get("accepted_incomplete")
    _ai_units = _ai.get("units") if isinstance(_ai, dict) else None
    _ai_rat = _ai.get("rationale") if isinstance(_ai, dict) else None
    _ai_ref = _ai.get("decision_ref") if isinstance(_ai, dict) else None
    _ai_unmet = None
    if not isinstance(_ai, dict):
        _ai_unmet = 1
    elif not isinstance(_ai_units, list):
        _ai_unmet = 2
    elif not (isinstance(_ai_rat, str) and _ai_rat.strip() != ""):
        _ai_unmet = 3
    elif not (isinstance(_ai_ref, str) and _ai_ref.strip() != ""):
        _ai_unmet = 4
    elif "DECISIONS.md" not in _ai_ref:
        _ai_unmet = 5
    elif not os.path.exists(os.path.join(rd, "DECISIONS.md")):
        _ai_unmet = 6
    _ai_ok = _ai_present and _ai_unmet is None
    # Elements that are not `str` are IGNORED, never coerced (§2.3(2)).
    # LIMITATION, SILENTLY-INERT OVERRIDE (residual R-U06-W3, filed not fixed — and the honest reading is
    # that it is a SPEC residual surfaced by the implementation, not a divergence from the spec text):
    # condition (2) above tests LIST-NESS only, and this comprehension then drops every non-`str` element.
    # So `accepted_incomplete: {"units": [7], "rationale": "r", "decision_ref": "DECISIONS.md#x"}` with a
    # DECISIONS.md on disk is COMPLETELY INVISIBLE in the output: it is well-formed by condition (2), so
    # no `accepted_incomplete malformed` FAIL fires; `_ai_named` is empty, so no unit is downgraded AND the
    # over-broad surplus set is empty, so no over-broad NOTE fires either. SAFE — every open unit keeps its
    # own hard FAIL and nothing is suppressed — but it is exactly the accretion shape §2.3's over-broad
    # rule exists to make visible. Reproduce: copy scripts/tests/i44_override_wellformed, set
    # accepted_incomplete.units to `[7]`, run the validator; exit stays 1 with U01's own I44 FAIL and no
    # row anywhere names the garbage. Naming the dropped elements in the over-broad NOTE would close it in
    # one clause. THE FENCE, STATED CORRECTLY — an earlier revision of this comment said that clause was
    # "out of U06's pure-insertion remit", and THAT FENCE DOES NOT EXIST: `_ai_named` and the over-broad
    # NOTE are U06's own insertion (both are absent from 935f8e6^), so the no-refactoring-existing-
    # predicates non-goal does not reach them. The fence that DOES hold is the SPEC: §2.3(2) says
    # non-`str` elements are "ignored, never coerced", so this is a SPEC residual surfaced by the
    # implementation, and an implementer must not unilaterally diverge from normative text — it is
    # referred back rather than taken. Whatever closes it must NOT touch the ignore-never-coerce rule.
    _ai_named = sorted({_x for _x in (_ai_units or []) if isinstance(_x, str)}) if isinstance(_ai_units, list) else []
    _AI_COND = {
        1: "(1) accepted_incomplete is not a JSON object",
        2: "(2) accepted_incomplete.units is not a list",
        3: "(3) accepted_incomplete.rationale is missing, not a string, or blank",
        4: "(4) accepted_incomplete.decision_ref is missing, not a string, or blank",
        5: "(5) accepted_incomplete.decision_ref does not name DECISIONS.md",
        6: "(6) no DECISIONS.md exists under the run dir",
    }

    def _vc_override_note(_u, _why):
        # UNGATED by `args.quiet` (§9-R12): SKILL.md mandates `--quiet`, so a quiet-gated downgrade row
        # would be inert in THE MANDATED ORCHESTRATOR INVOCATION. That wording is normative for code
        # comments per §3.3/§3.4: this line previously called --quiet the sole invocation of any
        # consequence, which OVER-STATES it and is RETRACTED — a human, a reviewer and the fixture
        # harness all run the validator WITHOUT --quiet (run_tests.sh does). The retracted phrase is
        # deliberately NOT re-quoted here, so that grepping it locates only loci that still ASSERT it;
        # §9-R18 names the phrase and its loci, and one such locus survives in the I47 block below,
        # which belongs to the unit that shipped I47 (23c9962) and is left untouched under Non-Goal 9.
        # The un-gating itself stands on §3.3's SECOND limb — the human ruling requires the override be
        # "available but LOUD: deliberate, grep-visible, per-unit". Same principle as the un-gated N-I45
        # skew NOTE — ANCHORED BY CONTENT, not by offset, because the offset this comment originally
        # carried (`:6557-6562`) was invalidated by the very insertion that wrote it: locate it with
        # `grep -n "i45_version_skew'\]}: validator_version=" validate_run.py` (exactly 1 hit, the print
        # itself). Un-gate a NOTE exactly when stdout is its only channel. Exit-neutral BY
        # CONSTRUCTION (a bare print touching neither rep.problems nor rep.checked), so un-gating cannot
        # move any exit code and no archived run's verdict changes — PRESERVES.
        print(f"  NOTE  {LABEL_STEM['note_i44']} (accepted-incomplete override) (units/{_u}): {_why} "
              f"— DOWNGRADED from a hard FAIL by fsm-state.json.accepted_incomplete "
              f"(decision_ref {_ai_ref!r}); the human accepted this unit's verification as incomplete "
              "at sign-off. Recorded, per-unit and grep-visible (I44 §2.3)")

    # ── I43 (P1) — verification currency. Four EXHAUSTIVE, MUTUALLY EXCLUSIVE arms over the post-guard
    # state space {SUPERSEDED, AHEAD, CURRENT} x {IN_FLIGHT, not IN_FLIGHT}. Two GUARDS first: I43 never
    # fires on an indeterminate debrief — already a FAIL by MECHANISM, not by offset (L16): debrief.schema
    # .json lists `iteration` in `required` and types it `integer`, so an absent or non-int iteration is
    # reported by the per-artifact validation loop (`grep -n '^ *rep\.fail(f"units/{uid}/{rel}", e)'` ->
    # exactly 1 hit; the LEADING anchor is load-bearing — the bare string also matches this comment) —
    # nor on an absent/unusable verify, which is I9's domain (`grep -n
    # "LABEL_STEM\['i9_missing'\]"` locates its four emissions) and, under sign-off, I44-a/-b's. The
    # `:664/:673/:681` and `:5592-5609` this comment used to carry pointed at an isdir check and an I42
    # sha256 read respectively — cite by content. Declining rather than
    # piling a second FAIL on the same fact is a normative sub-clause (§0.6), not an optimization.
    # I43 does NOT read `retries` (I4's ceiling `iteration <= retries+1` is neither widened nor narrowed —
    # this is an equality between two ARTIFACTS), does NOT read `verdict` (complete means CURRENT, not
    # PASS: a unit holding a current FAIL at retries==2 exits via ESCALATE), and detects STALENESS, never
    # GENUINENESS — a loop that bumps both iterations without re-verifying satisfies I43 exactly (§9-R5).
    for uid in sorted(unit_dirs_with_debrief):
        _i43_dbi = _vc_doc_iter(uid, "debrief")
        if _i43_dbi is None:
            continue                                   # GUARD: indeterminate debrief — emit nothing (§1.5)
        _i43_agg = _vc_agg(uid)
        _i43_vyi = _vc_doc_iter(uid, "verify")
        if _i43_agg is None or _i43_vyi is None:
            continue                                   # GUARD: absent/unusable verify — I9's domain (§0.6)
        _i43_inf = _vc_in_flight(uid)
        _i43_st = _fsm_unit_status.get(uid)
        _i43_so = _vc_gates.get("signoff_confirmed")
        if _i43_vyi < _i43_dbi and not _i43_inf:                                             # P1-a
            rep.fail(f"{LABEL_STEM['i43_currency']} (units/{uid})",
                     f"debrief.iteration={_i43_dbi} but the aggregated verify.iteration={_i43_vyi} — the "
                     f"verification is SUPERSEDED (fsm status {_i43_st!r}, phase {phase}, "
                     f"gates.signoff_confirmed={_i43_so!r}), so what was adjudicated is not what the unit "
                     "now claims; the in-flight carve-out (P6 + executing/verifying + not signed off) "
                     "does not apply")
        elif _i43_vyi > _i43_dbi and not _i43_inf:                                           # P1-b
            rep.fail(f"{LABEL_STEM['i43_currency']} (units/{uid})",
                     f"debrief.iteration={_i43_dbi} but the aggregated verify.iteration={_i43_vyi} — the "
                     f"verification is AHEAD OF THE DEBRIEF (fsm status {_i43_st!r}, phase {phase}, "
                     f"gates.signoff_confirmed={_i43_so!r}); no legal LT7 transient puts the verify ahead "
                     "(LT7 increments `iteration` BEFORE the next EXECUTE writes its debrief), so either "
                     "the debrief was rolled back under a live verification or the verify's iteration was "
                     "AUTHORED rather than observed")
        elif _i43_vyi != _i43_dbi and _i43_inf:                                              # P1-d
            if not args.quiet:
                print(f"  NOTE  {LABEL_STEM['note_i43']} (in-flight) (units/{uid}): debrief.iteration="
                      f"{_i43_dbi} vs aggregated verify.iteration={_i43_vyi} (fsm status {_i43_st!r} at "
                      f"P6, gates.signoff_confirmed={_i43_so!r}) — a unit mid-correction-loop legitimately "
                      "carries a verify one iteration behind; legal transient, not yet a defect")
        elif _i43_vyi == _i43_dbi:                                                           # P1-ok
            rep.ok(f"{LABEL_STEM['i43_currency']} (units/{uid}: iteration {_i43_vyi} verified)")

    # ── I44 (P2) — sign-off closure. The CONVERSE direction of gate ordering: from a true gate flag to a
    # required artifact state. It is DELIBERATELY NOT in REQUIRED_GATES (locate the table with
    # `grep -n '^ *REQUIRED_GATES = {'` -> exactly 1 hit; the leading-anchor form is what excludes this
    # citation of it — cited by content, since every offset in this file drifts): that table is
    # one-directional (phase => gates) and spec_check.py SC3 DERIVES it from spec/fsm.json.guards[], whose
    # entire vocabulary is `required_from_phase` — a lower bound on gates given a phase. "Given gate G
    # true, artifacts A must exist" is INEXPRESSIBLE there, so adding I44 would either break SC3 or
    # silently redefine what REQUIRED_GATES means. I44 therefore ships as its own labelled predicate,
    # following the `gpersonas_failclosed` archetype exactly (`grep -n "LABEL_STEM\['gpersonas_failclosed'\]"`
    # -> the rep.fail site; by content, not by offset).
    # KEYED ON ARTIFACTS, NEVER ON fsm-state STATUS LABELS: `_fsm_unit_status` is read below ONLY to
    # interpolate into detail text, never for a decision. Measured: a status-keyed formulation newly REDs
    # 3 archived runs for cosmetic desync (e.g. 2026-07-05_143454's U09, labelled `executing` at DONE with
    # a complete, iteration-matched debrief+verify) while the artifact-keyed one newly REDs NO RUN FOR
    # COSMETIC DESYNC and still catches all 3 real defects. THE FIGURE HERE IS DATED, AND THE ORDER OF
    # THESE TWO SENTENCES IS THE CLAIM. Do not read this as the false absolute "newly REDs zero runs" — an
    # earlier revision of this comment did assert that, and it was false when written. HISTORICALLY
    # (2026-07-29): I44 newly REDded 1 archived run IN THIS REPOSITORY -- i.e. 1 of the 17 ARCHIVED runs;
    # the 18th `.wip/` dir is the in-flight repair run, which the in-flight window carves out -- the repair
    # target, on 3 REAL defects (arm d on U05/U07/U08). CURRENTLY (2026-07-30, tree 0db7b03): those 3 were
    # discharged by the maintainer-waived re-verification (DECISIONS#44/#46), so I44 newly REDs NO archived
    # run -- reached BY MEASUREMENT AFTER REPAIR, which is a receipt, and NOT the same claim as the
    # unmeasured "zero" that was retracted. Full population, dates, direction and command in the block
    # headed `ARCHIVE-SAFETY FIGURE` above; `grep -n 'ARCHIVE-SAFETY FIGURE'` -> 2 hits, the heading itself
    # and this citation of it, the heading being the FIRST.
    # A stale label is a documentation defect and belongs to a separate NOTE — now shipped as N-I47 below.
    # NO PHASE CONDITION AND NO CARVE-OUT: the antecedent SIGNED_OFF is the exact negation of I43's
    # carve-out conjunct, so a carve-out here would be self-cancelling — and the motivating run rolled
    # P8 -> P6 back while LEAVING `signoff_confirmed: true`, so any phase-gated formulation is inert on it.
    if _vc_signed_off and unit_subdirs:
        _i44_fired = False
        if _ai_present and _ai_unmet is not None:
            # FAIL-CLOSED (§2.3): a malformed override downgrades NOTHING and adds exactly one hard FAIL.
            _i44_fired = True
            rep.fail(f"{LABEL_STEM['i44_signoff_closure']} (accepted_incomplete malformed)",
                     f"fsm-state.json.accepted_incomplete is PRESENT but unmet condition {_AI_COND[_ai_unmet]} "
                     "of the six required by I44 §2.3 — so NO unit is downgraded and every open unit keeps "
                     "its own hard FAIL; a malformed override may never silently suppress an emission")
        _i44_open = []
        for uid in sorted(unit_dirs_with_debrief):
            _i44_agg = _vc_agg(uid)
            _i44_dbi = _vc_doc_iter(uid, "debrief")
            _i44_vyi = _vc_doc_iter(uid, "verify")
            _i44_st = _fsm_unit_status.get(uid)
            _i44_arm = None
            if not os.path.exists(os.path.join(units_dir, uid, "verify.json")):
                _i44_arm = ("a", "ABSENT verification (no units/%s/verify.json on disk)" % uid)
            elif _i44_agg is None:
                _i44_arm = ("b", "UNUSABLE verification (not JSON / not schema-valid / unit_id mismatch)")
            elif "verdict" not in _i44_agg:
                _i44_arm = ("c", "verification carries NO VERDICT")
            elif not (_i44_dbi is not None and _i44_vyi is not None and _i44_dbi == _i44_vyi):
                _i44_arm = ("d", "SUPERSEDED verification (the verify does not adjudicate this debrief)")
            elif _i44_agg.get("verdict") == "DISAGREE":
                _i44_arm = ("e", "unresolved DISAGREE at sign-off")
            if _i44_arm is None:
                continue
            _i44_fired = True
            _i44_why = (f"{_i44_arm[1]} while gates.signoff_confirmed=true "
                        f"(debrief.iteration={_i44_dbi!r}, aggregated verify.iteration={_i44_vyi!r}, "
                        f"fsm status {_i44_st!r}, phase {phase})")
            if _i44_arm[0] == "e":
                # NOTE, not FAIL: DISAGREE is a COMPLETE verification act declaring irresolvability; its
                # sanctioned route is LT6 -> ESCALATE -> Phase 7, a human gate, not more verification.
                # Failing it would conflate "verification incomplete" with "escalation unresolved" AND
                # create an incentive against voting DISAGREE — attacking AO-5 from the incentive side.
                if not args.quiet:
                    print(f"  NOTE  {LABEL_STEM['note_i44']} (unresolved DISAGREE at sign-off) "
                          f"(units/{uid}): {_i44_why} — a genuine split is closed by the Phase-7 human "
                          "gate, never by another verification round; recorded, never failed (AO-5)")
                continue
            _i44_open.append(uid)
            # Per-unit coverage (§2.3): a well-formed override downgrades the units it NAMES and leaves
            # every other open unit a hard FAIL. There is no blanket "all open units" form.
            if _ai_ok and uid in _ai_named:
                _vc_override_note(uid, _i44_why)
            else:
                rep.fail(f"{LABEL_STEM['i44_signoff_closure']} (units/{uid})",
                         f"{_i44_why} — a run may not claim sign-off over an executed unit whose "
                         "verification is absent, unusable, verdict-less or superseded, at ANY phase "
                         f"(arm {_i44_arm[0]}; record fsm-state.json.accepted_incomplete to accept it "
                         "knowingly). Note a CURRENT FAIL verdict is CLOSED verification, not an arm.")
        if _ai_ok:
            _i44_surplus = sorted(set(_ai_named) - set(_i44_open))
            # UNGATED by `args.quiet` for the same §9-R12 reason as `_vc_override_note` above: the
            # over-broad row is the companion record of the SAME override and must survive `--quiet`.
            #
            # SCOPE OF THIS ROW IS I44 ONLY, AND THE WORDING SAYS SO. `_i44_open` is appended to inside
            # the arm-a..d loop above and nowhere else, while §4.3 makes I46 a SECOND consumer of the
            # SAME override object. A unit that is I46-armed but not I44-open therefore lands in this
            # surplus set even though the override is actively downgrading its I46 FAIL in the same run.
            # An earlier revision of this row called such a unit's override "stale", which was FALSE as
            # written — reproduce it by copying scripts/tests/i46_nonconverged_pass_at_signoff, adding a
            # well-formed `accepted_incomplete` naming its U01 plus a DECISIONS.md, and reading both rows.
            # The row is now scoped to what it actually measures (I44 openness) and explicitly declines to
            # call the override stale, because THIS ROW CANNOT SEE I46: the I46 loop runs after it.
            # Residual R-U06-W2 (filed, not fixed): unioning `_i44_open` with the units the I46 loop
            # downgrades — i.e. deferring this computation past that loop — would let the row say
            # "stale" truthfully. THE FENCE, STATED CORRECTLY — an earlier revision of this comment said
            # that union was "outside U06's pure-insertion remit", and THAT FENCE DOES NOT EXIST:
            # `_i44_open`, `_i44_surplus` and this print are U06's own insertion (all absent from
            # 935f8e6^), so the no-refactoring-existing-predicates non-goal does not reach them. The fence
            # that DOES hold is the brief's "Do NOT write fixtures — a different unit authors those from
            # the spec": moving the computation past the I46 loop changes this row's emission set and
            # must land RED/GREEN-pinned, and this unit may not author that fixture.
            # ALREADY OWNED UPSTREAM, so it is credited rather than re-filed as new: spec §9-R19 records
            # that this un-gated over-broad row has NEVER EXECUTED UNDER TEST in either direction and
            # assigns the fixture to P2-G4 (§2.5); §9-R10 records the I46-only-open false-surplus shape
            # this row's wording now declines to assert.
            if _i44_surplus:
                print(f"  NOTE  {LABEL_STEM['note_i44']} (override over-broad): "
                      f"accepted_incomplete.units names {_i44_surplus} but those units are not open under "
                      "any I44 arm (no absent/unusable/verdict-less/superseded verification), so the "
                      "override buys them nothing HERE. This row scopes to I44 and does NOT assert the "
                      "override is stale: I46 §4.3 shares this same override object and is evaluated "
                      "after this row, so a unit named here may still be having an I46 FAIL downgraded — "
                      "grep the run's own N-I44 accepted-incomplete rows before concluding it accreted. "
                      "Exit-neutral, and it blocks no downgrade for the units that ARE open")
        if not _i44_fired:
            rep.ok(f"{LABEL_STEM['i44_signoff_closure']} (signoff_confirmed with "
                   f"{len(unit_dirs_with_debrief)} executed unit(s); all verified and current)")

    # ── I46 (P4) — non-converged PASS. ADOPTION-ARMED BY IDENTITY: `v.get("converged") is False`, never
    # falsiness — an ABSENT `converged` (an optional key in verify.schema.json) never arms I46, and neither
    # does 0, "" or null. A run that never wrote the field emits NOTHING AT ALL (the I19/I20 zero-adoption
    # precedent), which is what keeps I46 silent across the archive. Severity is TWO-TIER by human ruling
    # (DECISIONS#29): exit-neutral NOTE below sign-off — `converged: false` is a LEGAL mid-run state, and
    # an unconditional FAIL would criminalize an honest report and punish adoption of an optional honesty
    # field — but a hard FAIL under a CLAIMED sign-off, where a unit whose own verification declares its
    # coverage incomplete IS verification left unfinished. I43, I44 and I46 thus share ONE doctrine rather
    # than three ad-hoc severities. `verify_rounds` is PRINTED when present but is never a CONDITION:
    # requiring the round cap would narrow the predicate on unmeasured grounds. Reads the AGGREGATED
    # verify only; a panel member's own `converged` is per-member audit data (§0.3).
    _i46_declared = 0
    _i46_fired = False
    for uid in sorted(unit_dirs_with_debrief):
        _i46_agg = _vc_agg(uid)
        if _i46_agg is None:
            continue
        if "converged" in _i46_agg:
            _i46_declared += 1
        if not (_i46_agg.get("verdict") == "PASS" and _i46_agg.get("converged") is False):
            continue
        _i46_fired = True
        _i46_why = ("aggregated verify records verdict=PASS with converged: false"
                    + (f", verify_rounds={_i46_agg.get('verify_rounds')!r}" if "verify_rounds" in _i46_agg
                       else " (no verify_rounds recorded)"))
        if not _vc_signed_off:                                                               # P4-a
            if not args.quiet:
                print(f"  NOTE  {LABEL_STEM['note_i46']} (units/{uid}): {_i46_why} — the verifier is "
                      "reporting honestly that its coverage is incomplete; legal mid-run, and it becomes "
                      "a defect only if the run claims sign-off in this state (I46 two-tier severity)")
        elif _ai_ok and uid in _ai_named:                                                    # P4-b, §4.3
            _vc_override_note(uid, _i46_why)
        else:                                                                                # P4-b
            rep.fail(f"{LABEL_STEM['i46_nonconverged_pass']} (units/{uid})",
                     f"{_i46_why} while gates.signoff_confirmed=true (phase {phase}) — a PASS whose own "
                     "verification declares its coverage NOT converged is verification left unfinished at "
                     "claimed completion; re-verify, or record fsm-state.json.accepted_incomplete")
    if _i46_declared and not _i46_fired:
        rep.ok(f"{LABEL_STEM['i46_nonconverged_pass']} ({_i46_declared} verify doc(s) declare converged; "
               "none is a non-converged PASS)")

    # ── I47 (DoD 6) — LEDGER DESYNC AT SIGN-OFF. The advisory NOTE that I44 deliberately does NOT carry.
    # I44 is keyed on ARTIFACTS, never on `fsm-state` status labels (`grep -n 'KEYED ON ARTIFACTS'` -> 2
    # hits, the I44 comment block stating it and this citation of it, that block being the FIRST; cited by
    # content because offsets drift), because a status-keyed
    # formulation would newly RED archived runs for COSMETIC desync; that comment, references/
    # state-machine.md:605 and the unit spec §2.1(i) all promise the stale label "is a SEPARATE predicate".
    # Until this insertion that predicate was DESCRIBED IN THREE PLACES AND SHIPPED IN NONE — a fifth
    # documented-but-absent predicate. It ships here as an exit-neutral NOTE and NOTHING else: a bare
    # `print` touching neither `rep.problems` nor `rep.checked`, so it can move no exit code and can newly
    # RED no archived run BY CONSTRUCTION (the N-I45 skew-NOTE / `_vc_override_note` archetype; both are
    # anchored by NAME here rather than by offset, since both moved during the change that wrote them).
    # ANTECEDENT — four conjuncts, all four required:
    #   (1) `gates.signoff_confirmed` is True by IDENTITY (`_vc_signed_off`), never truthiness;
    #   (2) the unit is EXECUTED — `unit_dirs_with_debrief`, exactly I44's domain, so a never-executed
    #       materialized unit stays out of scope (that is I10's, at P8/DONE);
    #   (3) its verification is COMPLETE AND CURRENT: verify.json PRESENT on disk, PARSEABLE/usable
    #       (`_vc_agg`: JSON, schema-valid, unit_id-matched), VERDICT-BEARING, and iteration-matched to the
    #       debrief with both iterations determinate ints. That is the exact NEGATION of I44's FAIL arms
    #       a-d and of I43-a/-b, so this NOTE never double-charges a fact another predicate already fails
    #       (§0.6, the same declining discipline I43 applies to I9). A DISAGREE verdict is NOT excluded: by
    #       I44 arm e's own doctrine a DISAGREE is a COMPLETE verification act, and its N-I44 row records
    #       an unresolved escalation while this row records a stale LABEL — two different facts;
    #   (4) the ledger's own `fsm-state.units[].status` is NON-TERMINAL.
    # NON-TERMINAL IS A WHITELIST of the four IN-PROGRESS labels, deliberately not `not in {passed,failed}`:
    # `escalated` (closed by the Phase-7 human gate — I44 arm e's doctrine), `retired` (a cancelled unit)
    # and `blocked` (a recorded non-completion, I10's domain) are CLOSED outcomes at sign-off, not stale
    # in-flight labels, and an unknown/future enum member must never arm an advisory. MEASURED, not tuned
    # to go green: over all 18 of this repository's `.wip/` run dirs (17 archived + the in-flight repair
    # run) the whitelist and the broader `not in {passed,failed}` form
    # select the SAME two units (2026-07-05_143454 U09 `executing` at DONE, and 2026-07-29_090706 U09
    # `verifying`), so the choice buys no silence — it is made on doctrine.
    # THE WITNESS this predicate exists for: 2026-07-05_143454_implement-dag-loop-proposals U09, labelled
    # `executing` at phase DONE over a complete, iteration-matched PASS verify. It is a documentation
    # defect, never a verification defect, so the row is advisory and that archived run's verdict is
    # unchanged (it is already RED for 25 unrelated version-skew rows; this adds none).
    # NOT gated on `validator_version` (stdout is its only channel; init_run.sh:161-163 stamps once at
    # scaffold, so a version gate would not arm on the run authoring the predicate) and NOT gated on
    #   [RETRACTION INSERTED BY U19 — the two lines above are RESTORED VERBATIM to their HEAD text, not
    #    deleted; the clause they leave hanging ("and NOT gated on ...") resumes below, at the line
    #    beginning `args.quiet`.]
    #    RETRACTED: `init_run.sh:161-163 stamps once at scaffold, so a version gate would not arm on
    #    the run authoring the predicate` is FALSE AT THIS TREE. `init_run.sh --restamp <RUN_DIR>`
    #    SHIPPED IN THIS RELEASE (1.12.0, this run's own U08) and has already been applied here — this
    #    run's fsm-state.json reads validator_version 1.12.0 against plugin.json 1.12.0 — so a >=1.12.0
    #    gate WOULD arm on the authoring run. The scaffold-time stamp is also not at `:161-163` (that
    #    offset is a PLAN.md heredoc). The un-gating DECISION is unaffected: it now rests on the three
    #    replacement reasons in the I43 banner above. Full retraction, quoting the sentence verbatim
    #    and refuting it: verify-repair-units artifacts/predicate-spec.md §0.4-a; the surviving
    #    divergence (MANUAL re-stamp landed, DoD 18's AUTOMATIC re-stamp-on-phase-advance did not) is
    #    §9-R16. Retracted IN PLACE rather than removed, per this run's date-in-place doctrine
    #    (DECISIONS#61) — the same treatment `fcb8df1` gave the 0/292 adoption zero, so a reader meets
    #    both the original claim and its refutation.
    # `args.quiet`, for the §9-R12 reason already applied to `_vc_override_note` and the N-I45 skew NOTE
    # (both by name, not by offset): SKILL.md mandates `--quiet`, so a quiet-gated advisory is inert in the only invocation that
    # matters. Un-gating is safe precisely because the row is exit-neutral => PRESERVES every guarantee;
    # offline/post-hoc, adds no state, edge or gate flag, and NEVER guards LT7.
    # CRASH DISCIPLINE (§0.5): every read is `.get`-only and isinstance-guarded — an exception here would
    # abort the linear pass and silently disable every downstream predicate.
    _I47_IN_PROGRESS = ("pending", "briefed", "executing", "verifying")
    if _vc_signed_off:
        for uid in sorted(unit_dirs_with_debrief):
            _i47_st = _fsm_unit_status.get(uid)
            if not (isinstance(_i47_st, str) and _i47_st in _I47_IN_PROGRESS):
                continue                       # terminal/closed outcome, unlabelled, or a non-str — silent
            if not os.path.exists(os.path.join(units_dir, uid, "verify.json")):
                continue                       # DECLINED to I44-a (absent verification)
            _i47_agg = _vc_agg(uid)
            if not isinstance(_i47_agg, dict) or "verdict" not in _i47_agg:
                continue                       # DECLINED to I44-b/-c (unusable / verdict-less)
            _i47_dbi = _vc_doc_iter(uid, "debrief")
            _i47_vyi = _vc_doc_iter(uid, "verify")
            if _i47_dbi is None or _i47_vyi is None or _i47_dbi != _i47_vyi:
                continue                       # DECLINED to I43-a/-b and I44-d (not CURRENT)
            print(f"  NOTE  {LABEL_STEM['note_i47']} (units/{uid}): fsm-state.units[] status "
                  f"{_i47_st!r} is NON-TERMINAL while gates.signoff_confirmed=true (phase {phase}), yet "
                  f"the unit's verification is COMPLETE AND CURRENT (verdict "
                  f"{_i47_agg.get('verdict')!r} at iteration {_i47_vyi}, matching the debrief) — the "
                  "LEDGER LABEL IS STALE: a documentation defect, not a verification defect, so I44 "
                  "correctly does not fail it. Refresh the status label to the outcome the verify "
                  "records (advisory, exit-neutral)")

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

    # -----------------------------------------------------------------------
    # I48 case-set contract (SPEC.md §3.1/§3.2/§3.2.1/§3.3/§6.1/§6.2).
    #
    # OFFLINE and POST-HOC, by construction: every clause below reads artifacts that already
    # exist on disk and emits ONLY `rep.fail(...)` report rows. It is evaluated inside this
    # single invariant pass, it appears in NO transition guard, it never writes fsm-state
    # (no `.phase`, no `.gates`, no `.loop`), and it has no early `return` — a `continue`
    # here advances THIS loop's unit cursor and nothing else. In particular it is NOT a guard
    # on the correction loop's sole back-edge LT7 (RETRY→EXECUTE): a live guard there can leave
    # RETRY with no enabled out-edge → deadlock, breaking Claim D of the termination proof
    # (CLAUDE.md; SPEC.md §3.2 `infeasible`; Non-Goal 2). Violations route to a report row,
    # escalation stays on the EXISTING ESCALATE branch. No existing invariant is touched:
    # this block is purely additive and reads `_i30_briefs` / `_i30_debriefs` / `_i30_verifies`
    # (already-parsed raw docs) without mutating them.
    #
    # VERSION GATE: `_I48_SHIP` is deliberately ABOVE 1.12.1 — the current release stamp — so the
    # arm fires on ZERO archived runs and on no run scaffolded by a validator that predates the
    # contract. A gate at 1.12.0 would arm on runs stamped 1.12.1, including this repo's own.
    # ABSENCE of `case_set[]` on a gated run is a hard FAIL (I48-1), never an advisory NOTE.
    _I48_SHIP = "1.13.0"                 # release shipping I48; validator_version >= this arms T1
    # U25: U24's inline literal stem was a SHIM for the deferred registration (DECISIONS#D20) and is
    # replaced here by the real hoist — the stem now has exactly one copy, in LABELS, and reaches this
    # block through LABEL_STEM. All three registration sites (LABELS, `spec/invariants.json` group
    # 'I48', the `references/state-machine.md` row) land together, because spec_check SC1 is
    # bidirectional: a label group without a registry entry and a mechanical entry without real label
    # prefixes each fail it. The LABELS entry carries `emitted_via: "hoisted-var"` (see the registry
    # preamble): the labels below are built from this ALIAS, not from the literal, so the absent-value
    # promise would misdescribe the call sites.
    _i48_stem = LABEL_STEM["i48_case_set"]
    _i48_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    _i48_t1 = _i27_semver_ge(_i48_ver, _I48_SHIP)
    _skew_record("I48-T1", True, _I48_SHIP, _i48_ver)      # N-I45 shadow count; stamp-only arm
    _I48_FLOOR = {"command": "executable", "locator": "located"}
    _I48_RANK = {"asserted": 0, "located": 1, "executable": 2}
    # §3.1: these keys live in the FROZEN brief for an orchestrator row; re-stating them in the
    # debrief creates a second copy that can be quietly narrowed.
    _I48_ORCH_FORBIDDEN = ("check", "check_form", "trigger_ref", "requirement_ref",
                           "requirement_ref_none_reason", "required_observations",
                           "forbidden_observations", "forbidden_observations_none_reason",
                           "production_path", "production_path_none_reason")
    # §10 (b): matched with re.fullmatch and NEVER compiled with re.MULTILINE — re.M is the flag
    # that re-opens the newline defeat.
    _I48_LOCATOR_RE = re.compile(r"[^\s:]+:[0-9]+([ \t][^\n]*)?")

    def _i48_blank(x):
        return not str(x if x is not None else "").strip()

    def _i48_hashable(x):
        # §3.3's totality join and §6.1's id membership test both HASH untrusted artifact values.
        # A list/dict id (or acceptance-criterion) is schema-invalid, but an uncaught TypeError
        # would abort main() BEFORE any RESULT: line — indistinguishable from a legitimate FAIL
        # (both rc 1) while taking every later armed row down with it. Every hash site below is
        # therefore filtered through this predicate, and every value it rejects is REPORTED by a
        # rep.fail row rather than silently dropped: a guard that only skips trades a crash for a
        # blind spot. Hashable-but-non-string ids (e.g. an int) are NOT affected — they keep the
        # shrink/extra_ids rows they already produce.
        try:
            hash(x)
        except TypeError:
            return False
        return True

    if _i48_t1:
        for _uid in sorted(_i30_briefs):
            _b = _i30_briefs.get(_uid) or {}
            _lbl = f"{_i48_stem} (units/{_uid})"
            _cs = _b.get("case_set")

            # I48-1 — ABSENCE on a gated run is a hard FAIL, not a NOTE (§2.2 explicit-none).
            if not isinstance(_cs, list):
                if _i48_blank(_b.get("case_set_none_reason")):
                    rep.fail(_lbl,
                             f"validator_version {_i48_ver!r} (>= {_I48_SHIP}) but brief.json carries "
                             "neither case_set[] nor a non-blank case_set_none_reason — the case-set "
                             "contract is not optional on a gated run (SPEC §2.2)")
                continue

            # §6.2 evaluation order is NORMATIVE: the brief-side id-uniqueness precondition is
            # computed FIRST, before any floor, so a duplicate id can never surface as a KeyError.
            _i48_ids = [e.get("id") for e in _cs if isinstance(e, dict)]
            _i48_unh = [repr(i) for i in _i48_ids if not _i48_hashable(i)]
            if _i48_unh:
                rep.fail(_lbl,
                         f"brief.case_set[] carries UNHASHABLE id(s) {_i48_unh} (list/dict) — an id "
                         "must be a scalar the §3.3 join can key on; reported here rather than "
                         "raised, so the invariant pass still reaches its RESULT: line")
            _i48_ids = [i for i in _i48_ids if _i48_hashable(i)]
            _i48_bdup = sorted({i for i in _i48_ids if _i48_ids.count(i) > 1}, key=str)
            if _i48_bdup:
                rep.fail(_lbl,
                         f"brief.case_set[] ids not unique: {_i48_bdup} — 'unique within the array' "
                         "(SPEC §2.1) is prose JSON Schema cannot express; the tier floor's verdict "
                         "would flip on transcription order alone")
                continue
            _i48_byid = {e.get("id"): e for e in _cs
                         if isinstance(e, dict) and _i48_hashable(e.get("id"))}

            _d = _i30_debriefs.get(_uid)
            if _d is None:
                continue                      # not yet executed — mid-run, nothing to adjudicate
            _rows = _d.get("case_set_discharge")
            if not isinstance(_rows, list):
                if _cs:
                    rep.fail(_lbl,
                             f"brief carries {len(_cs)} case_set entr(y/ies) but debrief.json has no "
                             "case_set_discharge[] — every frozen entry must be discharged (SPEC §3.3)")
                continue
            _rows = [r for r in _rows if isinstance(r, dict)]
            _orch = [r for r in _rows if r.get("origin") == "orchestrator"]
            _oids = [r.get("id") for r in _orch]
            _runh = [repr(r.get("id")) for r in _rows if not _i48_hashable(r.get("id"))]
            if _runh:
                rep.fail(_lbl,
                         f"case_set_discharge row(s) carry UNHASHABLE id(s) {_runh} (list/dict) — "
                         "the §3.3 totality join and §6.1's id membership test both hash a row id; "
                         "reported here rather than raised (covers executor ADDs too)")
            _oids = [i for i in _oids if _i48_hashable(i)]

            # I48-2 — §3.3 totality, both directions, plus the duplicate rule.
            _miss = sorted([i for i in _i48_byid if i not in _oids], key=str)
            _extra = sorted({i for i in _oids if i not in _i48_byid}, key=str)
            _rdup = sorted({i for i in _oids if _oids.count(i) > 1}, key=str)
            if _miss:
                rep.fail(_lbl, f"case_set_discharge is a SHRINK: frozen entr(y/ies) {_miss} have no "
                               "origin='orchestrator' row (SPEC §3.3 — an entry judged infeasible is "
                               "escalated with a recorded reason, never dropped)")
            if _extra:
                rep.fail(_lbl, f"origin='orchestrator' row(s) {_extra} match no frozen brief entry "
                               "(SPEC §6.2 extra_ids; an executor ADD carries origin='executor')")
            if _rdup:
                rep.fail(_lbl, f"id(s) {_rdup} appear in more than one origin='orchestrator' row "
                               "(SPEC §6.2 duplicate_ids)")
            if _cs and not _orch:
                rep.fail(_lbl, "case_set_discharge carries ZERO origin='orchestrator' rows against a "
                               "non-empty frozen case_set — the executor authored its own case set "
                               "(Non-Goal 3), which is not a shortcut")

            for _r in _rows:
                _rid = _r.get("id")
                _rlbl = f"{_i48_stem} (units/{_uid} {_rid})"
                _org = _r.get("origin")
                _out = _r.get("outcome")
                _tier = _r.get("evidence_tier")

                # I48-3 — §3.1: the forbidden second copy on an orchestrator row.
                if _org == "orchestrator":
                    _dupk = [k for k in _I48_ORCH_FORBIDDEN if k in _r]
                    if _dupk:
                        rep.fail(_rlbl, f"origin='orchestrator' row re-states brief-owned key(s) "
                                        f"{_dupk} — these MUST be absent (SPEC §3.1); a second copy "
                                        "is how 'never shrink' is violated without leaving a trace")

                # I48-4 — §3.1: vacuity_finding <=> outcome 'vacuous' (a biconditional, both arms).
                _vf = "vacuity_finding" in _r
                if _out == "vacuous" and (not _vf or _i48_blank(_r.get("vacuity_finding"))):
                    rep.fail(_rlbl, "outcome='vacuous' without a non-blank vacuity_finding — the only "
                                    "field carrying the measured vacuity (SPEC §3.2.1 route 2)")
                if _out != "vacuous" and _vf:
                    rep.fail(_rlbl, f"vacuity_finding present on outcome={_out!r} — REQUIRED exactly "
                                    "when outcome='vacuous', MUST be absent otherwise (SPEC §3.1)")

                # Governing entry (§3.1/§6.2): the row itself for an executor ADD; the frozen brief
                # entry for an orchestrator row — the ONLY branch that joins, and it is guarded, so a
                # row already reported in extra_ids never reaches the floor.
                if _org == "executor":
                    _gov = _r
                elif _i48_hashable(_rid) and _rid in _i48_byid:
                    _gov = _i48_byid[_rid]
                else:
                    continue
                _cf = _gov.get("check_form")

                # I48-5 — §6.2 tier_shortfall: evidence_tier below the derived floor.
                # `dict.get(k)` HASHES k, so the floor lookup below is a hash site on TWO untrusted
                # values — the governing entry's check_form (reachable from BOTH origins: the frozen
                # brief entry on an orchestrator row, the row itself on an executor ADD) and the row's
                # evidence_tier. Same discipline as every other site in this block: filter through
                # _i48_hashable, and REPORT the offending value rather than skip it silently.
                _i48_cfh, _i48_tih = _i48_hashable(_cf), _i48_hashable(_tier)
                if not (_i48_cfh and _i48_tih):
                    _i48_bad = ([f"check_form {_cf!r}"] if not _i48_cfh else []) + \
                               ([f"evidence_tier {_tier!r}"] if not _i48_tih else [])
                    rep.fail(_rlbl,
                             f"UNHASHABLE {' and '.join(_i48_bad)} (list/dict) — §6.2's tier floor is "
                             "a dict lookup that hashes both, so the shortfall check cannot run for "
                             "this row; reported here rather than raised, so the invariant pass still "
                             "reaches its RESULT: line")
                _floor = _I48_FLOOR.get(_cf) if _i48_cfh else None
                if _floor and _i48_tih and _I48_RANK.get(_tier, -1) < _I48_RANK[_floor]:
                    rep.fail(_rlbl, f"evidence_tier {_tier!r} is below the floor {_floor!r} derived "
                                    f"from the governing entry's check_form {_cf!r} (SPEC §2.1.0/§6.2)")

                # I48-6 — §3.2's locator FAILs: the executable cap and the shape.
                if _cf == "locator":
                    if _tier == "executable":
                        rep.fail(_rlbl, "check_form='locator' with evidence_tier='executable' — a "
                                        "locator can never reach executable (SPEC §3.2)")
                    _ck = _gov.get("check")
                    if not isinstance(_ck, str) or not _I48_LOCATOR_RE.fullmatch(_ck):
                        rep.fail(_rlbl, "check_form='locator' whose check does not fullmatch "
                                        "^[^\\s:]+:[0-9]+([ \\t][^\\n]*)?$ — a command string declared "
                                        "'locator' buys an illegitimate not-run (SPEC §3.2)")

                # I48-7 — §3.2 per-observation totality, SCOPED to discharged rows, CROSS-ARTIFACT.
                if _out != "discharged":
                    continue
                _nv = _r.get("non_vacuity")
                # U25 (DECISIONS#D24) — the iterate-over-`.get()` crash class, closed at the two
                # observation-list loci. `list(x or [])` CRASHES on a truthy non-iterable (measured:
                # `required_observations: 5` aborts main() with an uncaught TypeError BEFORE any
                # RESULT: line, from BOTH origins — the brief entry on an orchestrator row, the row
                # itself on an executor ADD) and MISDIAGNOSES every falsy container class
                # (`0`, `False`, `''`, `{}`, `0.0`), which `or []` silently rewrites to an empty list
                # so the totality check below blames the non_vacuity refs as "unknown" instead of
                # naming the malformed field. A string is worse than either: `list("abc")` yields
                # CHARACTERS, a silently plausible observation list. Same discipline as every other
                # guard in this block: REPORT the offending value in a naming row, never skip it
                # silently. This is a WIDENING of what is reported and is published as one.
                _obs, _obs_bad = [], False
                for _fk in ("required_observations", "forbidden_observations"):
                    _fv = _gov.get(_fk)
                    if _fv is None:
                        continue
                    if not isinstance(_fv, list):
                        _obs_bad = True
                        rep.fail(_rlbl,
                                 f"{_fk} is {type(_fv).__name__} {_fv!r}, not an array — §3.2's "
                                 "per-observation totality is a multiset over this list, so it "
                                 "cannot be computed for this row; reported here rather than "
                                 "raised, so the invariant pass still reaches its RESULT: line")
                        continue
                    _obs.extend(_fv)
                if not isinstance(_nv, list):
                    rep.fail(_rlbl, "outcome='discharged' without a non_vacuity[] array — REQUIRED, "
                                    "one member per observation (SPEC §3.1/§3.2)")
                    continue
                _refs = [m.get("observation_ref") for m in _nv if isinstance(m, dict)]
                _nmiss = [o for o in _obs if _refs.count(o) != _obs.count(o)]
                _nextra = [o for o in _refs if o not in _obs]
                # `_obs_bad` suppresses ONLY the multiset comparison, and only because the comparison
                # would be against a KNOWN-INCOMPLETE `_obs` — the malformed field already has its own
                # naming row above, so the defect still reaches the report exactly once. Every other
                # clause below (the per-member counterfactual FAILs) still runs.
                if not _obs_bad and (_nmiss or _nextra):
                    rep.fail(_rlbl, f"non_vacuity observation_ref multiset != required ∪ forbidden "
                                    f"observations (uncovered {sorted(set(map(str, _nmiss)))}, "
                                    f"unknown {sorted(set(map(str, _nextra)))}) — one red counterfactual "
                                    "must not certify a partly-vacuous entry (SPEC §3.2)")
                for _m in _nv:
                    if not isinstance(_m, dict):
                        continue
                    _cr = _m.get("counterfactual_result")
                    # §3.2 FAIL 1: a command-form check may never record 'not-run'.
                    if _cf == "command" and _cr == "not-run":
                        rep.fail(_rlbl, f"check_form='command' with counterfactual_result='not-run' for "
                                        f"{str(_m.get('observation_ref'))[:60]!r} — a command-form check "
                                        "MUST go red per observation; such a row is 'vacuous', never "
                                        "'discharged' (SPEC §3.2)")
                    if _cr == "not-run" and _i48_blank(_m.get("reason")):
                        rep.fail(_rlbl, "counterfactual_result='not-run' without a non-blank reason "
                                        "naming why no executable counterfactual can exist (SPEC §3.2)")
                    if _cr == "red" and "reason" in _m:
                        rep.fail(_rlbl, "reason present on counterfactual_result='red' — MUST be absent "
                                        "(SPEC §3.2)")

            # I48-8 (D13a, §6.1) — adequacy findings route into the EXISTING verify.defects[], the
            # only channel I6's blocker-on-PASS rule reads. Two arms, both post-hoc:
            #   (a) a non-discharge outcome recorded against a verdict-bearing verify with an empty
            #       defects[] is a finding that reached no channel;
            #   (b) a defect filed under a CASE ID instead of a verbatim acceptance criterion turns
            #       I6 RED (its cross-check is byte-exact membership over brief.acceptance_criteria),
            #       so routing into defects[] must carry the criterion string, not the entry id.
            _v = _i30_verifies.get(_uid)
            if isinstance(_v, dict):
                _defs = _v.get("defects") if isinstance(_v.get("defects"), list) else []
                _bad = [r.get("id") for r in _rows if r.get("outcome") in ("violated", "vacuous")]
                if _bad and not _defs:
                    rep.fail(_lbl, f"case_set_discharge records non-discharge outcome(s) for {_bad} but "
                                   "the verdict-bearing verify.json has an empty defects[] — adequacy "
                                   "findings MUST route into defects[], not audit_notes and not a "
                                   "bespoke block (SPEC §6.1 / D13a): I6 reads defects[]")
                _cunh = [repr(c) for c in (_b.get("acceptance_criteria") or [])
                         if not _i48_hashable(c)]
                if _cunh:
                    rep.fail(_lbl,
                             f"brief.acceptance_criteria carries UNHASHABLE member(s) {_cunh} "
                             "(list/dict) — I6's cross-check is byte-exact membership over this "
                             "array, which hashes every member; reported here rather than raised")
                _crit = {c for c in (_b.get("acceptance_criteria") or []) if _i48_hashable(c)}
                _ids_all = set(_i48_byid) | {r.get("id") for r in _rows
                                             if _i48_hashable(r.get("id"))}
                # The clause above guards the BRIEF-side members of the byte-exact membership test;
                # the value TESTED for membership comes from verify.json and is equally untrusted —
                # and `x in <set>` hashes x. Report it, then exclude it from the probe.
                _dunh = [repr(df.get("criterion")) for df in _defs
                         if isinstance(df, dict) and not _i48_hashable(df.get("criterion"))]
                if _dunh:
                    rep.fail(_lbl,
                             f"verify.json defect(s) carry an UNHASHABLE criterion {_dunh} "
                             "(list/dict) — §6.1's miscited-defect probe hashes this value against "
                             "the case_set id set; reported here rather than raised")
                _miscited = [df.get("criterion") for df in _defs
                             if isinstance(df, dict) and _i48_hashable(df.get("criterion"))
                             and df.get("criterion") in _ids_all
                             and df.get("criterion") not in _crit]
                if _miscited:
                    rep.fail(_lbl, f"defect criterion(s) {_miscited} are case_set ENTRY IDS, not verbatim "
                                   "members of brief.acceptance_criteria — I6's cross-check is byte-exact "
                                   "membership, so this turns I6 RED (SPEC §6.1)")
                if "case_set_findings" in _v:
                    rep.fail(_lbl, "verify.json carries a bespoke case_set_findings block — adequacy "
                                   "findings MUST go to defects[] (SPEC §6.1); a finding recorded "
                                   "anywhere else is invisible to I6")

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

    # =========================================================================
    # 1.14.0 — DRIFT & AUTONOMY (I49, I50, I51, I52, I53, I54, I56, I57, I58, I59)
    #
    # OFFLINE AND POST-HOC BY CONSTRUCTION. Every clause below reads artifacts that already exist
    # on disk and emits only `rep.fail(...)` / `rep.ok(...)` / a bare `print(...)`. None appears in
    # a transition-admission path, none writes fsm-state, and in particular NONE is a live guard on
    # the correction loop's sole back-edge LT7 (RETRY->EXECUTE): a guard there that can be false
    # leaves RETRY with no enabled out-edge => deadlock, which refutes Claim D of the termination
    # proof outright. Violations route to a report row; escalation stays on the EXISTING ESCALATE
    # branch. Mid-loop staleness is legal exactly as it is for I43/I44 — the arms that quantify over
    # a finished run fire only at P8/DONE.
    #
    # ARMING. Every predicate here is either ADOPTION-armed (silent until a run emits the key or
    # file it polices) or VERSION-gated (silent below the 1.14.0 stamp), so no archived run in
    # .wip/ changes grade on the day this ships. The one predicate that could not be adoption-armed
    # — I51-1's `run_mode` presence, because absence is exactly what it polices — is version-gated
    # with a `_skew_record` companion, which is the same posture I48 takes.
    #
    # NOT BUILT, DELIBERATELY. I55 (consequence-proportional verification depth) is DEFERRED and is
    # NOT implemented here. Its recording slice ships as two OPTIONAL, UNREAD schema fields
    # (debrief.consumed_upstream[], verify.consequence) so the deferral is an order to measure
    # rather than a burial; the housekeeping fuel counter (the enforced half of I57) is likewise
    # deferred. Both deferrals, with their adoption triggers, are recorded in
    # references/state-machine.md "Deferred mechanisms (1.14.0)".
    # =========================================================================
    _N14_SHIP = "1.14.0"
    _n14_ver = fsm.get("validator_version") if isinstance(fsm, dict) else None
    # NOTE ON STYLE, which is load-bearing rather than cosmetic: each version-gated arm below calls
    # the semver comparison for ITSELF and pairs it with its own `_skew_record`, exactly as _i27_t1
    # and _i48_t1 already do. Hoisting one shared boolean would be tidier code and would silently
    # break spec_check SC8, whose completeness rule is a 1:1 gate-to-recorder count. A refactor that
    # makes a shipped drift checker go red is a defect in the refactor, not in the checker.
    # (This comment deliberately names the helper WITHOUT its open paren: SC8 counts a bare string,
    # so a prose mention carrying the paren would inflate the gate count and fail the very check
    # this paragraph exists to respect — the same self-matching-comment trap the `_i27_semver_ge`
    # definition site already records against its own leading-`def` anchor.)

    def _n14_blank(x):
        return not str(x if x is not None else "").strip()

    def _n14_ws(s):
        return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()

    def _n14_read(rel):
        """Read a run-relative text file, or None if it is absent/unreadable. NEVER raises — the
        L29 crash class (an unguarded index or a bare comprehension over a missing key) takes the
        whole validator non-zero on a run it used to pass, silently disabling every downstream
        invariant."""
        try:
            with open(os.path.join(rd, rel), "r", encoding="utf-8", errors="replace") as _f:
                return _f.read()
        except Exception:
            return None

    _n14_decisions = _n14_read("DECISIONS.md")

    _N14_HEAD_RE_CACHE = {}

    def _n14_ref_resolves(ref):
        """(ok, why_not) for a DECISIONS.md reference. Fail-closed: a missing ledger is never read
        as 'no claim made'.

        THE ANCHOR MUST MATCH A HEADING LINE, NOT ANY SUBSTRING, and the file part must actually name
        DECISIONS.md. A bare case-insensitive substring test over the whole ledger was defeated by a
        ONE-CHARACTER anchor: measured, `DECISIONS.md#a`, `DECISIONS.md#e`, `#a`, `a`,
        `NOTES.md#D01` and `SOMEWHERE_ELSE.md#the` ALL resolved against a four-line DECISIONS.md, so
        the red fixture for I49-2 went fully green. `DECISIONS.md#zzz` was very nearly the only shape
        that still fired. A debt whose ref resolves to an arbitrary letter is not in the ledger in any
        sense the next run can use."""
        if _n14_blank(ref):
            return (False, "blank reference")
        if _n14_decisions is None:
            return (False, "no DECISIONS.md under the run dir")
        _t = str(ref).strip()
        _file, _sep, _anchor = _t.partition("#")
        if not _sep:
            _file, _sep, _anchor = _t.rpartition(":")
            if not _sep:
                _file, _anchor = _t, ""
        _file, _anchor = _file.strip(), _anchor.strip()
        if _file and os.path.basename(_file).lower() != "decisions.md":
            return (False, f"reference {ref!r} names {_file!r}, not DECISIONS.md")
        if len(_anchor) < 2:
            return (False, f"reference {ref!r} carries no usable anchor "
                           "(an anchor under two characters resolves against almost any ledger)")
        _re_key = _anchor.lower()
        _hre = _N14_HEAD_RE_CACHE.get(_re_key)
        if _hre is None:
            # A heading line carrying the anchor, or an explicit <a id="..."> — the two shapes a
            # DECISIONS.md entry is actually addressable by.
            _hre = re.compile(r"^\s{0,3}#{1,6}\s.*" + re.escape(_anchor)
                              + r"|<a\s+id=[\"']" + re.escape(_anchor) + r"[\"']",
                              re.M | re.I)
            _N14_HEAD_RE_CACHE[_re_key] = _hre
        if _hre.search(_n14_decisions):
            return (True, None)
        return (False, f"anchor {_anchor!r} matches no DECISIONS.md heading (or <a id=…>) — a "
                       "substring anywhere in the prose is not a resolvable reference")

    # ---- canonical unit order (declared, because the run directory supplies no chronology) ------
    # I54-2 and I56-1 both count "after", and NOTHING on disk dates a unit: verify.schema.json,
    # debrief.schema.json and graph.schema.json each carry ZERO timestamp keys, and graph.json
    # orders WAVES, never units inside one. So the order is STIPULATED — graph.json.waves[] in wave
    # order, tie-broken by ascending unit id — and both FAIL messages name the rule they used, so an
    # intra-wave disagreement is diagnosable as a disagreement about RECONSTRUCTION rather than read
    # as evidence of narration. Within a wave this is a canonical reconstruction, NOT real time.
    _N14_ORDER_RULE = "graph.json.waves[] in wave order, tie-broken by ascending unit id"
    # AND THE ORDER SOURCE MUST EXIST. `waves` is OPTIONAL in graph.schema.json and I3b SKIPs when it
    # is absent with no amendments — so deleting one optional key silently degraded the "stipulated"
    # order to ALPHABETICAL UNIT ID, which has no relation to execution order, while both FAIL
    # messages went on naming the wave-order rule. Measured: two run dirs differing ONLY in the
    # presence of `waves`, one FAILing both I54-2 and I56 and the other a clean PASS. The sentinel
    # that sorts wave-less units LAST reasons in the wrong direction here — LAST is the position that
    # RESETS a streak. So a run that adopts either mechanism owes the order source it is counted by.
    _n14_units_by_id = {}
    _n14_wave_of = {}
    if isinstance(graph_doc, dict):
        for _gu in (graph_doc.get("units") or []):
            if isinstance(_gu, dict) and isinstance(_gu.get("id"), str):
                _n14_units_by_id[_gu["id"]] = _gu
        for _wv in (graph_doc.get("waves") or []):
            if not isinstance(_wv, dict):
                continue
            _wn = _as_int(_wv.get("wave"))
            for _wu in (_wv.get("units") or []):
                if isinstance(_wu, str) and _wn is not None:
                    _n14_wave_of[_wu] = _wn
    # Units with no wave row sort LAST (a large sentinel), never silently first: a unit the waves[]
    # table forgot must not be able to reset a starvation streak by accident of ordering.
    _n14_order = sorted(_n14_units_by_id, key=lambda u: (_n14_wave_of.get(u, 10 ** 6), u))

    def _n14_verdict(uid):
        _v = unit_docs.get(uid, {}).get("verify")
        return _v.get("verdict") if isinstance(_v, dict) else None

    # -------------------------------------------------------------------------------------------
    # I49 — horizon record (Ask 1: internal re-evaluation inside every Socratic dialogue)
    # ADOPTION-armed and ADOPTION-CLOSED: silent until a run writes its first `horizon`, and then
    # required on EVERY dialogue instance and every socratic block in that run. Partial adoption is
    # a FAIL by design, because a half-adopted horizon record is how "we only wrote it down when it
    # flattered us" would look.
    # -------------------------------------------------------------------------------------------
    _n14_h_stem = LABEL_STEM["i49_horizon"]
    _n14_h_sites = []          # (label, horizon, surface_id, recommended_set)
    # SITES ARE BUILT FROM THE **RAW** JSON, NOT FROM THE SCHEMA-VALIDATED DOCS, and that is the whole
    # difference between a predicate and a decoration. The schemas enforce the debt iff themselves
    # (`allOf` if/then plus `not: {required: [debt]}`), so a document that violates it is rejected one
    # layer earlier, dropped from `docs`/`unit_docs`, and its site DISAPPEARED — leaving I49 to print
    # `PASS … debt iff + anti-strawman join hold` over a site set it had silently shrunk from 4 to 3,
    # on a run containing exactly the violation it claims to have checked. Measured on the shipped
    # `horizon_debt_on_durable` fixture, whose whole job is that arm: it never reached I49 at all.
    # Reading raw makes every arm reachable and keeps the site count honest; each arm below is
    # isinstance-guarded because raw input is untrusted by definition.
    def _n14_raw(rel):
        _p = os.path.join(rd, rel)
        if not os.path.isfile(_p):
            return None
        try:
            return load_json(_p)
        except Exception:
            return "<unreadable>"

    _n14_h_indeterminate = []
    _n14_dlg_doc = _n14_raw("dialogues.json")
    if _n14_dlg_doc == "<unreadable>":
        _n14_h_indeterminate.append("dialogues.json")
        _n14_dlg_doc = None
    if isinstance(_n14_dlg_doc, dict):
        for _di, _dd in enumerate(_n14_dlg_doc.get("dialogues") or []):
            if not isinstance(_dd, dict):
                continue
            _recs = set()
            for _rr in (_dd.get("rounds") or []):
                if not isinstance(_rr, dict):
                    continue
                for _qq in (_rr.get("questions") or []):
                    if isinstance(_qq, dict) and isinstance(_qq.get("recommended"), str):
                        _recs.add(_n14_ws(_qq["recommended"]))
            _n14_h_sites.append((f"dialogues.json[{_dd.get('instance') or _di}]",
                                 _dd.get("horizon"), _dd.get("surface_id"), _recs))
    for _uid in sorted(unit_subdirs):
        for _kind in ("debrief", "verify"):
            _doc = _n14_raw(f"units/{_uid}/{_kind}.json")
            if _doc is None:
                continue
            if _doc == "<unreadable>":
                _n14_h_indeterminate.append(f"units/{_uid}/{_kind}.json")
                continue
            if not isinstance(_doc, dict):
                continue
            _soc = _doc.get("socratic")
            if isinstance(_soc, dict):
                _n14_h_sites.append((f"units/{_uid}/{_kind}.json:socratic",
                                     _soc.get("horizon"), None, None))
    # ARMING IS A CONJUNCTION — adoption AND the 1.14.0 stamp — and the second conjunct is NOT
    # defensive style, it is a MEASURED repair. `socratic` is additionalProperties:true and the
    # dialogues element was open to an undeclared key, so a run written BEFORE this shipped could
    # already carry a `horizon`, and one does: the run that DESIGNED this invariant dogfooded the
    # field in its own assembly unit. Measured on this tree —
    #   grep -rl '"horizon"' .wip/2026-08-09_140537_dag-drift-and-autonomy-redesign --include='*.json'
    #   -> units/U14/debrief.json, units/U14/verify.json
    # — and a pure content-adoption gate armed on it, adding 30 I49-1 FAIL rows to an archived run
    # (20 -> 50) on the day this shipped. THAT IS THE ADOPTION GATE LEAKING, not a defect in the
    # archive. A content trigger is only archive-safe where the key was previously SCHEMA-FORBIDDEN
    # (progress_clock, context_contract, deliverable, priority_class, kind:'resequence' all are,
    # since their parent objects are additionalProperties:false); where the parent object was OPEN,
    # the version stamp is the only sound gate.
    _n14_h_adopted = (any(isinstance(_h, dict) for (_, _h, _, _) in _n14_h_sites)
                      and _i27_semver_ge(_n14_ver, _N14_SHIP))
    _skew_record("I49-T1", any(isinstance(_h, dict) for (_, _h, _, _) in _n14_h_sites),
                 _N14_SHIP, _n14_ver)
    if _n14_h_adopted:
        _n14_h_bad = False
        if _n14_h_indeterminate:
            # Never print a clean PASS over a site set that could not be read: an unparseable
            # artifact is an UNKNOWN site, not an absent one.
            rep.fail(f"{_n14_h_stem} (site set indeterminate)",
                     f"{_n14_h_indeterminate} could not be parsed, so the adoption-closure count "
                     "below is over an incomplete site set and I49-1 cannot be decided for them")
            _n14_h_bad = True
        for _lbl, _h, _sid, _recs in _n14_h_sites:
            # I49-1 presence closure
            if _h is not None and not isinstance(_h, dict):
                rep.fail(f"{_n14_h_stem} ({_lbl})",
                         f"`horizon` is {type(_h).__name__}, not an object — I49-1")
                _n14_h_bad = True
                continue
            if not isinstance(_h, dict):
                rep.fail(f"{_n14_h_stem} ({_lbl})",
                         "this run has ADOPTED `horizon` (at least one site carries one) but this "
                         "site does not — I49-1 adoption closure. Partial adoption is a FAIL by "
                         "design: a horizon recorded only where it flatters the run is not a record")
                _n14_h_bad = True
                continue
            # I49-2 debt has teeth
            _choice = _h.get("choice")
            _debt = _h.get("debt")
            if _choice == "expedient":
                if not isinstance(_debt, dict):
                    rep.fail(f"{_n14_h_stem} ({_lbl})",
                             "choice == 'expedient' with no `debt` object — I49-2. A debt with no "
                             "revisit condition is an excuse")
                    _n14_h_bad = True
                else:
                    if _n14_blank(_debt.get("revisit_condition")):
                        rep.fail(f"{_n14_h_stem} ({_lbl})",
                                 "choice == 'expedient' with a blank debt.revisit_condition — I49-2")
                        _n14_h_bad = True
                    _ok_ref, _why_ref = _n14_ref_resolves(_debt.get("decisions_ref"))
                    if not _ok_ref:
                        rep.fail(f"{_n14_h_stem} ({_lbl})",
                                 f"debt.decisions_ref does not resolve: {_why_ref} — I49-2. A debt "
                                 "not in the ledger is invisible to the next run")
                        _n14_h_bad = True
            elif _choice == "durable" and _debt is not None:
                rep.fail(f"{_n14_h_stem} ({_lbl})",
                         "a `debt` block is present on choice == 'durable' — I49-2 backward half. "
                         "Forbidding it here is what makes `grep -l revisit_condition` an EXACT "
                         "inventory of the run's debts rather than a list of decorations")
                _n14_h_bad = True
            # I49-3 anti-strawman join (elicitation surfaces only)
            if _sid in ("DS-2", "DS-4") and isinstance(_recs, set):
                _exp = _n14_ws(_h.get("expedient"))
                if _exp and _exp not in _recs:
                    rep.fail(f"{_n14_h_stem} ({_lbl})",
                             f"horizon.expedient does not match any question's `recommended` string "
                             f"in this instance — I49-3, the anti-strawman join. You cannot strawman "
                             f"an option you already recommended. Offered strings: "
                             f"{sorted(_recs) if _recs else '(none)'}")
                    _n14_h_bad = True
        if not _n14_h_bad:
            rep.ok(f"{_n14_h_stem} ({len(_n14_h_sites)} site(s) closed; debt iff + anti-strawman join hold)")

    # -------------------------------------------------------------------------------------------
    # I50 — plain-language prose bounds (Ask 2, ONE ARM OF THREE).
    # Only `i50_prose_bounds` ships. The other two arms of the source recommendation — term coverage
    # and anchor resolution — are preconditioned on a RUN_DIR/GLOSSARY.md that exists NOWHERE in the
    # tree, and run against a directory with no glossary THEY WOULD FAIL EVERY RUN. They are
    # deferred until that artifact ships; see references/state-machine.md "Deferred mechanisms".
    # VERSION-gated (not adoption-gated), because the thing it polices is prose every run already
    # writes — there is no key whose appearance could arm it without also re-grading every archive.
    # -------------------------------------------------------------------------------------------
    _N14_PROSE_FILES = ("PLAN.md", "DECISIONS.md", "PROGRESS.md", "LEARNINGS.md",
                        "CLARIFICATIONS.md", "DIALOGUES.md", "SYNTHESIS.md")
    _N14_MAX_WPS, _N14_MEAN_WPS, _N14_ARI, _N14_SHARE = 60, 18.0, 14.0, 0.50
    # MINIMUM CORPUS for the AGGREGATE bounds. The three thresholds were fitted against four real
    # files carrying 45-181 scorable sentences and 685-3,717 words; ARI in particular
    # (4.71 x chars/word + 0.5 x mean - 21.43) is a continuous-prose index and is NOISE over a
    # handful of fragmentary lines. MEASURED, and this is why the floor exists rather than being
    # tidiness: on a FRESHLY SCAFFOLDED, EMPTY run — before anyone has written a word — the seeded
    # PLAN.md scored 7 sentences / 44 words / ARI 15.4 and the seeded DECISIONS.md scored
    # prose_share 0.40, so BOTH went red. That is the wrong-direction defect, which is the worse
    # one: it pays an author to PAD AN EMPTY LEDGER to buy a green.
    #
    # THE SPLIT IS PRINCIPLED, NOT A WEAKENING. `max_wps` is a property of ONE SENTENCE and needs no
    # corpus at all — a 90-word sentence is a 90-word sentence in a two-line file — so it ALWAYS
    # applies. The three AGGREGATE bounds (mean, ARI, prose-line share) are statistics over a
    # population and are only meaningful once one exists. 30 sits comfortably below the smallest
    # fitted corpus (45), so nothing the thresholds were calibrated against escapes.
    #
    # DISCLOSED ESCAPE: a file kept permanently under 30 scorable sentences is never scored on the
    # aggregates. On a real run PLAN/DECISIONS/PROGRESS/SYNTHESIS grow past it; a run that keeps
    # every ledger tiny has other problems. The longest-sentence bound bites at any size.
    _N14_MIN_SENTENCES = 30
    # Thresholds are set from the measured corpora, not from taste: three passing files top out at
    # 38/48/50-word longest sentences, means 14.3/14.4/15.2 and ARI 9.4/9.6/10.9, against a failing
    # file's 90-word sentence, mean 20.5 and ARI 15.3. A sentence splitter is a HEURISTIC and a
    # different heuristic gives different numbers — any reimplementation must re-fit these rather
    # than inherit them.
    _N14_SENT_RE = re.compile(r"(?<=[.!?])(?:\*{1,2}|_{1,2})?\s+")
    _N14_CODE_RE = re.compile(r"`[^`]*`")
    # A bare PATH is machine text, not prose, and is normalised to a single short word before
    # scoring. This is not tidiness — it repairs a MEASURED collision between two predicates
    # shipped in the same change: I59 REQUIRES every obligation line in PROGRESS.md to name the
    # run-directory file it read, and a 30-character path counts as one word with thirty characters,
    # which drives ARI (4.71 x chars/word + ...) straight through the bound. Without this, a run
    # that satisfies I59 exactly is FAILED by I50 for doing so. The exemption can only LOWER a
    # score, and only on lines carrying machine identifiers, so it cannot launder prose: a sentence
    # is still counted at its true word length. Same doctrine as the existing fence and table
    # exemptions — score the sentences that frame the machine text, never the machine text.
    _N14_PATH_RE = re.compile(r"(?<!\S)(?:[A-Za-z0-9_.-]*/[A-Za-z0-9_./#-]+"
                              r"|[A-Za-z0-9_.-]+\.(?:json|md|py|sh|tsv|tla|als|cfg))(?!\S)")
    _N14_ROW_RE = re.compile(r"^\s*\|")
    _N14_FENCE_RE = re.compile(r"^\s*(```|~~~)")
    # A LIST ITEM and an ATX HEADING each end a paragraph, exactly as a table row does. Without this
    # the scorer joins consecutive lines with " " and then splits on terminal punctuation, so a bullet
    # list whose items lack full stops collapses into ONE enormous "sentence" — it measures MARKDOWN
    # PUNCTUATION, not sentence length. Measured: two files with identical content and identical
    # readability, differing only in trailing periods, graded differently (66-word "sentence" vs a
    # true longest of 8), and a real archived PROGRESS.md scored max_wps 935 on a concatenated wall of
    # shell tokens and paths that is not a sentence at all. That is the wrong-direction class again:
    # it pays an author to sprinkle full stops into a good artifact.
    _N14_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>\s)")

    def _n14_prose_score(text):
        """Score PROSE LINES ONLY. Tables, tallies and fenced commands are exempt BY CONSTRUCTION,
        so the rule bites on the sentences that frame numbers and never asks anyone to delete one —
        which is what keeps it from fighting BB-L44 (no count without the command that produced it)
        and losing. The prose-line FLOOR closes the wholesale escape of moving everything into
        tables or a fence; it does NOT close a selective one, and that limit is disclosed rather
        than argued away (moving 33 of 131 prose lines was measured to buy a green)."""
        _in_fence = False
        _paras, _cur = [], []
        _cand = _prose = 0
        for _ln in str(text or "").split("\n"):
            if _N14_FENCE_RE.match(_ln):
                _in_fence = not _in_fence
                if _cur:
                    _paras.append(_cur)
                    _cur = []
                continue
            if _in_fence:
                # FENCED LINES COUNT IN THE DENOMINATOR, exactly as table rows do. Excluding them
                # left the WHOLESALE fence escape wide open while the code claimed to have closed it:
                # measured, wrapping all seven ledger files of a real run in a fence and leaving three
                # trivial prose lines outside turned four FAILs into a clean PASS, and an
                # UNTERMINATED fence did the same. Exempting text from SCORING is right — a fenced
                # command is not prose — but exempting it from the SHARE is what made the exemption an
                # escape hatch.
                _cand += 1
                continue
            if not _ln.strip():
                if _cur:
                    _paras.append(_cur)
                    _cur = []
                continue
            _cand += 1
            if _N14_ROW_RE.match(_ln):
                if _cur:
                    _paras.append(_cur)
                    _cur = []
                continue
            if _N14_ITEM_RE.match(_ln):
                # A list item or heading is its own paragraph: end the previous one, start a new one.
                if _cur:
                    _paras.append(_cur)
                _prose += 1
                _cur = [_ln]
                continue
            _prose += 1
            _cur.append(_ln)
        if _cur:
            _paras.append(_cur)
        _share = (float(_prose) / _cand) if _cand else 0.0
        _sents = []
        for _p in _paras:
            _t = _N14_PATH_RE.sub("file", _N14_CODE_RE.sub(" ", " ".join(_p)))
            for _frag in _N14_SENT_RE.split(_t):
                _w = _frag.split()
                if len(_w) >= 3:
                    _sents.append(_w)
        _out = {"prose_lines": _prose, "candidate_lines": _cand,
                "prose_share": round(_share, 3), "sentences": len(_sents)}
        if not _sents:
            _out["code"] = "TOO-SHORT-TO-SCORE"
            return _out
        # The longest sentence is scored at ANY size — it needs no corpus.
        _out["max_wps"] = max(len(_s) for _s in _sents)
        if len(_sents) < _N14_MIN_SENTENCES:
            _out["code"] = "TOO-SHORT-TO-SCORE"
            return _out
        if _share < _N14_SHARE:
            _out["code"] = "NO-PROSE-LINES"
            return _out
        _words = sum(len(_s) for _s in _sents)
        _chars = sum(len("".join(_s)) for _s in _sents)
        _mean = float(_words) / len(_sents)
        _out.update({"code": None, "words": _words, "mean_wps": round(_mean, 1),
                     "max_wps": max(len(_s) for _s in _sents),
                     "ari": round(4.71 * (float(_chars) / _words) + 0.5 * _mean - 21.43, 1)})
        return _out

    _n14_prose_present = [_f for _f in _N14_PROSE_FILES if os.path.exists(os.path.join(rd, _f))]
    _skew_record("I50-T1", bool(_n14_prose_present), _N14_SHIP, _n14_ver)
    if _n14_prose_present and _i27_semver_ge(_n14_ver, _N14_SHIP):
        _n14_p_stem = LABEL_STEM["i50_prose_bounds"]
        # accepted_prose[] — the recorded, greppable override, in the accepted_incomplete idiom:
        # available but LOUD. It never suppresses (a named file still prints an N-I50 NOTE), never
        # covers a file it does not name, and FAILS CLOSED if malformed.
        _n14_ap = fsm.get("accepted_prose") if isinstance(fsm, dict) else None
        _n14_ap_files, _n14_ap_bad = set(), None
        if _n14_ap is not None:
            if not isinstance(_n14_ap, dict):
                _n14_ap_bad = "accepted_prose is not an object"
            elif not (isinstance(_n14_ap.get("files"), list) and _n14_ap.get("files")
                      and all(isinstance(_x, str) and _x.strip() for _x in _n14_ap["files"])):
                _n14_ap_bad = "accepted_prose.files must be a non-empty list of non-blank strings"
            # The well-formedness conditions are the `accepted_incomplete` ones VERBATIM — str-ness,
            # a non-blank rationale, a ref naming DECISIONS.md, and DECISIONS.md actually on disk.
            # An earlier revision omitted the str-ness and existence conjuncts, which made this
            # override strictly WEAKER than both the idiom it claims to copy and the I49-2 debt ref
            # shipped twenty lines away: `rationale: 7`, `decision_ref: {"a": "DECISIONS.md"}` and a
            # ref to a DECISIONS.md that had been deleted were all accepted as well-formed.
            elif not isinstance(_n14_ap.get("rationale"), str) or _n14_blank(_n14_ap.get("rationale")):
                _n14_ap_bad = "accepted_prose.rationale is blank or not a string"
            elif not isinstance(_n14_ap.get("decision_ref"), str) \
                    or "DECISIONS.md" not in _n14_ap["decision_ref"]:
                _n14_ap_bad = "accepted_prose.decision_ref is not a string naming DECISIONS.md"
            elif _n14_decisions is None:
                _n14_ap_bad = ("accepted_prose names DECISIONS.md but no DECISIONS.md exists under "
                               "the run dir")
            else:
                _n14_ap_files = {_x.strip() for _x in _n14_ap["files"]}
        if _n14_ap_bad:
            rep.fail(f"{_n14_p_stem} (accepted_prose malformed)",
                     f"{_n14_ap_bad} — a malformed override covers NOTHING and fails closed, so the "
                     "prose bounds below still bind on every file")
        _n14_p_bad = False
        _n14_p_scored = 0
        _n14_p_read = 0
        for _pf in _n14_prose_present:
            _txt = _n14_read(_pf)
            if _txt is None:
                # FAIL-OPEN REPAIR: an I/O failure is NOT "nothing to check". Silently skipping it
                # made deleting or chmod-000-ing a ledger a strictly positive move — the breach row
                # vanished and the closing rep.ok still counted the file as "within" the bounds.
                rep.fail(f"{_n14_p_stem} ({_pf})",
                         "the file is present but could not be read (unreadable, or not a regular "
                         "file) — an I/O failure is not evidence that the prose is fine")
                _n14_p_bad = True
                continue
            _n14_p_read += 1
            _sc = _n14_prose_score(_txt)
            _breaches = []
            # The per-sentence bound binds at ANY corpus size; the aggregates need a population.
            if _sc.get("max_wps", 0) > _N14_MAX_WPS:
                _breaches.append(f"longest sentence {_sc['max_wps']} > {_N14_MAX_WPS} words")
            if _sc.get("code") == "NO-PROSE-LINES":
                _breaches.append(f"NO-PROSE-LINES (prose_share {_sc['prose_share']} < {_N14_SHARE}, "
                                 f"{_sc['sentences']} scorable sentence(s))")
            elif _sc.get("code") is None:
                if _sc["mean_wps"] > _N14_MEAN_WPS:
                    _breaches.append(f"mean {_sc['mean_wps']} > {_N14_MEAN_WPS} words/sentence")
                if _sc["ari"] > _N14_ARI:
                    _breaches.append(f"ARI {_sc['ari']} > {_N14_ARI}")
            if not _breaches:
                continue
            # OBSERVABLE, NOT ENFORCED — and this is a DELIBERATE DOWNGRADE from the source
            # recommendation's ENFORCED grade, made on a measurement that recommendation did not
            # have. It fitted its three thresholds against FOUR files. Measured here against the
            # WHOLE corpus — all 127 ledger files across the 21 archived runs, with the repaired
            # scorer — **48 of 127 (37%) breach at least one bound, in 17 of the 21 runs**, and the
            # breaches are real: the longest is a genuine 95-word sentence, not a scorer artifact.
            # Four of the seven ledgers in the very run that DESIGNED this predicate fail it.
            #
            # A hard FAIL there would not be obeyed, it would be ROUTED AROUND — every file named in
            # `accepted_prose` on day one — which is this document's own argument against a gate that
            # becomes noise, turned on itself. Archive safety is also only on LOAN: the version gate
            # protects archived runs today, but SKILL.md mandates `--restamp` on every phase advance,
            # which is designed to END that protection.
            #
            # So the bound SHIPS AND REPORTS, and does not fail a run. PROMOTION TRIGGER, so this is a
            # deferral and not a burial: promote to `rep.fail` when one full run's ledger files clear
            # all four bounds without naming a single file in `accepted_prose`. Re-measure the corpus
            # first — the command is in spec/invariants.json's I50 entry — rather than inheriting the
            # 48/127 above, which is dated the instant it is written.
            _n14_p_scored += 1
            _n14_ack = " (ACKNOWLEDGED in fsm-state.accepted_prose)" if _pf in _n14_ap_files else ""
            print(f"  NOTE  {LABEL_STEM['note_i50']} ({_pf}){_n14_ack}: {'; '.join(_breaches)}. "
                  f"Scored over PROSE LINES ONLY — tables, tallies and fenced commands are exempt by "
                  f"construction, so this never asks anyone to delete a number — {_sc}. ADVISORY: "
                  "this reports and does not fail the run.")
        rep.ok(f"{_n14_p_stem} ({_n14_p_read} of {len(_n14_prose_present)} ledger file(s) scored, "
               f"{_n14_p_scored} over max {_N14_MAX_WPS} / mean {_N14_MEAN_WPS} / ARI {_N14_ARI} / "
               f"share {_N14_SHARE}; OBSERVABLE — reported, never failed)")

    # -------------------------------------------------------------------------------------------
    # I51 — the machine-decision channel (Ask 3: fully automatic mode). THE ONE **REVISES**.
    # Today a run at DONE asserts a human signed off. After this, a run at DONE asserts a human
    # signed off OR a machine closed sign-off under a recorded mode with a recorded analyst. That
    # is a WEAKER sentence than the one dag makes today, and it is made openly rather than by
    # editing SKILL.md's "setting it without a human is a defect" — which stays literally true and
    # unedited, because a machine-closed gate sets a DIFFERENT key that no human ever sets.
    # It detects CONFLATION, never FORGERY.
    # -------------------------------------------------------------------------------------------
    _N14_GATES = (("personas", "personas_confirmed", "personas_machine_closed", "DS-1"),
                  ("clarification", "clarification_resolved", "clarification_machine_closed", "DS-2"),
                  ("signoff", "signoff_confirmed", "signoff_machine_closed", "DS-5"))
    _n14_mc_stem = LABEL_STEM["i51_machine_gate"]
    _n14_mode = fsm.get("run_mode") if isinstance(fsm, dict) else None
    _n14_md = docs.get("machine-decisions")
    _n14_md_recs = (_n14_md.get("decisions") or []) if isinstance(_n14_md, dict) else []
    _n14_mclosed = {_g: (gates.get(_mk) is True) for _g, _hk, _mk, _s in _N14_GATES}
    _n14_any_machine = any(_n14_mclosed.values()) or bool(_n14_md_recs)

    def _n14_critical(_rec):
        """Clause-by-clause recomputation of critical(q) from the record's OWN fields, so an
        orchestrator cannot quietly narrow the definition. An honest PROXY: measurable and
        re-derivable, and not a claim that every genuinely consequential question falls inside it."""
        if _rec.get("gate") in ("signoff", "disagreement"):
            return True                                    # clause 1, gate-level form
        if _rec.get("surface_id") in ("DS-4", "DS-5"):
            return True                                    # clause 1, surface-level form
        _ea = _rec.get("edits_anchor")
        if isinstance(_ea, list) and any(_x in ("definition_of_done", "non_goals") for _x in _ea):
            return True                                    # clause 2 — the question would move scope
        _an = _rec.get("analyst") if isinstance(_rec.get("analyst"), dict) else {}
        _av = _n14_ws(_an.get("verdict")).lower()
        if _av == "abstain":
            return True                                    # clause 4a — refusal or tie
        try:
            if float(_an.get("confidence")) < 0.7:
                return True                                # clause 4b
        except (TypeError, ValueError):
            return True                                    # unreadable confidence => fail closed
        if _av != _n14_ws(_rec.get("orchestrator_recommendation")).lower():
            return True                                    # clause 3 — the analyst contradicts
        return False

    # I51-1 (mode declared) — VERSION-gated. Written unarmed this reds every archived run in .wip/,
    # because run_mode is a NEW top-level fsm-state property; that is the concrete breakage the
    # gate exists to prevent, and the archive fixtures are what prove it did.
    _n14_past_p1 = phase in ("P2_CLARIFICATION", "P3_CARTOGRAPHY", "P4_DECOMPOSITION",
                             "P5_BRIEFING", "P6_EXECUTE_VERIFY", "P7_DISAGREEMENT_GATE",
                             "P8_SYNTHESIS", "DONE")
    _skew_record("I51-1", bool(fsm) and _n14_past_p1, _N14_SHIP, _n14_ver)
    if fsm and _n14_past_p1 and _i27_semver_ge(_n14_ver, _N14_SHIP):
        if _n14_mode not in ("manual", "critical-only", "automatic"):
            rep.fail(f"{_n14_mc_stem} (I51-1 mode declared)",
                     f"fsm-state.run_mode is {_n14_mode!r} — from P2 onward a run must DECLARE its "
                     "autonomy mode (manual | critical-only | automatic), chosen at a Phase-0/1 "
                     "dialogue with NO ASSUMED DEFAULT")
        else:
            rep.ok(f"{_n14_mc_stem} (I51-1 run_mode={_n14_mode!r})")

    # Same conjunction, same reason: `gates` is additionalProperties:true, so a `*_machine_closed`
    # key was already writable before this shipped and a content-only trigger is not archive-sound.
    _skew_record("I51-2..6", _n14_any_machine, _N14_SHIP, _n14_ver)
    if ((_n14_any_machine or _n14_mode in ("critical-only", "automatic"))
            and _i27_semver_ge(_n14_ver, _N14_SHIP)):
        _n14_mc_bad = False
        _n14_by_gate = {}
        for _r in _n14_md_recs:
            if isinstance(_r, dict):
                _n14_by_gate.setdefault(_r.get("gate"), []).append(_r)
        for _g, _hk, _mk, _surface in _N14_GATES:
            # I51-2 (exclusivity) — a run may NEVER claim both a human and a machine closed one gate.
            if gates.get(_hk) is True and gates.get(_mk) is True:
                rep.fail(f"{_n14_mc_stem} (I51-2 exclusivity, {_g})",
                         f"gates.{_hk} and gates.{_mk} are BOTH true — one gate, two deciders. The "
                         "machine path may not reach the human vocabulary even by mistake")
                _n14_mc_bad = True
            if not _n14_mclosed[_g]:
                continue
            # I51-3 (backing) — the MC-2 shape (a set flag must be backed by a record), copied.
            _backing = [_r for _r in _n14_by_gate.get(_g, [])
                        if _r.get("decided_by") == "machine"
                        and not _n14_blank((_r.get("analyst") or {}).get("reasoning"))]
            if not _backing:
                rep.fail(f"{_n14_mc_stem} (I51-3 backing, {_g})",
                         f"gates.{_mk} is true but machine-decisions.json carries no record for gate "
                         f"{_g!r} with decided_by == 'machine' and a non-blank analyst.reasoning")
                _n14_mc_bad = True
            # I51-6 (channel disjointness) — the two channels never both describe the same gate.
            _dlg_hits = []
            if isinstance(_n14_dlg_doc, dict):
                _dlg_hits = [_d.get("instance") for _d in (_n14_dlg_doc.get("dialogues") or [])
                             if isinstance(_d, dict) and _d.get("surface_id") == _surface]
            if _dlg_hits:
                rep.fail(f"{_n14_mc_stem} (I51-6 channel disjointness, {_g})",
                         f"gates.{_mk} is true while dialogues.json carries {_surface} record(s) "
                         f"{_dlg_hits} for the same gate — a machine decision dressed in the human "
                         "channel. This detects CONFLATION, never forgery")
                _n14_mc_bad = True
        # THE RECORD -> FLAG DIRECTION. Every arm above keys on the FLAG, and the records were only
        # consulted INSIDE `if not _n14_mclosed[g]: continue` — so a machine-decision record with no
        # corresponding flag was invisible. Measured: a run declaring `run_mode: "manual"` with
        # `signoff_confirmed: true`, a DS-5 HUMAN dialogue, AND a machine record for the same gate
        # passed clean, while I51's own green line asserted "channels disjoint" and "mode='manual'"
        # — beside one machine closure on disk. That is the exact conflation this invariant exists
        # to detect, reported as compliance.
        for _g, _hk, _mk, _surface in _N14_GATES:
            _recs_g = [_r for _r in _n14_by_gate.get(_g, [])
                       if isinstance(_r, dict) and _r.get("decided_by") == "machine"]
            if not _recs_g:
                continue
            if gates.get(_hk) is True:
                rep.fail(f"{_n14_mc_stem} (I51-2 exclusivity by record, {_g})",
                         f"machine-decisions.json carries a machine record for gate {_g!r} while "
                         f"gates.{_hk} — the HUMAN attestation — is true. One gate, two deciders, "
                         "recorded from the other end")
                _n14_mc_bad = True
            if gates.get(_mk) is not True:
                rep.fail(f"{_n14_mc_stem} (I51-3 unflagged record, {_g})",
                         f"machine-decisions.json carries a machine record for gate {_g!r} but "
                         f"gates.{_mk} is not true — a machine decision that closed nothing, or a "
                         "closure the gates object hides")
                _n14_mc_bad = True
            if _n14_mode == "manual":
                rep.fail(f"{_n14_mc_stem} (I51-5 mode consistency by record, {_g})",
                         f"run_mode == 'manual' but a machine decision is recorded for gate {_g!r} "
                         "— manual means today's behaviour and ZERO machine closures, and that must "
                         "hold over the RECORDS, not only over the flags")
                _n14_mc_bad = True
        # I51-4 (critical recomputation) — recomputed from the record, never trusted from it.
        for _ri, _r in enumerate(_n14_md_recs):
            if not isinstance(_r, dict):
                continue
            # A record must decide something ON THE MENU, and its declared mode must be the run's.
            # I51-3 checked only that a record EXISTED: measured, `decision: "banana"` against
            # options ["accept","reject"] passed, and so did a record whose decision and analyst
            # verdict were both "reject" while `signoff_machine_closed` still satisfied DONE.
            _opts = _r.get("options") if isinstance(_r.get("options"), list) else []
            if _opts and _n14_ws(_r.get("decision")) not in {_n14_ws(_o) for _o in _opts}:
                rep.fail(f"{_n14_mc_stem} (I51-3 decision off-menu, decisions[{_ri}])",
                         f"decision {_r.get('decision')!r} is not one of the recorded options "
                         f"{_opts} — a machine decision that chose nothing offered is not a decision")
                _n14_mc_bad = True
            if _r.get("mode") is not None and _r.get("mode") != _n14_mode:
                rep.fail(f"{_n14_mc_stem} (I51-5 record mode, decisions[{_ri}])",
                         f"the record declares mode={_r.get('mode')!r} while fsm-state.run_mode is "
                         f"{_n14_mode!r} — the field is `required` in the schema, so leaving it "
                         "unread made it dead data a record could contradict the run with")
                _n14_mc_bad = True
            _want = _n14_critical(_r)
            _got = _r.get("critical")
            if _got is not _want:
                rep.fail(f"{_n14_mc_stem} (I51-4 critical recomputation, decisions[{_ri}])",
                         f"record for gate {_r.get('gate')!r} records critical={_got!r} but the "
                         f"clauses recompute critical={_want!r} — 'critical' is a RECOMPUTED "
                         "predicate, not an adjective an orchestrator may narrow")
                _n14_mc_bad = True
        # I51-5 (mode consistency)
        if _n14_mode == "manual" and any(_n14_mclosed.values()):
            rep.fail(f"{_n14_mc_stem} (I51-5 mode consistency)",
                     f"run_mode == 'manual' but "
                     f"{sorted(_g for _g in _n14_mclosed if _n14_mclosed[_g])} machine-closed — "
                     "manual means today's behaviour and ZERO machine closures")
            _n14_mc_bad = True
        if _n14_mode == "critical-only":
            for _ri, _r in enumerate(_n14_md_recs):
                if isinstance(_r, dict) and _n14_critical(_r) and _r.get("decided_by") == "machine":
                    rep.fail(f"{_n14_mc_stem} (I51-5 mode consistency, decisions[{_ri}])",
                             f"run_mode == 'critical-only' but a CRITICAL question on gate "
                             f"{_r.get('gate')!r} was machine-decided — in this mode a critical "
                             "question halts for the human")
                    _n14_mc_bad = True
        if not _n14_mc_bad:
            rep.ok(f"{_n14_mc_stem} (mode={_n14_mode!r}, {len(_n14_md_recs)} machine decision(s), "
                   "channels disjoint)")

    # -------------------------------------------------------------------------------------------
    # I52 — projection ceiling (Ask 4: orchestrator context relief).
    # ADOPTION-armed on fsm-state.context_contract. HONEST GRADE: OBSERVABLE, with ENFORCED
    # explicitly disclaimed — the size check is fully mechanical, but no predicate can establish
    # that the orchestrator READ the projection rather than answering from residual context. The
    # design makes statelessness LEGIBLE, never TRUE.
    # -------------------------------------------------------------------------------------------
    _n14_cc = fsm.get("context_contract") if isinstance(fsm, dict) else None
    if isinstance(_n14_cc, dict):
        _n14_pj_stem = LABEL_STEM["i52_projection"]
        _n14_ceiling = _as_int(_n14_cc.get("projection_ceiling_bytes"))
        # MID-RUN ADOPTION must not retroactively fail every already-landed pair at once. Measured on
        # a real archived run: adding a context_contract to
        # .wip/2026-08-02_235310_independent-test-authorship produced 28 I52 FAILs and NOTHING ELSE
        # (710 checks / 560 problems -> 711 / 588), because a 28-unit run that adopts at wave 5
        # instantly owes 28 back-filled projections. The rational orchestrator response to that is
        # NEVER TO ADOPT, which makes the mechanism self-disarming — a wrong-direction defect, and the
        # worse class. `adopted_at_wave` scopes the obligation forward; earlier units are reported as
        # an exit-neutral NOTE so the gap stays visible rather than silent.
        _n14_adopt_wave = _as_int(_n14_cc.get("adopted_at_wave"))
        _n14_recorded = {}
        for _u in (fsm.get("units") or []):
            if isinstance(_u, dict) and isinstance(_u.get("unit_id"), str):
                _n14_recorded[_u["unit_id"]] = _as_int(_u.get("projection_bytes"))
        _n14_pj_bad = False
        _n14_pj_n = 0
        _n14_pj_pre = []
        for _uid in sorted(unit_dirs_with_debrief):
            if not os.path.exists(os.path.join(rd, "units", _uid, "verify.json")):
                continue                      # a LANDED PAIR is debrief + verify; mid-loop is legal
            if _n14_adopt_wave is not None and _n14_wave_of.get(_uid, 0) < _n14_adopt_wave:
                _n14_pj_pre.append(_uid)
                continue
            _ap = os.path.join(rd, "units", _uid, "adjudication.json")
            if not os.path.isfile(_ap):
                rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                         "context_contract is adopted and this unit has a landed debrief+verify "
                         "pair, but units/%s/adjudication.json is absent (or is not a regular file) "
                         "— the orchestrator has no bounded projection to read and must ingest the "
                         "whole pair" % _uid)
                _n14_pj_bad = True
                continue
            _sz = os.path.getsize(_ap)
            _n14_pj_n += 1
            if _n14_ceiling is not None and _sz > _n14_ceiling:
                rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                         f"adjudication.json is {_sz} B > ceiling {_n14_ceiling} B "
                         "(context_contract.projection_ceiling_bytes)")
                _n14_pj_bad = True
            _rec_sz = _n14_recorded.get(_uid)
            if _rec_sz is not None and _rec_sz != _sz:
                rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                         f"fsm-state.units[].projection_bytes records {_rec_sz} B but the file on "
                         f"disk is {_sz} B — a recorded size that disagrees with the file is "
                         "narration, not a measurement")
                _n14_pj_bad = True
            # FIDELITY. A size check alone accepts a 0-byte file, a directory, prose, or a projection
            # that flatly CONTRADICTS the pair it projects — and this is the artifact the orchestrator
            # reads INSTEAD of that pair, so an unchecked projection substitutes narration for the
            # evidence, which is the exact thing I52 exists to prevent. `adjudication.json` is
            # deliberately NOT given a schema of its own (it is a derived view, not a contract), so
            # the anchor is the pair it claims to project.
            try:
                _adj = load_json(_ap)
            except Exception as _e:
                rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                         f"adjudication.json is not valid JSON: {_e} — a projection the orchestrator "
                         "reads in place of the debrief+verify pair must at least parse")
                _n14_pj_bad = True
                continue
            if not isinstance(_adj, dict) or not _adj:
                rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                         "adjudication.json is empty or is not a JSON object — an empty projection "
                         "is not a bounded view of the pair, it is the absence of one")
                _n14_pj_bad = True
                continue
            _vdoc = unit_docs.get(_uid, {}).get("verify")
            if isinstance(_vdoc, dict):
                for _k in ("verdict", "iteration"):
                    if _k in _adj and _adj.get(_k) != _vdoc.get(_k):
                        rep.fail(f"{_n14_pj_stem} (units/{_uid})",
                                 f"adjudication.json records {_k}={_adj.get(_k)!r} but "
                                 f"units/{_uid}/verify.json records {_k}={_vdoc.get(_k)!r} — a "
                                 "projection that disagrees with the artifact it projects is worse "
                                 "than no projection: the orchestrator reads THIS file instead of "
                                 "that one")
                        _n14_pj_bad = True
        if _n14_pj_pre:
            print(f"  NOTE  {_n14_pj_stem}: {len(_n14_pj_pre)} landed pair(s) predate "
                  f"context_contract.adopted_at_wave={_n14_adopt_wave} and are NOT required to carry "
                  f"a projection: {_n14_pj_pre}. Mid-run adoption is scoped forward on purpose — a "
                  "retroactive obligation would make never adopting the rational choice — but the "
                  "orchestrator still ingests those pairs whole.")
        if not _n14_pj_bad:
            rep.ok(f"{_n14_pj_stem} ({_n14_pj_n} landed pair(s) projected under "
                   f"{_n14_ceiling} B and agreeing with their verify.json; OBSERVABLE — that the "
                   "projection was READ is not decidable from artifacts)")

    # -------------------------------------------------------------------------------------------
    # I59 — obligation source-naming (the second predicate Ask 4's design needs; rendered `I52-B`
    # in the source document, which explicitly asked the implementing run to allocate a proper
    # second number. It is I59.)
    # -------------------------------------------------------------------------------------------
    if isinstance(_n14_cc, dict):
        _n14_ob_stem = LABEL_STEM["i59_obligation_source"]
        _n14_prog = _n14_read("PROGRESS.md")
        if _n14_prog is None:
            rep.fail(f"{_n14_ob_stem}",
                     "context_contract is adopted but PROGRESS.md is absent — the turn contract "
                     "says every discharged obligation names the file it read, and there is "
                     "nowhere for it to say so")
        else:
            # THE TOKEN IS `O-<NN>`, HYPHENATED, AND THAT IS NOT COSMETIC. A bare `O<NN>` collides
            # head-on with a vocabulary the skill ALREADY ships: references/evidence-standards.md
            # defines O1..O4 as evidence-admissibility rules (external system named, file/code state,
            # number/threshold, causal wording) and SKILL.md cites "O1-O4 rules". Measured, a bare
            # token FAILed real archived prose — .wip/2026-07-16_014443_dag-depth-enhancement's
            # PROGRESS.md uses "claims_owed O1-O5" — and fired on ordinary English like "O2
            # saturation" and "O3 levels". A predicate that reds a run for correctly citing the
            # skill's own evidence rules is the wrong-direction defect.
            _n14_ob_re = re.compile(r"\bO-(?:1[0-9]|2[01]|[1-9])\b")
            # THE PATH TOKEN MUST RESOLVE INSIDE THE RUN DIR. A permissive shape was satisfied by
            # `N/A`, `and/or` and `50/50` — measured, four entries that said "from memory" and "no
            # file read" in plain English all PASSED the predicate whose own message is "an
            # obligation discharged from memory is an obligation discharged from nothing" — and by
            # paths that do not exist or sit outside the run (`/etc/passwd`). Existence is the
            # cheapest thing that makes the claim mean anything; it still cannot show the file was
            # READ, which is why the grade stays OBSERVABLE.
            _n14_path_re = re.compile(r"[A-Za-z0-9_.\-/]+")
            _n14_ob_bad = 0
            _n14_ob_seen = 0
            for _li, _line in enumerate(_n14_prog.split("\n"), 1):
                _obs = _n14_ob_re.findall(_line)
                if not _obs:
                    continue
                _n14_ob_seen += len(_obs)
                _named = None
                for _tok in _n14_path_re.findall(_line):
                    if _tok.startswith("/") or ".." in _tok or "/" not in _tok and "." not in _tok:
                        continue
                    if os.path.exists(os.path.join(rd, _tok.rstrip(".,;:)"))):
                        _named = _tok.rstrip(".,;:)")
                        break
                if _named is None:
                    rep.fail(f"{_n14_ob_stem} (PROGRESS.md:{_li})",
                             f"this entry discharges {_obs} and names no run-directory file that "
                             "EXISTS — under the turn contract an obligation discharged from memory "
                             "is an obligation discharged from nothing")
                    _n14_ob_bad += 1
            if _n14_ob_bad == 0:
                # VACUITY IS ANNOUNCED, NOT HIDDEN. On the only realistic corpus the token count is
                # ZERO — no shipped normative text produced an `O-<NN>` stamp before 1.14.0 — so a
                # bare green here would be "a check that cannot go red" wearing a PASS. Say so.
                if _n14_ob_seen == 0:
                    rep.ok(f"{_n14_ob_stem} (VACUOUS: 0 `O-<NN>` obligation tokens in PROGRESS.md, so "
                           "this predicate quantified over an EMPTY SET and could not have gone red. "
                           "It binds only once the orchestrator stamps the token SKILL.md's turn "
                           "contract asks for)")
                else:
                    rep.ok(f"{_n14_ob_stem} ({_n14_ob_seen} obligation token(s) across PROGRESS.md, "
                           "each on a line naming a run-directory file that exists. PER-LINE "
                           "semantics: one resolving path discharges every obligation named on that "
                           "line. Form only — that the file was READ is not decidable)")

    # -------------------------------------------------------------------------------------------
    # I53 — directive provenance (Drift fix 1: explicit maintainer requests outrank generated work).
    # ADOPTION-armed: silent unless a run carries directives/, a directive_ref, or a priority_class.
    # ENFORCED for provenance and shape; OBSERVABLE — and UNENFORCEABLE IN PRINCIPLE — for the
    # GENUINENESS of the directive, because a true quotation of the maintainer and a fabricated one
    # are the same bytes in the same file (Limitation AD).
    # -------------------------------------------------------------------------------------------
    _n14_dirdir = os.path.join(rd, "directives")
    _n14_dirfiles = []
    if os.path.isdir(_n14_dirdir):
        try:
            _n14_dirfiles = sorted(_f for _f in os.listdir(_n14_dirdir) if _f.endswith(".json"))
        except Exception:
            _n14_dirfiles = []
    _n14_amend_dref = {}
    for _fn, _rec in amendments:
        _o = _rec.get("origin") if isinstance(_rec, dict) else None
        if isinstance(_o, dict) and _o.get("directive_ref"):
            _n14_amend_dref[_fn] = _o["directive_ref"]
    _n14_pc_units = {_uid: _gu.get("priority_class")
                     for _uid, _gu in _n14_units_by_id.items() if _gu.get("priority_class")}
    # ARMING MUST INCLUDE THE TRIGGER I53-1 POLICES. Keying it on `directives/` + `directive_ref` +
    # `priority_class` alone disarmed the predicate exactly where it matters: `graph.schema.json`
    # stipulates that an ABSENT priority_class means 'normal', so absence and "normal" are equivalent
    # by construction — yet only the written form armed the block. Measured: deleting the
    # (semantically vacuous) `priority_class: "normal"` from the `directive_unbacked` fixture took it
    # from 1 I53 row to 0 and the run fully green, with the unbacked `human_request` amendment — the
    # incident this invariant exists for — reported NOWHERE.
    #
    # BUT THE TRIGGER PREDATES THE FEATURE, so arming on it alone is an ARCHIVE LEAK — and this one
    # was measured, not reasoned about: `human_request` is used by real archived runs, and widening
    # the arming took three of them from 1/0/20 FAIL rows to 4/1/25, adding nine I53 rows to runs
    # written before a directive ledger existed. The arming is therefore the same CONJUNCTION I49
    # uses — the trigger OR an adopted artifact, AND the 1.14.0 stamp — which is archive-sound
    # precisely because no archived run carries that stamp. Content triggers alone are only safe
    # where the content was previously schema-FORBIDDEN; `human_request` never was.
    _n14_hr_amend = any(isinstance(_r, dict)
                        and (_r.get("origin") or {}).get("trigger") == "human_request"
                        for _fn, _r in amendments)
    _n14_d_content = bool(_n14_dirfiles or _n14_amend_dref or _n14_pc_units or _n14_hr_amend)
    _skew_record("I53-T1", _n14_d_content, _N14_SHIP, _n14_ver)
    if _n14_d_content and _i27_semver_ge(_n14_ver, _N14_SHIP):
        _n14_d_stem = LABEL_STEM["i53_directive"]
        _n14_d_bad = False
        # Load + schema-validate the ledger. A row that will not parse is fail-closed, never read
        # as "no claim made".
        _n14_directives = {}
        _n14_dschema = schemas.get("directive.schema.json")
        for _fn in _n14_dirfiles:
            _p = os.path.join(_n14_dirdir, _fn)
            try:
                _inst = load_json(_p)
            except Exception as _e:
                rep.fail(f"{_n14_d_stem} (directives/{_fn})", f"not valid JSON: {_e}")
                _n14_d_bad = True
                continue
            if _n14_dschema is None:
                # LOUD, never silent — mirroring the amendment loader's "no schema loaded for …" row.
                # Silence here was a fail-OPEN under the documented version-skew scenario (a
                # --schemas dir from a lagging plugin copy), and it fed an unvalidated row straight
                # into the .get() below.
                rep.fail(f"{_n14_d_stem} (directives/{_fn})",
                         "no schema loaded for directive.schema.json — the ledger row cannot be "
                         "validated, and an unvalidated directive is not a directive")
                _n14_d_bad = True
                continue
            _errs = validate(_inst, _n14_dschema)
            if _errs:
                for _e in _errs:
                    rep.fail(f"{_n14_d_stem} (directives/{_fn})", _e)
                _n14_d_bad = True
                continue
            if not isinstance(_inst, dict):
                # The L29 crash class, closed: an unguarded `.get()` on a non-object row raised
                # AttributeError, which killed main() at the SAME exit code a normal FAIL returns,
                # printed no RESULT: line, and silently disabled I54/I56/I57/I58 and the summary.
                rep.fail(f"{_n14_d_stem} (directives/{_fn})",
                         f"directive row is {type(_inst).__name__}, not an object")
                _n14_d_bad = True
                continue
            # I53-5 append-only shape: the id equals the filename stem.
            _stem_id = _fn[:-5]
            if _inst.get("id") != _stem_id:
                rep.fail(f"{_n14_d_stem} (directives/{_fn})",
                         f"id {_inst.get('id')!r} != filename stem {_stem_id!r} — I53-5. An id that "
                         "can drift from its filename makes the ledger un-greppable")
                _n14_d_bad = True
            # NOTE: there is deliberately no "duplicate id" branch here. `_stem_id` is derived from
            # the filename, and directory entries are unique, so stem-collision is UNREACHABLE — a
            # branch that cannot fire is a vacuous check, and the real duplicate risk (two rows
            # claiming one id) is already closed by the id == stem arm above.
            _n14_directives[_stem_id] = _inst
            # I53-2 the row has teeth (schema-enforced too; kept so a schema relaxation cannot
            # silently disarm the predicate).
            if _n14_blank(_inst.get("verbatim_request")) or _n14_blank(_inst.get("transcript_ref")):
                rep.fail(f"{_n14_d_stem} (directives/{_fn})",
                         "blank verbatim_request or transcript_ref — I53-2, fail-closed: a missing "
                         "quotation is never read as 'no claim made'")
                _n14_d_bad = True
        # I53-1 a human_request amendment must carry a resolving directive_ref and human_gate:true.
        for _fn, _rec in amendments:
            if not isinstance(_rec, dict):
                continue
            _o = _rec.get("origin") if isinstance(_rec.get("origin"), dict) else {}
            if _o.get("trigger") != "human_request":
                continue
            _dref = _o.get("directive_ref")
            if _n14_blank(_dref):
                rep.fail(f"{_n14_d_stem} (amendments/{_fn})",
                         "origin.trigger == 'human_request' with no origin.directive_ref — I53-1. A "
                         "directive with no ledger row is exactly the state the incident describes: "
                         "an explicit request indistinguishable from a self-generated investigation")
                _n14_d_bad = True
            if _rec.get("human_gate") is not True:
                rep.fail(f"{_n14_d_stem} (amendments/{_fn})",
                         "origin.trigger == 'human_request' with human_gate != true — I53-1")
                _n14_d_bad = True
        # I53-5 every directive_ref anywhere resolves to a file that exists.
        for _fn, _dref in sorted(_n14_amend_dref.items()):
            _target = str(_dref).split("/")[-1]
            if _target[:-5] not in _n14_directives:
                rep.fail(f"{_n14_d_stem} (amendments/{_fn})",
                         f"origin.directive_ref {_dref!r} resolves to no file under directives/ "
                         f"(present: {sorted(_n14_directives) or '(none)'}) — I53-5")
                _n14_d_bad = True
        # I53-3 priority_class is DERIVED, never asserted.
        _n14_directive_added = set()
        for _fn, _rec in amendments:
            if not isinstance(_rec, dict):
                continue
            _o = _rec.get("origin") if isinstance(_rec.get("origin"), dict) else {}
            if _o.get("trigger") != "human_request":
                continue
            _target = str(_o.get("directive_ref") or "").split("/")[-1]
            if _target[:-5] in _n14_directives:
                for _ua in (_rec.get("units_added") or []):
                    if isinstance(_ua, str):
                        _n14_directive_added.add(_ua)
        for _uid, _pc in sorted(_n14_pc_units.items()):
            if _pc == "directive" and _uid not in _n14_directive_added:
                rep.fail(f"{_n14_d_stem} (graph.json units[{_uid}])",
                         "priority_class == 'directive' but this unit appears in no units_added of "
                         "any amendment whose origin.trigger == 'human_request' with a RESOLVING "
                         "directive_ref — I53-3. The class is DERIVED, never asserted; "
                         "self-promotion with no ledger row is the drift, not the cure")
                _n14_d_bad = True
        # I53-4 the class may not drift between the graph and a frozen brief once the unit executed.
        for _uid in sorted(unit_dirs_with_debrief):
            _b = unit_docs.get(_uid, {}).get("brief")
            if not isinstance(_b, dict) or "priority_class" not in _b:
                continue
            _gpc = _n14_units_by_id.get(_uid, {}).get("priority_class", "normal") or "normal"
            _bpc = _b.get("priority_class") or "normal"
            if _gpc != _bpc:
                rep.fail(f"{_n14_d_stem} (units/{_uid})",
                         f"priority_class differs between graph.json ({_gpc!r}) and the frozen "
                         f"brief.json ({_bpc!r}) on an EXECUTED unit — I53-4, riding the existing "
                         "I17 content anchor. This STRENGTHENS the frozen prefix; it relaxes nothing")
                _n14_d_bad = True
        if not _n14_d_bad:
            rep.ok(f"{_n14_d_stem} ({len(_n14_directives)} ledger row(s), "
                   f"{len(_n14_amend_dref)} amendment reference(s) resolve; genuineness stays "
                   "OBSERVABLE — Limitation AD)")

    # -------------------------------------------------------------------------------------------
    # I54 — the deliverable clock (Drift fix 2). ADOPTION-armed on fsm-state.progress_clock.
    # It WARNS IN FLIGHT and BLOCKS ONLY AT SIGN-OFF, and it adds NO fourth human gate: no
    # REQUIRED_GATES flag, no attestation boolean, no question asked, and no guard on LT7.
    # -------------------------------------------------------------------------------------------
    _n14_clock = fsm.get("progress_clock") if isinstance(fsm, dict) else None
    _n14_deliv_adopted_early = any(isinstance(_gu, dict) and _gu.get("deliverable")
                                   for _gu in _n14_units_by_id.values())
    if (isinstance(_n14_clock, dict) or _n14_deliv_adopted_early) and isinstance(graph_doc, dict) \
            and not (graph_doc.get("waves") or []):
        rep.fail(f"{LABEL_STEM['i54_clock']} (order source)",
                 "this run adopts the deliverable clock and/or units[].deliverable, both of which are "
                 f"counted under a STIPULATED order ({_N14_ORDER_RULE}), but graph.json carries no "
                 "waves[]. Without it the order degrades to alphabetical unit id — which has no "
                 "relation to execution order — while every message still names the wave rule. The "
                 "order source is not optional for a run that adopts the mechanisms it orders")
    if isinstance(_n14_clock, dict):
        _n14_c_stem = LABEL_STEM["i54_clock"]
        _n14_c_bad = False
        # I54-1 (classification) — a counter over a PARTIALLY labelled population is worse than no
        # counter, because it reads low.
        _n14_unclassified = [_u for _u in _n14_order
                             if _n14_units_by_id[_u].get("deliverable") not in ("ships", "informs")]
        if _n14_unclassified:
            rep.fail(f"{_n14_c_stem} (I54-1 classification)",
                     f"progress_clock is adopted but {len(_n14_unclassified)} graph unit(s) carry no "
                     f"`deliverable` value: {_n14_unclassified[:12]}"
                     f"{' …' if len(_n14_unclassified) > 12 else ''}")
            _n14_c_bad = True
        # I54-2 (recomputation) — THE arm that makes the number evidence rather than narration.
        _n14_count, _n14_last_ship = 0, None
        _n14_crossings = []
        _n14_thr = _as_int(_n14_clock.get("surface_threshold"))
        if _n14_thr is None or _n14_thr < 1:
            _n14_thr = 3
        for _u in _n14_order:
            _vd = _n14_verdict(_u)
            if _vd not in ("PASS", "FAIL"):
                continue                                   # not yet adjudicated to a terminal verdict
            if _n14_units_by_id[_u].get("deliverable") == "ships" and _vd == "PASS":
                _n14_count, _n14_last_ship = 0, _u
                continue
            _n14_count += 1
            if _n14_count == _n14_thr:
                _n14_crossings.append(_u)
        _n14_written = _as_int(_n14_clock.get("units_since_ship"))
        if _n14_written != _n14_count:
            rep.fail(f"{_n14_c_stem} (I54-2 recomputation)",
                     f"fsm-state.progress_clock.units_since_ship is {_n14_clock.get('units_since_ship')!r} "
                     f"but the recomputation from graph.json + units/*/verify.json gives "
                     f"{_n14_count}. Order rule used: {_N14_ORDER_RULE}. Within a wave that is a "
                     "canonical RECONSTRUCTION, not real time — so read a disagreement here as "
                     "arithmetic first and reconstruction second")
            _n14_c_bad = True
        _n14_wls = _n14_clock.get("last_ship_unit")
        if (_n14_wls or None) != _n14_last_ship:
            rep.fail(f"{_n14_c_stem} (I54-2 recomputation)",
                     f"progress_clock.last_ship_unit is {_n14_wls!r} but the recomputation gives "
                     f"{_n14_last_ship!r} (order rule: {_N14_ORDER_RULE})")
            _n14_c_bad = True
        # I54-3 (disclosure) — fires ONLY at P8/DONE, exactly like I23 DoD closure. A run may not
        # reach DONE claiming it crossed its own threshold in silence: that is the incident verbatim.
        _n14_sa = _n14_clock.get("surfaced_at")
        _n14_sa = _n14_sa if isinstance(_n14_sa, list) else []
        # A record only COVERS a crossing if it discloses a count that had actually been reached.
        # A pure cardinality comparison accepted a record reading {units_since_ship: 0, phase:
        # P2_CLARIFICATION} — a disclosure of ZERO units since ship, in a phase before any unit ran —
        # as covering a crossing at 3 in P8. Counting records is not matching them.
        _n14_cover = [_r for _r in _n14_sa
                      if isinstance(_r, dict) and (_as_int(_r.get("units_since_ship")) or 0) >= _n14_thr]
        if _n14_clock.get("enabled") is False and _n14_crossings:
            # Disabling must be LOUD, exactly as I56-2 requires of the starvation cap. Silence here
            # let one boolean turn a FAIL into a clean PASS with no greppable trace at all.
            print(f"  NOTE  {LABEL_STEM['i54_clock']}: progress_clock.enabled=false, so the "
                  f"disclosure arm is OFF — the clock still crossed its threshold of {_n14_thr} at "
                  f"unit(s) {_n14_crossings}. Switching a gate off must not erase the evidence it "
                  "would have produced.")
        elif _n14_thr > max(len(_n14_order), 1) and _n14_count:
            print(f"  NOTE  {LABEL_STEM['i54_clock']}: surface_threshold={_n14_thr} exceeds the run's "
                  f"{len(_n14_order)} unit(s), so the clock CANNOT surface whatever happens — "
                  f"units_since_ship reached {_n14_count}. A threshold out of reach is a disable.")
        elif phase in ("P8_SYNTHESIS", "DONE") and _n14_clock.get("enabled") is not False:
            if len(_n14_crossings) > len(_n14_cover):
                rep.fail(f"{_n14_c_stem} (I54-3 disclosure)",
                         f"the clock crossed its threshold of {_n14_thr} at unit(s) "
                         f"{_n14_crossings} but surfaced_at[] holds only {len(_n14_cover)} record(s) "
                         f"disclosing a count of {_n14_thr} or more (of {len(_n14_sa)} present). The "
                         "human need not ACT on the warning; the run may not pretend the warning "
                         "never happened")
                _n14_c_bad = True
        if not _n14_c_bad:
            _n14_arm_ran = (phase in ("P8_SYNTHESIS", "DONE")
                            and _n14_clock.get("enabled") is not False)
            rep.ok(f"{_n14_c_stem} (units_since_ship={_n14_count} recomputed, last_ship="
                   f"{_n14_last_ship!r}, {len(_n14_crossings)} crossing(s), "
                   + (f"{len(_n14_cover)} covered by a matching surfaced_at record"
                      if _n14_arm_ran else "disclosure arm NOT evaluated at this phase/enabled state")
                   + ")")

    # -------------------------------------------------------------------------------------------
    # I56 — requirement-starvation disclosure (Drift fix 4: a cap on consecutive non-shipping units
    # per requirement). This section DEFINES NO FIELD: it consumes graph.json units[].deliverable
    # READ-ONLY and keeps NO counter, because with a planner-written label a persisted counter is a
    # second copy of a derivable fact and a second copy is a divergence waiting to happen.
    # ENFORCED as an AFTER-THE-FACT disclosure, and PROSE-ONLY at the instant it should fire: a
    # dossier BACKFILLED at P8, after every token is spent, satisfies I56 exactly, and nothing in
    # the run directory distinguishes the two. That limit is stated, not blurred.
    # -------------------------------------------------------------------------------------------
    _n14_deliv_adopted = any(_gu.get("deliverable") for _gu in _n14_units_by_id.values())
    if _n14_deliv_adopted:
        _n14_s_stem = LABEL_STEM["i56_starvation"]
        _n14_cap_n = _as_int(gates.get("starvation_cap_n"))
        if _n14_cap_n is None or _n14_cap_n < 1:
            _n14_cap_n = 3
        _n14_cap_on = gates.get("starvation_cap_enabled") is not False
        # run(d): per DoD item, the trailing streak of adjudicated non-"ships" units citing it.
        _n14_runs = {}
        for _u in _n14_order:
            _vd = _n14_verdict(_u)
            if _vd not in ("PASS", "FAIL"):
                continue
            _gu = _n14_units_by_id[_u]
            # A UNIT THAT FAILED VERIFICATION SHIPPED NOTHING, so it may not reset the streak. The
            # conjunct is I54-2's, verbatim; without it a `deliverable: "ships"` unit whose own
            # verification FAILED zeroed the starvation count for every DoD item it cites — measured,
            # one field flip turned a 3-unit starvation FAIL into a clean rc-0 PASS on a run that
            # simultaneously reported `I9 verification present (units/U02: verdict=FAIL)`. The design
            # discloses that the LABEL is gameable at plan time; it did not disclose that a FAILED
            # ship resets, and that is a different and worse hole.
            _ships = _gu.get("deliverable") == "ships" and _vd == "PASS"
            # DEDUP the citations: dod_refs carries no uniqueItems, and counting per CITATION rather
            # than per UNIT let a schema-valid graph inflate its own streak — measured, three units
            # produced "6 consecutive non-shipping units" naming U02 and U03 twice each, a message
            # that refutes itself.
            for _d in dict.fromkeys(_x for _x in (_gu.get("dod_refs") or []) if isinstance(_x, str)):
                _cur = _n14_runs.setdefault(_d, [0, []])
                if _ships:
                    _n14_runs[_d] = [0, []]        # a shipping unit resets ALL k items it cites
                else:
                    _cur[0] += 1
                    _cur[1].append(_u)
        # The two legal sinks, and only those two. A file called `starvation.md` would be neither
        # schema-validated nor recognised — validate_run.py maps schemas for exactly brief/debrief/
        # verify/disagreement — which is why the fourth `origin` literal exists.
        _n14_disclosed = []
        for _uid in sorted(unit_subdirs):
            _dis = unit_docs.get(_uid, {}).get("disagreement")
            if isinstance(_dis, dict) and _dis.get("origin") == "requirement-starvation":
                _n14_disclosed.append(" ".join(str(_dis.get(_k) or "") for _k in
                                               ("subject", "question", "why_material", "recommendation")))
        # The machine sink is admissible only where I51's arms are ARMED to police that file.
        # Otherwise I56 becomes an unversioned CONSUMER of version-gated-policed evidence: measured,
        # a run stamped 1.13.0 discharged a real starvation with a record whose `critical: false`
        # was a lie under clause 1, and nothing checked it.
        _skew_record("I56-MACHINE-SINK", bool(_n14_md_recs), _N14_SHIP, _n14_ver)
        for _r in (_n14_md_recs if _i27_semver_ge(_n14_ver, _N14_SHIP) else []):
            if isinstance(_r, dict) and _r.get("gate") == "disagreement":
                _n14_disclosed.append(" ".join([str(_r.get("question") or ""),
                                                str(_r.get("decision") or "")]
                                               + [str(_o) for _o in (_r.get("options") or [])]))
        _n14_s_bad = False
        _n14_breached = sorted(_d for _d, _v in _n14_runs.items() if _v[0] >= _n14_cap_n)
        for _d in _n14_breached:
            _streak = _n14_runs[_d][1][-_n14_cap_n:]
            if not _n14_cap_on:
                # I56-2 — switching a gate off must NOT erase the evidence it would have produced.
                print(f"  NOTE  {LABEL_STEM['note_i56']}: cap DISABLED "
                      f"(gates.starvation_cap_enabled=false) — DoD item {_d!r} reached "
                      f"run(d)={_n14_runs[_d][0]} against N={_n14_cap_n} on units {_streak}")
                continue
            # TOKEN-BOUNDARY match, not `in`. A bare substring test accepted any disclosure whose
            # text merely CONTAINED the item id: measured, a dossier about something else entirely
            # "disclosed" DoD-A because it mentioned the path `docs/DoD-Archive.md`, and disclosing
            # `DoD-AB` marked `DoD-A` disclosed too. A check that cannot go RED for any item whose id
            # is a substring of anything the run writes is not a check.
            _d_re = re.compile(r"(?<!\S)" + re.escape(_d) + r"(?!\S)")
            if any(_d_re.search(_txt) for _txt in _n14_disclosed):
                continue
            rep.fail(f"{_n14_s_stem} ({_d!r})",
                     f"{_n14_runs[_d][0]} consecutive non-shipping units against this DoD item "
                     f"(N={_n14_cap_n}, units {_streak}) and NO disclosure names it. The two legal "
                     "sinks are a units/<id>/disagreement.json with origin "
                     "'requirement-starvation', or a machine-decisions.json record on gate "
                     "'disagreement'. Order rule: " + _N14_ORDER_RULE)
            _n14_s_bad = True
        # A cap set beyond any reachable streak is a DISABLE wearing a number. Same doctrine as
        # I56-2: switching a gate off must not erase the evidence it would have produced.
        _n14_max_run = max([_v[0] for _v in _n14_runs.values()] or [0])
        if _n14_cap_on and _n14_cap_n > max(len(_n14_order), 1) and _n14_max_run:
            print(f"  NOTE  {LABEL_STEM['note_i56']}: gates.starvation_cap_n={_n14_cap_n} exceeds the "
                  f"run's {len(_n14_order)} unit(s), so the cap CANNOT fire whatever happens — the "
                  f"longest non-shipping streak reached {_n14_max_run}. Raising the number out of "
                  "reach is a disable, and a disable must stay auditable.")
        if not _n14_s_bad:
            rep.ok(f"{_n14_s_stem} (N={_n14_cap_n}, enabled={_n14_cap_on}, "
                   f"{len(_n14_runs)} DoD item(s) tracked, {len(_n14_breached)} at or over the cap; "
                   "ENFORCED as disclosure, PROSE-ONLY as timeliness)")

    # -------------------------------------------------------------------------------------------
    # I58 — re-sequencing eligibility (Drift fix 6). ADOPTION-armed on a `resequence` record.
    # Termination is bought by FUEL alone: a resequence adds and retires nothing, so the shipped
    # `fuel_cost == max(1, added - retired)` already charges it 1 and the published global bound
    # holds VERBATIM with no new term. There is NO monotone measure over the wave assignment — a
    # unit may legally go 5 -> 3 -> 5 — which is why I58-3 forbids a vacuous record.
    # -------------------------------------------------------------------------------------------
    _n14_rs = [(_fn, _r) for _fn, _r in amendments
               if isinstance(_r, dict) and _r.get("kind") == "resequence"]
    if _n14_rs:
        _n14_r_stem = LABEL_STEM["i58_resequence"]
        _n14_r_bad = False
        _n14_amend_names = [_fn for _fn, _ in amendments]
        for _fn, _rec in _n14_rs:
            _lbl = f"{_n14_r_stem} (amendments/{_fn})"
            _payload = _rec.get("resequenced") or []
            _snap = _rec.get("wave_snapshot") if isinstance(_rec.get("wave_snapshot"), dict) else None
            # I58-3 non-vacuity
            if not _payload:
                rep.fail(_lbl, "resequenced[] is empty — I58-3. A record that changes nothing is a "
                               "FAIL, not a free re-run: termination here is bought by fuel alone")
                _n14_r_bad = True
            for _e in _payload:
                if isinstance(_e, dict) and _as_int(_e.get("wave_from")) == _as_int(_e.get("wave_to")):
                    rep.fail(_lbl, f"resequenced entry for {_e.get('unit_id')!r} has "
                                   f"wave_to == wave_from ({_e.get('wave_to')!r}) — I58-3 vacuity")
                    _n14_r_bad = True
            # I58-1 eligibility — a FAIL-CLOSED CONJUNCTION, deliberately stronger than the code's
            # frozen set (debrief-presence) and at least as strong as SKILL.md's prose freeze. A
            # predicate keyed on debrief-presence alone is not merely weaker; it is a TRAP: nothing
            # fails at the instant of the re-wave, and the moment the unit's debrief lands the I17
            # frozen-content anchor emits `wave X != brief Y`, whose ONLY repair is to undo the
            # re-sequencing the run just spent fuel on.
            _n14_status = {}
            for _u in (fsm.get("units") or []):
                if isinstance(_u, dict) and isinstance(_u.get("unit_id"), str):
                    _n14_status[_u["unit_id"]] = _u.get("status")
            for _e in _payload:
                if not isinstance(_e, dict):
                    continue
                _u = _e.get("unit_id")
                _st = _n14_status.get(_u)
                if _st != "pending":
                    rep.fail(_lbl, f"unit {_u!r} has fsm-state status {_st!r}, not 'pending' — "
                                   "I58-1 eligibility. Only a pending, un-briefed unit may be "
                                   "re-waved")
                    _n14_r_bad = True
                _udir = os.path.join(rd, "units", str(_u))
                _held = []
                if os.path.isdir(_udir):
                    try:
                        _held = sorted(_f for _f in os.listdir(_udir)
                                       if _f.split(".")[0] in UNIT_PRIMARIES)
                    except Exception:
                        _held = []
                if _held:
                    rep.fail(_lbl, f"unit {_u!r} holds {_held} — I58-1 eligibility. Re-waving a "
                                   "unit that already has a brief plants a future I17 "
                                   "frozen-content FAIL whose only repair undoes this amendment")
                    _n14_r_bad = True
                # I58-2 the target wave is legal: at or beyond the frontier, and above every dep.
                _wt = _as_int(_e.get("wave_to"))
                _fw = _as_int(_rec.get("frontier_wave"))
                if _fw is None:
                    # DEFENCE IN DEPTH, and unreachable TODAY: the schema makes frontier_wave
                    # required on kind:'resequence', so such a record is dropped before I58 runs.
                    # Kept deliberately — and labelled, rather than left to read as a live check —
                    # so a future schema relaxation cannot silently disarm the clause.
                    rep.fail(_lbl, "frontier_wave is absent or non-integral on a resequence record "
                                   "— I58-2, a FAIL and never a `continue`. Reusing the shipped "
                                   "frontier clause's guard verbatim would let a record DISARM the "
                                   "check by omitting the key (the L24 silent-skip shape)")
                    _n14_r_bad = True
                elif _wt is not None and _wt < _fw:
                    rep.fail(_lbl, f"unit {_u!r} moves to wave {_wt} below frontier_wave {_fw} — "
                                   "I58-2")
                    _n14_r_bad = True
                _deps = (_n14_units_by_id.get(_u, {}) or {}).get("deps") or []
                _dw = [_n14_wave_of[_d] for _d in _deps if _d in _n14_wave_of]
                if _dw and _wt is not None and _wt < 1 + max(_dw):
                    rep.fail(_lbl, f"unit {_u!r} moves to wave {_wt} but its dependencies sit at "
                                   f"{sorted(set(_dw))} — I58-2 requires wave_to >= 1 + max(dep wave)")
                    _n14_r_bad = True
            # I58-5 the record adds and retires nothing (schema-enforced too; kept so a schema
            # relaxation cannot silently disarm the fuel argument this rests on).
            for _k in ("units_added", "units_retired", "edges_added"):
                if _rec.get(_k):
                    rep.fail(_lbl, f"{_k} is non-empty on a resequence record — I58-5. The fuel "
                                   "charge max(1, added - retired) == 1 is only correct because a "
                                   "resequence moves nothing in or out of the graph")
                    _n14_r_bad = True
            # I58-6 trigger
            _o = _rec.get("origin") if isinstance(_rec.get("origin"), dict) else {}
            if _o.get("trigger") not in ("priority_change", "human_request"):
                rep.fail(_lbl, f"origin.trigger is {_o.get('trigger')!r} — I58-6 admits exactly "
                               "'priority_change' and 'human_request'. A unit's own debrief handoff "
                               "may NOT fire a resequence, or a run could re-order itself once per "
                               "unit")
                _n14_r_bad = True
            elif _o.get("trigger") == "priority_change" and _n14_blank(_o.get("source_ref")):
                rep.fail(_lbl, "origin.trigger == 'priority_change' with a blank origin.source_ref "
                               "— I58-6")
                _n14_r_bad = True
            # I58-4a the snapshot agrees with the record.
            if _snap is None:
                rep.fail(_lbl, "wave_snapshot is absent — I58-4a. Without it the interesting half "
                               "of this invariant is not decidable by ANY predicate over emitted "
                               "artifacts: a run directory holds exactly one graph.json, "
                               "baseline_units is an id set with no waves, and for the very "
                               "population the clause polices (a pending, un-briefed unit the "
                               "record does not list) the pre-amendment wave was recorded nowhere")
                _n14_r_bad = True
            else:
                # I58-4c COMPLETENESS. I58-4 quantifies over the snapshot's own keys, so without this
                # the record's AUTHOR chooses the domain of "the clause that catches a silent re-wave
                # of a unit the record does not name" — measured, simply OMITTING the silently-moved
                # unit from wave_snapshot took two otherwise-identical run dirs from FAIL to PASS. The
                # schema DESCRIBES the snapshot as every pre-amendment unit id, but
                # additionalProperties cannot enforce completeness and nothing else did. Absence is a
                # FAIL, never a skip — the same L24 shape I58-2 guards for frontier_wave.
                _snap_missing = sorted(_u for _u in _n14_units_by_id if _u not in _snap)
                if _snap_missing:
                    rep.fail(_lbl, f"wave_snapshot omits {_snap_missing} — I58-4c. The snapshot must "
                                   "cover every unit in the graph, or the record's author picks the "
                                   "domain of the clause meant to police it, and a silent re-wave "
                                   "escapes by simply not being listed")
                    _n14_r_bad = True
                for _e in _payload:
                    if not isinstance(_e, dict):
                        continue
                    _u = _e.get("unit_id")
                    if _as_int(_snap.get(_u)) != _as_int(_e.get("wave_from")):
                        rep.fail(_lbl, f"wave_snapshot[{_u!r}] is {_snap.get(_u)!r} but the record "
                                       f"claims wave_from {_e.get('wave_from')!r} — I58-4a")
                        _n14_r_bad = True
                # I58-4b, REWRITTEN. The comparison target for a resequence record is the NEXT
                # RESEQUENCE record's snapshot, or graph.json when this is the last one.
                #
                # The previous form keyed on the next AMENDMENT of any kind, and was a check that
                # could not go GREEN: `wave_snapshot` is schema-FORBIDDEN on every non-resequence
                # kind, so a resequence followed by an ordinary add_units was an UNREPAIRABLE FAIL —
                # the only route to green was schema-rejected and cascaded into seven further FAILs.
                # Its stated target was unreachable in the other direction too: `wave_snapshot` is
                # REQUIRED on kind:'resequence', so a resequence lacking one is dropped at the schema
                # layer and never reaches this arm at all. An arm that can only fire falsely is worse
                # than an absent one.
                _idx = _n14_amend_names.index(_fn)
                _next_rs = next(((_fn2, _r2) for _fn2, _r2 in amendments[_idx + 1:]
                                 if isinstance(_r2, dict) and _r2.get("kind") == "resequence"), None)
                if _next_rs is not None:
                    _fn2, _r2 = _next_rs
                    _s2 = _r2.get("wave_snapshot")
                    _target_map = _s2 if isinstance(_s2, dict) else None
                    _target_desc = f"the next resequence record amendments/{_fn2}"
                else:
                    _target_map, _target_desc = _n14_wave_of, "graph.json.waves[]"
                # I58-4 — the clause that catches a SILENT re-wave of a unit the record never named.
                if _target_map is not None:
                    _moved = {_e.get("unit_id"): _as_int(_e.get("wave_to"))
                              for _e in _payload if isinstance(_e, dict)}
                    for _u, _w0 in sorted(_snap.items()):
                        _expect = _moved.get(_u, _as_int(_w0))
                        _actual = _as_int(_target_map.get(_u))
                        if _actual is None:
                            continue          # retired/absent downstream: not this clause's business
                        if _actual != _expect:
                            rep.fail(_lbl, f"unit {_u!r} sits at wave {_actual} in {_target_desc} "
                                           f"but wave_snapshot + resequenced[] imply {_expect} — "
                                           "I58-4. This is the clause that catches a silent re-wave "
                                           "of a unit the record does not name")
                            _n14_r_bad = True
        if not _n14_r_bad:
            rep.ok(f"{_n14_r_stem} ({len(_n14_rs)} resequence record(s): eligible, non-vacuous, "
                   "snapshot-complete; wave MINIMALITY is deliberately NOT enforced)")

    # -------------------------------------------------------------------------------------------
    # Blast radius (1.15.0) — I60 write scope / file footprint, I61 no overlapping writes in a wave.
    # OFFLINE, POST-HOC predicates over emitted artifacts only: graph.json units[].deliverable and
    # units[].frame, units/<U>/brief.json frame + outputs[], units/<U>/footprint.json (+ its
    # footprint.json.sha256 sidecar in `shasum -a 256` form, `<hex>  footprint.json`) and
    # fsm-state.blast. Nothing here runs git or any other process, gates a transition, or guards LT7.
    # Footprint contract restated (written by scripts/footprint.py): {unit_id, iteration, mode,
    # base_ref, pre_snapshot_sha256, post_snapshot_sha256, changes[{path, status, from_path,
    # sha256_before, sha256_after}], unattributed[], capture_error, tool_version}; a failed capture
    # sets capture_error and changes [] (fail-closed). Every read is RAW (json.load + isinstance), so
    # a schema-invalid artifact still reaches its clause, and a wrong-typed key is a FAIL row naming
    # the key, never a traceback. Paths and patterns are matched by frame_match only.
    # Version gate: armed iff fsm-state.validator_version >= _BLAST_SHIP AND graph.json lists at least
    # one unit (structural: before Phase 4 there is nothing to scope; from then on every clause runs).
    # There is NO opt-out on an armed run: a missing blast record / footprint is a FAIL, never a reason
    # to skip a clause. Stamp and graph are read raw, so a schema-invalid fsm-state.blast or graph is
    # still judged. Archive-safe: an unstamped, malformed-stamped or < 1.15.0 run is never armed. The
    # N-I45 shadow arm BLAST-T1 is counted when the graph has a unit AND the run carries a blast
    # artifact (fsm-state.blast, a graph unit frame, or a units/<U>/footprint.json) that the stamp
    # leaves unjudged — so a pre-1.15.0 run that never adopted the mechanism is not reported as
    # suppressing it (a deliberate UNDER-count of N-I45's upper bound for such runs).
    _BLAST_SHIP = "1.15.0"

    def _blast_raw(path):
        try:
            return load_json(path), None
        except FileNotFoundError:
            return None, "absent"
        except Exception as _e:
            return None, f"unreadable ({type(_e).__name__}: {_e})"

    _blast_fsm, _ = _blast_raw(os.path.join(rd, "fsm-state.json"))
    _blast_ver = _blast_fsm.get("validator_version") if isinstance(_blast_fsm, dict) else None
    _blast_graph, _ = _blast_raw(os.path.join(rd, "graph.json"))
    _blast_units = {}
    _blast_wave_of = {}
    if isinstance(_blast_graph, dict):
        _bg_units = _blast_graph.get("units")
        if isinstance(_bg_units, list):
            for _bu in _bg_units:
                if isinstance(_bu, dict) and isinstance(_bu.get("id"), str):
                    _blast_units[_bu["id"]] = _bu
        _bg_waves = _blast_graph.get("waves")
        if isinstance(_bg_waves, list):
            for _bw in _bg_waves:
                _bwn = _as_int(_bw.get("wave")) if isinstance(_bw, dict) else None
                _bwu = _bw.get("units") if isinstance(_bw, dict) else None
                if _bwn is None or not isinstance(_bwu, list):
                    continue
                for _u in _bwu:
                    if isinstance(_u, str):
                        _blast_wave_of[_u] = _bwn
    _blast_fp_present = any(os.path.isfile(os.path.join(units_dir, _u, "footprint.json"))
                            for _u in sorted(unit_subdirs))
    _blast_structure = (isinstance(_blast_fsm, dict) and "blast" in _blast_fsm) or _blast_fp_present \
        or any(isinstance(_bu, dict) and "frame" in _bu for _bu in _blast_units.values())
    _blast_armed = _i27_semver_ge(_blast_ver, _BLAST_SHIP) and bool(_blast_units)
    _skew_record("BLAST-T1", bool(_blast_units) and _blast_structure, _BLAST_SHIP, _blast_ver)

    if _blast_armed:
        _i60 = LABEL_STEM["i60_write_scope"]
        _i61 = LABEL_STEM["i61_wave_disjoint"]
        _blast_bad = {"I60": False, "I61": False}

        def _blast_fail(stem, clause, locus, detail):
            _blast_bad["I60" if stem == _i60 else "I61"] = True
            rep.fail(f"{stem} ({clause} {locus})", detail)

        def _blast_list(obj, key, stem, clause, locus):
            """obj[key] as a list of str; a present-but-wrong-typed value is a FAIL row naming the key."""
            if not isinstance(obj, dict) or key not in obj:
                return []
            _v = obj[key]
            if not isinstance(_v, list) or not all(isinstance(_x, str) for _x in _v):
                _blast_fail(stem, clause, locus, f"`{key}` must be a list of strings, got {_v!r:.120}")
                return []
            return _v

        # I60-6 — the run's blast baseline (fsm-state.blast) is present and well formed.
        _bl = _blast_fsm.get("blast") if isinstance(_blast_fsm, dict) else None
        _bl_mode = _bl.get("mode") if isinstance(_bl, dict) else None
        _bl_ws = _bl.get("workspace_root") if isinstance(_bl, dict) else None
        _n_ships = sum(1 for _bu in _blast_units.values() if _bu.get("deliverable") == "ships")
        if _bl is None:
            _blast_fail(_i60, "I60-6", "fsm-state.blast",
                        "absent on a run stamped >= 1.15.0 — init_run.sh records the baseline at scaffold; "
                        "a missing blast record is a FAIL, never an opt-out")
        elif not isinstance(_bl, dict):
            _blast_fail(_i60, "I60-6", "fsm-state.blast", f"must be an object, got {type(_bl).__name__}")
        elif _bl_mode not in ("git", "snapshot", "none"):
            _blast_fail(_i60, "I60-6", "fsm-state.blast.mode", f"must be git|snapshot|none, got {_bl_mode!r}")
        elif _bl_mode == "none" and _n_ships:
            _blast_fail(_i60, "I60-6", "fsm-state.blast.mode",
                        f"mode none (no capture mechanism) with {_n_ships} ships unit(s) — a run that changes "
                        "the repository must capture what it changed")
        elif _bl_mode == "git" and not (isinstance(_bl.get("base_sha"), str)
                                        and re.fullmatch(r"[0-9a-f]{40}", _bl["base_sha"])):
            _blast_fail(_i60, "I60-6", "fsm-state.blast.base_sha",
                        f"git mode requires a 40-hex lowercase base_sha, got {_bl.get('base_sha')!r:.60}")

        # Per-unit declared frame (graph is authoritative), validated once.
        _blast_mod = {}
        _blast_imm = {}
        for _u, _bu in _blast_units.items():
            _loc = f"graph.json units[{_u}]"
            # I60-1 — every graph unit says whether it ships.
            if _bu.get("deliverable") not in ("ships", "informs"):
                _blast_fail(_i60, "I60-1", _loc, f"deliverable must be ships|informs, got {_bu.get('deliverable')!r}")
            _fr = _bu.get("frame")
            if _fr is not None and not isinstance(_fr, dict):
                _blast_fail(_i60, "I60-2", _loc, f"`frame` must be an object, got {type(_fr).__name__}")
                _fr = None
            _blast_mod[_u] = _blast_list(_fr, "modifies", _i60, "I60-2", _loc)
            _blast_imm[_u] = _blast_list(_fr, "immutable", _i60, "I60-2", _loc)
            # I60-2 — a ships unit declares a valid, non-empty write scope.
            if _bu.get("deliverable") == "ships":
                if not _blast_mod[_u]:
                    _blast_fail(_i60, "I60-2", _loc, "a ships unit needs a non-empty frame.modifies")
                for _pat in _blast_mod[_u] + _blast_imm[_u]:
                    if not frame_match.is_valid_pattern(_pat):
                        _blast_fail(_i60, "I60-2", _loc, f"invalid frame pattern {_pat!r:.120}")
            # I60-2 — brief.json mirrors the graph frame; a ships unit's repo outputs lie inside it.
            _bp = os.path.join(units_dir, _u, "brief.json")
            if not os.path.isfile(_bp):
                continue
            _bb, _berr = _blast_raw(_bp)
            if not isinstance(_bb, dict):
                _blast_fail(_i60, "I60-2", f"units/{_u}/brief.json", f"not a JSON object ({_berr or 'wrong type'})")
                continue
            if _frame_canon(_bu.get("frame")) != _frame_canon(_bb.get("frame")):
                _blast_fail(_i60, "I60-2", f"units/{_u}/brief.json",
                            "brief.frame differs from graph.json frame (each list compared as a set)")
            if _bu.get("deliverable") == "ships":
                for _o in _blast_list(_bb, "outputs", _i60, "I60-2", f"units/{_u}/brief.json"):
                    _op = _o.strip()
                    if os.path.isabs(_op):
                        _rp = os.path.realpath(_op)
                        if _rp == os.path.realpath(rd) or _rp.startswith(os.path.realpath(rd) + os.sep):
                            continue                       # a run-dir artifact, not a repo path
                        if isinstance(_bl_ws, str) and _rp.startswith(os.path.realpath(_bl_ws) + os.sep):
                            _op = os.path.relpath(_rp, os.path.realpath(_bl_ws))
                    elif "/" not in _op or _op.startswith(("units/", ".wip/")):
                        continue                           # run-dir artifact (DECISIONS.md, units/<U>/...)
                    if not frame_match.match_any_pattern(_op, _blast_mod[_u]):
                        _blast_fail(_i60, "I60-2", f"units/{_u}/brief.json",
                                    f"outputs[] repo path {_o!r:.120} matches no frame.modifies pattern")

        # I60-3..5 per executed unit (has a debrief); footprints feed I61.
        _blast_fp = {}
        for _u in sorted(unit_dirs_with_debrief):
            _loc = f"units/{_u}"
            _fpp = os.path.join(units_dir, _u, "footprint.json")
            if not os.path.isfile(_fpp):
                _blast_fail(_i60, "I60-3", _loc, "executed unit has no footprint.json (footprint.py capture)")
                continue
            _fp, _fperr = _blast_raw(_fpp)
            if not isinstance(_fp, dict):
                _blast_fail(_i60, "I60-3", _loc, f"footprint.json is not a JSON object ({_fperr or 'wrong type'})")
                continue
            _ud = unit_docs.get(_u)
            if not (isinstance(_ud, dict) and isinstance(_ud.get("footprint"), dict)):
                _blast_fail(_i60, "I60-3", _loc, "footprint.json is not schema-valid against footprint.schema.json")
            if _fp.get("unit_id") != _u:
                _blast_fail(_i60, "I60-3", _loc, f"footprint unit_id {_fp.get('unit_id')!r} != directory {_u!r}")
            try:
                with open(_fpp, "rb") as _fh:
                    _fpsha = hashlib.sha256(_fh.read()).hexdigest()
                with open(_fpp + ".sha256", "r", encoding="utf-8") as _fh:
                    _side = _fh.read().split()
                _side0 = _side[0].lower() if _side else None
            except Exception as _e:
                _fpsha, _side0 = None, f"<unreadable sidecar: {type(_e).__name__}>"
            if _fpsha is None or _side0 != _fpsha:
                _blast_fail(_i60, "I60-3", _loc, f"footprint.json.sha256 {_side0!r:.80} != sha256(footprint.json) {_fpsha!r}")
            _db, _ = _blast_raw(os.path.join(units_dir, _u, "debrief.json"))
            _dit = _as_int(_db.get("iteration")) if isinstance(_db, dict) else None
            _fit = _as_int(_fp.get("iteration"))
            if _fit is None or _dit is None or _fit != _dit:
                _blast_fail(_i60, "I60-3", _loc,
                            f"footprint iteration {_fp.get('iteration')!r} != debrief.json iteration "
                            f"{_db.get('iteration') if isinstance(_db, dict) else None!r} (a retry re-captures)")
            if _fp.get("capture_error") is not None:
                _blast_fail(_i60, "I60-3", _loc, f"capture_error set: {_fp.get('capture_error')!r:.160}")
            _chg = _fp.get("changes")
            if not isinstance(_chg, list):
                _blast_fail(_i60, "I60-3", _loc, f"footprint `changes` must be a list, got {type(_chg).__name__}")
                _chg = []
            _paths = set()
            for _c in _chg:
                if not isinstance(_c, dict) or not isinstance(_c.get("path"), str):
                    _blast_fail(_i60, "I60-3", _loc, f"malformed changes[] entry {_c!r:.120}")
                    continue
                _cps = [_c["path"]] + ([_c["from_path"]] if isinstance(_c.get("from_path"), str) else [])
                for _cp in _cps:
                    _paths.add(_cp)
                    # I60-4 — every write lies inside modifies and outside immutable.
                    if not frame_match.match_any_pattern(_cp, _blast_mod.get(_u, [])):
                        _blast_fail(_i60, "I60-4", _loc, f"changed path {_cp!r:.120} matches no frame.modifies pattern")
                    if frame_match.match_any_pattern(_cp, _blast_imm.get(_u, [])):
                        _blast_fail(_i60, "I60-4", _loc, f"changed path {_cp!r:.120} matches a frame.immutable pattern")
            # I60-5 — an informs unit changed nothing outside the run directory.
            if _chg and _blast_units.get(_u, {}).get("deliverable") == "informs":
                _blast_fail(_i60, "I60-5", _loc, f"informs unit has {len(_chg)} footprint change(s); it must be empty")
            # I61-2 — every captured change is claimed by some unit's frame.
            _una = _fp.get("unattributed")
            if not isinstance(_una, list):
                _blast_fail(_i61, "I61-2", _loc, f"footprint `unattributed` must be a list, got {type(_una).__name__}")
            elif _una:
                _blast_fail(_i61, "I61-2", _loc, f"{len(_una)} unattributed changed path(s) no unit's frame claims: "
                                                 f"{_una[:5]!r:.200}")
            _blast_fp[_u] = _paths

        # I61-1 (FAIL) / I61-3 (NOTE) — pairwise within each graph wave.
        _by_wave = {}
        for _u, _wn in sorted(_blast_wave_of.items()):
            _by_wave.setdefault(_wn, []).append(_u)
        for _wn in sorted(_by_wave):
            _wu = _by_wave[_wn]
            for _i, _a in enumerate(_wu):
                for _b in _wu[_i + 1:]:
                    _both = sorted(_blast_fp.get(_a, set()) & _blast_fp.get(_b, set()))
                    if _both:
                        _blast_fail(_i61, "I61-1", f"wave {_wn} {_a}/{_b}",
                                    f"same-wave footprints overlap on {len(_both)} path(s): {_both[:5]!r:.200}")
                    _fov = frame_match.set_overlaps(_blast_mod.get(_a, []), _blast_mod.get(_b, []))
                    if _fov:
                        print(f"  NOTE  {LABEL_STEM['note_i61']}: wave {_wn} {_a}/{_b} declare overlapping "
                              f"frame.modifies {_fov[:3]!r:.200} — the two units can write the same path")
        if not _blast_bad["I60"]:
            rep.ok(f"{_i60} ({len(_blast_units)} unit(s), {len(_blast_fp)} footprint(s): scoped and well formed)")
        if not _blast_bad["I61"]:
            rep.ok(f"{_i61} ({len(_by_wave)} wave(s): same-wave footprints disjoint, nothing unattributed)")

    # I62 — every impact obligation settled (1.15.0 blast radius). OFFLINE and POST-HOC like I60/I61:
    # it reads units/<U>/impact.json (+ its `<hex>  impact.json` sidecar), units/<U>/footprint.json,
    # units/<U>/debrief.json and the aggregated, verdict-bearing units/<U>/verify.json (blast_audit),
    # raw (json.load + isinstance), so a schema-invalid record still reaches its clause and a
    # wrong-typed key is a FAIL row naming the key, never a traceback. It gates no transition and
    # guards no back-edge; it reuses I60's armed flag (no further version gate).
    # Impact contract restated (written by scripts/impact_scan.py): {unit_id, iteration,
    # footprint_sha256, symbols[], obligations[{id, kind: reference|coupling, symbol_ids,
    # rule_id, referencing_paths, hit_count, sample_hits}], truncated_hits, caps, scanner}. Symbol
    # kinds are an OPEN set and a scan failure is itself an obligation (id `error:<where>`), so
    # obligations are settled by id alone — no kind is ever a reason to skip one.
    # Audit contract restated (verify.blast_audit): {impact_sha256, rows[{obligation_id,
    # disposition: exercised|unaffected|owned_by|broken, check, exit_code, red_input, owner_unit,
    # rationale}]}. No opt-out: on an armed run a missing impact.json or blast_audit is a FAIL.
    # The audit is judged once the unit has a verify.json that is current (verify.iteration ==
    # debrief.iteration) — mid-loop staleness is legal and owned by I43/I44/I46 — and, from
    # P8_SYNTHESIS on, whatever its iteration.
    # I64-8 blast_accepted — the ONE opt-out on an armed run: a NAMED, PER-ITEM override, the I44
    # accepted_incomplete shape. fsm-state.blast_accepted = {items: [string], rationale: string,
    # decision_ref: string naming DECISIONS.md}. ITEM GRAMMAR: "<clause>:<subject>" with <clause> one of
    # I62-4, I64-3 .. I64-7 and <subject> the exact key a FAIL row of that clause prints in its
    # "[accept via blast_accepted.items: ...]" suffix (copy it). Matching is exact string equality — no
    # glob, prefix or clause-wide form — so an item downgrades only FAIL rows carrying exactly its key.
    # ONE KEY, ONE SUBJECT: every acceptable key names exactly one subject, never a category —
    #   I62-4  "<impact locus> <obligation id>"  one owned_by obligation of one unit
    #   I64-3  "<path>"                          one changed path no frame owns
    #   I64-4  "<path> <unit>"                   one shared path for one writer
    #   I64-5  "<regression id>"                 one declared regression command
    #   I64-6  "<kind> <detail>"                 one weakened-test row (integration test_weakening[]
    #                                            kind + detail; detail names the surface and the file or row)
    #   I64-7  "<census id>"                     one must_not_increase census
    # A row that is not about such a subject prints no key and is NEVER acceptable: I60, I61, I63,
    # I62-1..3, I64-1, I64-2 (identical start/end trees void the whole comparison) and I64-8; and every
    # RECORD-STRUCTURE row — a wrong-typed or malformed entry of integration.json, and any finding about
    # the blast config itself (absent, unreadable, wrong-typed, regression_commands empty without a
    # reason). Those are repaired, not accepted: accepting one would silence the checks the record feeds,
    # and the override never relies on a schema FAIL elsewhere to stay safe. If one key would downgrade
    # two FAIL rows whose details differ, the second stays a FAIL with an "ambiguous" NOTE. A named
    # finding becomes an exit-neutral, always-printed "N-I64 blast accepted" NOTE (downgraded and
    # greppable, never suppressed); unnamed findings stay FAILs. A string item that matches no finding
    # once I64 is judged — including a blanket or out-of-grammar string such as "*", "all", "I64" or
    # "I64-3" — downgrades nothing and gets the over-broad advisory NOTE. MALFORMED — I44's six conditions
    # adapted plus one, in order, the first unmet one named: (1) not an object; (2) items is not a list
    # (an empty list is well-formed and accepts nothing); (3) rationale is not a non-blank string; (4)
    # decision_ref is not a non-blank string; (5) decision_ref does not name DECISIONS.md; (6)
    # <run>/DECISIONS.md is missing; (7) an item is not a string (REPORTED here, not silently ignored as
    # I44 does) — gives exactly ONE FAIL on every armed run carrying the key, and downgrades NOTHING.
    # Coupling semantics (I62-4): a coupling obligation records the TRIGGER file, not the file that
    # satisfies the rule, and is settled by EXERCISING its required command; owned_by on a coupling
    # means a later unit whose frame covers the trigger runs that command. An owned_by no single
    # unit's frame can satisfy (e.g. a prose reference spanning files) stays an I62-4 FAIL until a
    # named item accepts it here — loud, never silent.
    _BA_CLAUSES = ("I62-4", "I64-3", "I64-4", "I64-5", "I64-6", "I64-7")
    _ba_items, _ba_hit, _ba_unmet, _ba_ref = set(), {}, None, ""
    if _blast_armed and isinstance(_blast_fsm, dict) and "blast_accepted" in _blast_fsm:
        _ba = _blast_fsm["blast_accepted"]
        if not isinstance(_ba, dict):
            _ba_unmet = f"(1) blast_accepted is not an object (got {type(_ba).__name__})"
        else:
            _ba_l, _ba_r, _ba_d = _ba.get("items"), _ba.get("rationale"), _ba.get("decision_ref")
            if not isinstance(_ba_l, list):
                _ba_unmet = f"(2) items is not a list (got {type(_ba_l).__name__})"
            elif not (isinstance(_ba_r, str) and _ba_r.strip()):
                _ba_unmet = "(3) rationale is not a non-blank string"
            elif not (isinstance(_ba_d, str) and _ba_d.strip()):
                _ba_unmet = "(4) decision_ref is not a non-blank string"
            elif "DECISIONS.md" not in _ba_d:
                _ba_unmet = f"(5) decision_ref {_ba_d!r:.80} does not name DECISIONS.md"
            elif not os.path.isfile(os.path.join(rd, "DECISIONS.md")):
                _ba_unmet = "(6) DECISIONS.md is missing from the run directory"
            else:
                _ba_off = [_x for _x in _ba_l if not isinstance(_x, str)]
                if _ba_off:
                    _ba_unmet = (f"(7) {len(_ba_off)} item(s) not a string (grammar '<clause>:<subject>', clause "
                                 f"one of {', '.join(_BA_CLAUSES)}), first {_ba_off[0]!r:.80}")
                else:
                    _ba_items, _ba_ref = set(_ba_l), _ba_d
        if _ba_unmet:
            rep.fail(f"{LABEL_STEM['i64_integration']} (I64-8 blast_accepted malformed: {_ba_unmet})",
                     "the override fails closed and downgrades NOTHING; every named finding stays a FAIL")

    def _ba_take(clause, item, detail):
        """(accepted, hint): accepted iff a well-formed blast_accepted names this exact finding — then an
        exit-neutral N-I64 NOTE is printed in place of the FAIL; hint is the copyable item suffix. `item`
        None marks a row that is not about one subject (record structure): never acceptable, no hint."""
        if item is None or clause not in _BA_CLAUSES:
            return False, ""
        _key = f"{clause}:{item}"
        if _key in _ba_items:
            if _ba_hit.setdefault(_key, detail) == detail:
                print(f"  NOTE  {LABEL_STEM['note_i64']}: {json.dumps(_key)} downgraded from FAIL by "
                      f"fsm-state.blast_accepted ({_ba_ref}) — {detail}")
                return True, ""
            print(f"  NOTE  {LABEL_STEM['note_i64']}: {json.dumps(_key)} is ambiguous — it names more than one "
                  "different finding, so this one stays a FAIL (an item must name exactly one subject)")
            return False, ""
        return False, f" [accept via blast_accepted.items: {json.dumps(_key)}]"

    if _blast_armed:
        _i62 = LABEL_STEM["i62_impact"]
        _i62_bad = [False]
        _i62_late = phase in ("P8_SYNTHESIS", "DONE")

        def _i62_fail(clause, locus, detail):
            _i62_bad[0] = True
            _ba_ok, _ba_hint = _ba_take(clause, locus, detail)  # only I62-4 (one obligation) is acceptable
            if not _ba_ok:
                rep.fail(f"{_i62} ({clause} {locus})", detail + _ba_hint)

        def _i62_sha(path):
            try:
                with open(path, "rb") as _fh:
                    return hashlib.sha256(_fh.read()).hexdigest()
            except Exception:
                return None

        def _i62_blank(v):
            return not (isinstance(v, str) and v.strip())

        def _i62_it(doc):
            return _as_int(doc.get("iteration")) if isinstance(doc, dict) else None

        def _i62_current_pass(uid):
            _odb, _ = _blast_raw(os.path.join(units_dir, uid, "debrief.json"))
            _ovf, _ = _blast_raw(os.path.join(units_dir, uid, "verify.json"))
            return (isinstance(_ovf, dict) and _ovf.get("verdict") == "PASS"
                    and _i62_it(_ovf) is not None and _i62_it(_ovf) == _i62_it(_odb))

        _i62_n = 0
        for _u in sorted(unit_dirs_with_debrief):
            _bu = _blast_units.get(_u)
            if not (isinstance(_bu, dict) and _bu.get("deliverable") == "ships"):
                continue
            _i62_n += 1
            _loc = f"units/{_u}"
            _udir = os.path.join(units_dir, _u)
            _db, _ = _blast_raw(os.path.join(_udir, "debrief.json"))
            _dit = _i62_it(_db)
            # I62-1 — the executed ships unit has a schema-valid impact.json bound to its footprint
            # (footprint_sha256 == sha256(footprint.json bytes)), its sidecar, and its current iteration.
            _ip = os.path.join(_udir, "impact.json")
            _isha = _i62_sha(_ip)
            _imp, _imperr = _blast_raw(_ip)
            _obl = None                           # {obligation id: obligation}; None = unknown
            if not os.path.isfile(_ip):
                _i62_fail("I62-1", _loc, "executed ships unit has no impact.json (impact_scan.py) — "
                                         "a missing impact record is a FAIL, never an opt-out")
            elif not isinstance(_imp, dict):
                _i62_fail("I62-1", _loc, f"impact.json is not a JSON object ({_imperr or 'wrong type'})")
            else:
                _ud = unit_docs.get(_u)
                if not (isinstance(_ud, dict) and isinstance(_ud.get("impact"), dict)):
                    _i62_fail("I62-1", _loc, "impact.json is not schema-valid against impact.schema.json")
                if _imp.get("unit_id") != _u:
                    _i62_fail("I62-1", _loc, f"impact unit_id {_imp.get('unit_id')!r:.60} != directory {_u!r}")
                try:
                    with open(_ip + ".sha256", "r", encoding="utf-8") as _fh:
                        _side = _fh.read().split()
                    _side0 = _side[0].lower() if _side else None
                except Exception as _e:
                    _side0 = f"<unreadable sidecar: {type(_e).__name__}>"
                if _isha is None or _side0 != _isha:
                    _i62_fail("I62-1", _loc, f"impact.json.sha256 {_side0!r:.80} != sha256(impact.json) {_isha!r}")
                _fsha = _i62_sha(os.path.join(_udir, "footprint.json"))
                if _fsha is None or _imp.get("footprint_sha256") != _fsha:
                    _i62_fail("I62-1", _loc, f"impact footprint_sha256 {_imp.get('footprint_sha256')!r:.80} != "
                                             f"sha256(footprint.json) {_fsha!r} (re-scan after every capture)")
                _iit = _i62_it(_imp)
                if _iit is None or _dit is None or _iit != _dit:
                    _i62_fail("I62-1", _loc, f"impact iteration {_imp.get('iteration')!r:.40} != debrief.json "
                                             f"iteration {_dit!r} (a retry re-scans)")
                _ol = _imp.get("obligations")
                if not isinstance(_ol, list):
                    _i62_fail("I62-1", _loc, f"impact `obligations` must be a list, got {type(_ol).__name__}")
                else:
                    _obl = {}
                    for _o in _ol:
                        if not (isinstance(_o, dict) and isinstance(_o.get("id"), str) and _o["id"]):
                            _i62_fail("I62-1", _loc, f"malformed obligations[] entry {_o!r:.120}")
                            _obl = None
                            break
                        _obl[_o["id"]] = _o
            # I62-2 — the aggregated verdict-bearing verify.json carries a blast_audit bound to this
            # impact.json and settling every obligation id exactly once.
            _vf, _vferr = _blast_raw(os.path.join(_udir, "verify.json"))
            if _vf is None and _vferr == "absent":
                continue                          # not verified yet: nothing adjudicated to audit
            if not isinstance(_vf, dict):
                _i62_fail("I62-2", _loc, f"verify.json is not a JSON object ({_vferr or 'wrong type'})")
                continue
            if not (_i62_late or (_i62_it(_vf) is not None and _i62_it(_vf) == _dit)):
                continue                          # a stale verdict mid-loop: re-verification pending
            _ba = _vf.get("blast_audit")
            if not isinstance(_ba, dict):
                _i62_fail("I62-2", f"{_loc} blast_audit",
                          "absent from verify.json — a missing audit is a FAIL, never an opt-out" if _ba is None
                          else f"must be an object, got {type(_ba).__name__}")
                continue
            if _isha is not None and _ba.get("impact_sha256") != _isha:
                _i62_fail("I62-2", f"{_loc} blast_audit", f"impact_sha256 {_ba.get('impact_sha256')!r:.80} != "
                                                          f"sha256(impact.json) {_isha!r} (the audit judged another scan)")
            _rows = _ba.get("rows")
            if not isinstance(_rows, list):
                _i62_fail("I62-2", f"{_loc} blast_audit", f"`rows` must be a list, got {type(_rows).__name__}")
                continue
            _seen = {}
            _verdict = _vf.get("verdict")
            for _r in _rows:
                _oid = _r.get("obligation_id") if isinstance(_r, dict) else None
                if not (isinstance(_oid, str) and _oid):
                    _i62_fail("I62-2", f"{_loc} blast_audit", f"malformed rows[] entry {_r!r:.120} (needs obligation_id)")
                    continue
                _seen[_oid] = _seen.get(_oid, 0) + 1
                _rl = f"{_loc} {_oid}"
                _disp = _r.get("disposition")
                _ob = _obl.get(_oid) if isinstance(_obl, dict) else None
                if _disp == "exercised":
                    # I62-3 — a check that ran green, plus the input that would turn it red.
                    if _i62_blank(_r.get("check")):
                        _i62_fail("I62-3", _rl, "exercised row has no non-blank `check`")
                    if type(_r.get("exit_code")) is not int or _r.get("exit_code") != 0:
                        _i62_fail("I62-3", _rl, f"exercised row exit_code {_r.get('exit_code')!r:.40} != 0")
                    if _i62_blank(_r.get("red_input")):
                        _i62_fail("I62-3", _rl, "exercised row has no non-blank `red_input` (an input that makes the check fail)")
                elif _disp == "owned_by":
                    # I62-4 — another graph unit whose frame.modifies covers an affected path, and
                    # which (from P8_SYNTHESIS on) holds a current PASS.
                    _own = _r.get("owner_unit")
                    _paths = _ob.get("referencing_paths") if isinstance(_ob, dict) else None
                    if not isinstance(_paths, list):
                        _paths = []
                    if not isinstance(_own, str) or _own == _u or _own not in _blast_units:
                        _i62_fail("I62-4", _rl, f"owner_unit {_own!r:.40} is not another unit of graph.json")
                    elif not any(frame_match.match_any_pattern(_p, _blast_mod.get(_own, [])) for _p in _paths):
                        _i62_fail("I62-4", _rl, f"owner {_own}'s frame.modifies covers none of the obligation's "
                                                f"referencing_paths {_paths[:5]!r:.160}")
                    elif _i62_late and not _i62_current_pass(_own):
                        _i62_fail("I62-4", _rl, f"owner {_own} holds no current PASS (verify.verdict PASS with "
                                                "verify.iteration == debrief.iteration) at synthesis")
                elif _disp == "unaffected":
                    # I62-5 — a judgement, so it must say why; I62-7 — a coupling cannot be unaffected.
                    if _i62_blank(_r.get("rationale")):
                        _i62_fail("I62-5", _rl, "unaffected row has no non-blank `rationale`")
                    if isinstance(_ob, dict) and _ob.get("kind") == "coupling":
                        _i62_fail("I62-7", _rl, "a coupling obligation dispositioned unaffected — it must be exercised")
                elif _disp == "broken":
                    # I62-6 — DECIDABLE BITE (the I22 precedent): a broken row on a PASS verdict.
                    if _verdict == "PASS":
                        _i62_fail("I62-6", _rl, "a broken impact row on a PASS verdict: a known breakage is a FAIL")
                else:
                    _i62_fail("I62-2", _rl, f"disposition must be exercised|unaffected|owned_by|broken, got {_disp!r:.40}")
            for _oid in sorted(_seen):
                if _seen[_oid] > 1:
                    _i62_fail("I62-2", f"{_loc} {_oid}", f"obligation dispositioned {_seen[_oid]} times (exactly once)")
                if isinstance(_obl, dict) and _oid not in _obl:
                    _i62_fail("I62-2", f"{_loc} {_oid}", "audit row names no obligation of impact.json")
            if isinstance(_obl, dict):
                for _oid in sorted(_obl):
                    if _oid not in _seen:
                        _i62_fail("I62-2", f"{_loc} {_oid}", "obligation has no blast_audit row (every id exactly once)")
        if not _i62_bad[0]:
            rep.ok(f"{_i62} ({_i62_n} executed ships unit(s): impact bound, every obligation settled)")

    # I63 end re-run / I64 integration before sign-off (1.15.0 blast radius). OFFLINE and POST-HOC like
    # I60-I62: both read the run-dir integration.json (written by scripts/integrate.py, with its
    # `<hex>  integration.json` sidecar), the units' footprints/briefs/debriefs and the blast config
    # RAW (json.load + isinstance), and take their antecedents (phase, gates) RAW from fsm-state.json
    # exactly as the armed flag is, so a schema-invalid record — fsm-state.json included — still reaches
    # its clause and a wrong-typed key is a FAIL row naming the key, never a traceback. Neither gates a
    # transition nor guards the correction loop's back-edge LT7; both reuse I60's armed flag (no further
    # version gate). I63 runs at P8_SYNTHESIS/DONE; I64's antecedent is the sign-off itself
    # (gates.signoff_confirmed, or the machine-closed signoff_machine_closed, each by IDENTITY to True).
    # No opt-out. An absent or unreadable integration.json is a FAIL wherever a clause needs it: I64-1 on
    # every signed-off run, and at P8/DONE I63-1 for each passed command-form check plus I63-2 whenever a
    # footprint wrote a file (no final hash is known). An absent blast config (neither <run>/blast-config.json nor
    # <workspace>/.dag/blast.json) is an I64-5 FAIL UNLESS integration.differential is a non-empty list: a
    # differential_none_reason never discharges it, because integrate.py writes one itself when it finds
    # no config. An absent config is not a way out of the clauses that judge the RECORD: with no config
    # visible, I64-7 judges EVERY integration censuses[] row as must_not_increase (added != 0 is a FAIL
    # naming the census), I64-5 FAILs a non-empty integration errors[] (without the config a declared
    # command that timed out or could not run cannot be told apart from an undeclared one), and every
    # differential row is judged on exit AND stdout (no `compare` narrows it). This NARROWS the
    # config-less gap, it does not close it: the declared-command coverage arm of I64-5 still has no
    # declared command to judge, and the validator judges the config visible to IT now, never the one
    # integrate.py was actually given (integrate.py accepts a config from any path).
    # Integration contract restated: {base_sha, base_tree_digest, tip_tree_digest, union_changes[{path,
    # status A|M|D|R|T, sha256_base, sha256_tip}] (a rename is a D row for the old path plus an A row
    # for the new one), unowned_writes[path], multi_writer_paths[{path, units[]}], replay[{unit_id,
    # case_id, command, exit_code}] (a replay that timed out or could not run is an errors[] row and NO
    # replay row — so a missing replay row is a failure, never "not applicable"), differential[{
    # regression_id, base_exit, tip_exit, base_stdout_sha256, tip_stdout_sha256, intended_change_ref}]
    # or differential_none_reason, test_weakening[{kind, detail, intended_change_ref}], censuses[{id,
    # base, tip, added, closed, shipped}], errors[]}. Blast config: the run-dir blast-config.json, else
    # <workspace_root>/.dag/blast.json — {regression_commands[{id, command, timeout_s, compare}] or
    # regression_none_reason, censuses[{id, command_template, must_not_increase}], ...}.
    # A differential row is judged on its EXIT status always, and on its stdout hash ONLY when that
    # command's declared `compare` names stdout in any letter case (e.g. "exit+stdout", "EXIT+STDOUT"):
    # an exit-only command's stdout
    # difference is not a difference (its stdout may embed a checkout path); a regression id the config
    # does not declare is judged on both. Limitation: I64 judges what integrate.py RECORDED. An exit
    # status that depends on the environment integrate.py gave the command (an optional package that
    # is or is not importable there) can match on both sides while failing on both — equal exits mean
    # "no recorded difference", never "no regression"; what must be 0 is each replayed check (I63-1).
    if _blast_armed:
        _i63 = LABEL_STEM["i63_replay"]
        _i64 = LABEL_STEM["i64_integration"]
        _i6x_f = _blast_fsm if isinstance(_blast_fsm, dict) else {}
        _i6x_g = _i6x_f.get("gates") if isinstance(_i6x_f.get("gates"), dict) else {}
        _i6x_ph = _i6x_f.get("phase")
        _i63_on = isinstance(_i6x_ph, str) and _i6x_ph in ("P8_SYNTHESIS", "DONE")
        _i64_on = _i6x_g.get("signoff_confirmed") is True or _i6x_g.get("signoff_machine_closed") is True
        _i6x_bad = {"I63": False, "I64": _ba_unmet is not None}

        def _i63_fail(clause, locus, detail):
            _i6x_bad["I63"] = True
            rep.fail(f"{_i63} ({clause} {locus})", detail)

        def _i64_fail(clause, locus, detail, item=None):
            # Every I64 FAIL passes through here: the one point where the per-item I64-8 override can
            # downgrade a NAMED finding, never a whole clause. `item` is the "<subject>" half of the I64-8
            # key and is passed ONLY by call sites whose row is about exactly one subject (a path, a
            # path + writer, a regression id, one weakened-test row, a census id); the default None marks
            # a record-structure row (a wrong-typed or malformed record entry, the blast config itself),
            # which is never acceptable and prints no key.
            _i6x_bad["I64"] = True
            _ba_ok, _ba_hint = _ba_take(clause, item, detail)
            if not _ba_ok:
                rep.fail(f"{_i64} ({clause} {locus})", detail + _ba_hint)

        def _i6x_list(obj, key, fail, clause, locus):
            """obj[key] as a list ([] when obj is not an object or lacks the key — a missing required key
            is the schema's FAIL); a present-but-non-list value is a FAIL row naming the key."""
            if not isinstance(obj, dict) or key not in obj:
                return []
            _v = obj[key]
            if not isinstance(_v, list):
                fail(clause, locus, f"`{key}` must be a list, got {type(_v).__name__}")
                return []
            return _v

        def _i6x_later(u, paths):
            """Units in a strictly later graph wave than u whose footprint touched any of `paths`."""
            _w = _blast_wave_of.get(u)
            if _w is None:
                return []
            return sorted(_x for _x in _blast_fp if _x != u and _blast_wave_of.get(_x) is not None
                          and _blast_wave_of[_x] > _w and _blast_fp[_x] & paths)

        if _i63_on or _i64_on:
            _ig_loc = "integration.json"
            _ig, _ig_err = _blast_raw(os.path.join(rd, _ig_loc))
            if _ig is not None and not isinstance(_ig, dict):
                _ig, _ig_err = None, f"not a JSON object (got {type(_ig).__name__})"
            _ig_fail, _ig_cl = (_i64_fail, "I64-1") if _i64_on else (_i63_fail, "I63-1")
            # (unit_id, case_id) -> True iff every replay row for it exited 0; units with an exit-0 row.
            _replay_ok = {}
            _replay_units_ok = set()
            for _r in _i6x_list(_ig, "replay", _ig_fail, _ig_cl, _ig_loc):
                if not (isinstance(_r, dict) and isinstance(_r.get("unit_id"), str)
                        and isinstance(_r.get("case_id"), str)):
                    _ig_fail(_ig_cl, _ig_loc, f"malformed replay[] row {_r!r:.120}")
                    continue
                _ex = _as_int(_r.get("exit_code"))
                _k = (_r["unit_id"], _r["case_id"])
                _replay_ok[_k] = _replay_ok.get(_k, True) and _ex == 0
                if _ex == 0:
                    _replay_units_ok.add(_r["unit_id"])
            # path -> [(unit, sha256_after, sha256_before)] from every parsed footprint (I60-3 owns shape
            # FAILs); a rename's old path is recorded as deleted by the renaming unit.
            _writes = {}
            for _u in sorted(_blast_fp):
                _fpd, _ = _blast_raw(os.path.join(units_dir, _u, "footprint.json"))
                _chg = _fpd.get("changes") if isinstance(_fpd, dict) else None
                if not isinstance(_chg, list):
                    continue
                for _c in _chg:
                    if not (isinstance(_c, dict) and isinstance(_c.get("path"), str)):
                        continue
                    _writes.setdefault(_c["path"], []).append((_u, _c.get("sha256_after"), _c.get("sha256_before")))
                    if isinstance(_c.get("from_path"), str):
                        _writes.setdefault(_c["from_path"], []).append((_u, None, _c.get("sha256_before")))

            if _i63_on:
                # I63-1 — every passed command-form check (a brief case_set entry with check_form command
                # whose orchestrator-origin row in the unit's current debrief is `discharged`) has a
                # replay row, and every replay row for it exited 0.
                for _u in sorted(unit_dirs_with_debrief):
                    _bb, _ = _blast_raw(os.path.join(units_dir, _u, "brief.json"))
                    _db, _ = _blast_raw(os.path.join(units_dir, _u, "debrief.json"))
                    _disc = {}
                    for _r in _i6x_list(_db, "case_set_discharge", _i63_fail, "I63-1", f"units/{_u}/debrief.json"):
                        if isinstance(_r, dict) and _r.get("origin") == "orchestrator" and isinstance(_r.get("id"), str):
                            _disc[_r["id"]] = _r.get("outcome")
                    for _e in _i6x_list(_bb, "case_set", _i63_fail, "I63-1", f"units/{_u}/brief.json"):
                        if not (isinstance(_e, dict) and _e.get("check_form") == "command"
                                and isinstance(_e.get("id"), str) and _disc.get(_e["id"]) == "discharged"):
                            continue
                        _st = _replay_ok.get((_u, _e["id"]))
                        if _st is True:
                            continue
                        _why = "replayed with a non-zero exit" if _st is False else (
                            "has no replay row" + ("" if _ig is not None else f" (integration.json {_ig_err})"))
                        _i63_fail("I63-1", f"{_u}/{_e['id']}",
                                  f"passed command-form check {_why} — regressed unit {_u}; later-wave units "
                                  f"whose footprints touched its files: {_i6x_later(_u, _blast_fp.get(_u, set())) or 'none'}")
                # I63-2 — a unit's footprint sha256_after differs from the path's final hash only when a
                # later-wave unit's footprint wrote that path. Final hash: integration union_changes
                # sha256_tip; a path the union omits is unchanged base->tip (its earliest writer's
                # sha256_before). With no readable union_changes there is NO final hash, so a footprint
                # that wrote any file is an I63-2 FAIL ("final hashes unknown"), never a self-comparison.
                _tip = {}
                for _c in _i6x_list(_ig, "union_changes", _ig_fail, _ig_cl, _ig_loc):
                    if isinstance(_c, dict) and isinstance(_c.get("path"), str):
                        _tip[_c["path"]] = _c.get("sha256_tip")
                _union_known = isinstance(_ig, dict) and isinstance(_ig.get("union_changes"), list)
                if not _union_known and _writes:
                    _i63_fail("I63-2", _ig_loc, f"final hashes unknown ({_ig_err or 'no union_changes list'}) — "
                                                f"{len(_writes)} footprint-written path(s) cannot be shown unchanged after their unit")
                for _p in (sorted(_writes) if _union_known else []):
                    _ws = _writes[_p]
                    _final = _tip[_p] if _p in _tip else min(_ws, key=lambda _t: _blast_wave_of.get(_t[0], -1))[2]
                    for _u, _aft, _bef in _ws:
                        if _aft != _final and not _i6x_later(_u, {_p}):
                            _i63_fail("I63-2", f"{_u} {_p}",
                                      f"footprint sha256_after {_aft!r:.24} != final hash {_final!r:.24} and no "
                                      f"later-wave unit's footprint wrote it — the file changed after {_u} was verified")

            if _i64_on:
                # I64-1 — integration.json present, schema-valid, sidecar matching, start state = fsm-state.blast.
                if _ig is None:
                    _i64_fail("I64-1", _ig_loc, f"{_ig_err} on a signed-off armed run — the whole-run integration "
                                                "must be recorded before sign-off; a missing record is a FAIL, never an opt-out")
                else:
                    if not isinstance(docs.get("integration"), dict):
                        _i64_fail("I64-1", _ig_loc, "not schema-valid against integration.schema.json")
                    try:
                        with open(os.path.join(rd, _ig_loc), "rb") as _fh:
                            _igsha = hashlib.sha256(_fh.read()).hexdigest()
                        with open(os.path.join(rd, _ig_loc + ".sha256"), "r", encoding="utf-8") as _fh:
                            _side = _fh.read().split()
                        _side0 = _side[0].lower() if _side else None
                    except Exception as _e:
                        _igsha, _side0 = None, f"<unreadable sidecar: {type(_e).__name__}>"
                    if _igsha is None or _side0 != _igsha:
                        _i64_fail("I64-1", _ig_loc, f"integration.json.sha256 {_side0!r:.80} != sha256(integration.json) {_igsha!r}")
                    for _k in ("base_sha", "base_tree_digest"):
                        _want = _bl.get(_k) if isinstance(_bl, dict) else None
                        if _ig.get(_k) != _want:
                            _i64_fail("I64-1", f"{_ig_loc} {_k}", f"{_ig.get(_k)!r:.80} != fsm-state.blast.{_k} {_want!r:.80}")
                    # I64-2 — identical start and end trees while a ships unit changed files: invalid control.
                    _ships_chg = sorted(_u for _u in _blast_fp if _blast_fp[_u]
                                        and _blast_units.get(_u, {}).get("deliverable") == "ships")
                    if _ships_chg and _ig.get("base_tree_digest") == _ig.get("tip_tree_digest"):
                        _i64_fail("I64-2", _ig_loc, f"base_tree_digest == tip_tree_digest while ships unit(s) "
                                                    f"{_ships_chg[:5]} changed files — an identical-sides comparison is invalid")
                    # I64-3 — every changed path is owned by some unit's frame.
                    for _w in _i6x_list(_ig, "unowned_writes", _i64_fail, "I64-3", _ig_loc):
                        _i64_fail("I64-3", f"{_ig_loc} {_w!r:.120}", "a changed path no unit's frame owns",
                                  item=_w if isinstance(_w, str) and _w.strip() else None)
                    # I64-4 — every path with >1 writer (footprints UNION integration multi_writer_paths) has,
                    # for each writer, at least one replay row with exit 0.
                    _mw = {}
                    for _p, _ws in _writes.items():
                        if len({_t[0] for _t in _ws}) > 1:
                            _mw[_p] = {_t[0] for _t in _ws}
                    for _m in _i6x_list(_ig, "multi_writer_paths", _i64_fail, "I64-4", _ig_loc):
                        _mu = _m.get("units") if isinstance(_m, dict) else None
                        if not (isinstance(_m, dict) and isinstance(_m.get("path"), str) and isinstance(_mu, list)):
                            _i64_fail("I64-4", _ig_loc, f"malformed multi_writer_paths[] entry {_m!r:.120}")
                            continue
                        _mw.setdefault(_m["path"], set()).update(_x for _x in _mu if isinstance(_x, str))
                    for _p in sorted(_mw):
                        for _u in sorted(_mw[_p]):
                            if _u not in _replay_units_ok:
                                _i64_fail("I64-4", f"{_p} {_u}", f"multi-writer path has no exit-0 replay row for writer {_u}",
                                          item=f"{_p} {_u}")
                # I64-5 / I64-6 read the frozen intended changes and the blast config.
                _intended = set()
                for _bu in _blast_units.values():
                    _fr = _bu.get("frame")
                    _ics = _fr.get("intended_changes") if isinstance(_fr, dict) else None
                    if isinstance(_ics, list):
                        _intended.update(_x for _x in _ics if isinstance(_x, str))
                _bc_loc = "blast-config.json"
                _bc, _bc_err = _blast_raw(os.path.join(rd, _bc_loc))
                if _bc is None and _bc_err == "absent" and isinstance(_bl_ws, str):
                    _bc_loc = "<workspace>/.dag/blast.json"
                    _bc, _bc_err = _blast_raw(os.path.join(_bl_ws, ".dag", "blast.json"))
                _bc_absent = _bc is None and _bc_err == "absent"
                if _bc_absent:
                    # No config in the run dir nor the workspace: nothing declares regression commands or
                    # explains their absence, so the ONLY accepted evidence is a NON-EMPTY recorded
                    # differential (a regression command demonstrably ran). A differential_none_reason is NOT
                    # accepted: integrate.py writes one itself when it finds no config ("no blast config, so
                    # no regression commands to compare") — generated by the tool, not given by anyone.
                    _ig_dif = _ig.get("differential") if isinstance(_ig, dict) else None
                    if not (isinstance(_ig_dif, list) and _ig_dif):
                        _i64_fail("I64-5", "blast-config.json", "no blast config (run dir or <workspace>/.dag/blast.json) "
                                  "and no recorded differential row — without a config only a non-empty integration "
                                  "differential shows a regression command ran; a differential_none_reason does not count")
                    # ... and any recorded integration error is a FAIL: with no config, a declared command
                    # that timed out or could not run (an errors[] row and no differential row) cannot be
                    # told apart from an undeclared one. Deliberately not acceptable per item: the remedy
                    # is a visible config that declares the commands or explains their absence.
                    _ig_er0 = _ig.get("errors") if isinstance(_ig, dict) else None
                    if _ig_er0 is not None and _ig_er0 != []:
                        _i64_fail("I64-5", "blast-config.json", "no blast config (run dir or <workspace>/.dag/blast.json) "
                                  "and a non-empty integration errors[] "
                                  f"({len(_ig_er0) if isinstance(_ig_er0, list) else type(_ig_er0).__name__}: {_ig_er0!r:.120}) — "
                                  "without the config a declared regression command that timed out or could not run "
                                  "is indistinguishable from an undeclared one")
                elif not isinstance(_bc, dict):
                    _i64_fail("I64-5", _bc_loc, f"unreadable blast config ({_bc_err or 'not an object'}) — "
                                                "regression commands must be declared or their absence explained")
                    _bc = None
                _rcs = _i6x_list(_bc, "regression_commands", _i64_fail, "I64-5", _bc_loc)
                _rnr = _bc.get("regression_none_reason") if isinstance(_bc, dict) else None
                if isinstance(_bc, dict) and not _rcs and not (isinstance(_rnr, str) and _rnr.strip()):
                    _i64_fail("I64-5", _bc_loc, "regression_commands is empty and no non-blank regression_none_reason is given")
                _cmp = {}
                for _rc in _rcs:
                    if isinstance(_rc, dict) and isinstance(_rc.get("id"), str):
                        _cmp[_rc["id"]] = _rc.get("compare")
                if _ig is not None:
                    # I64-5 — every recorded old-vs-new difference cites a frozen intended change verbatim;
                    # every declared regression command has a differential row (a timed-out one has none).
                    _diff_ids = set()
                    _dif_rows = _i6x_list(_ig, "differential", _i64_fail, "I64-5", _ig_loc)
                    for _d in _dif_rows:
                        if not (isinstance(_d, dict) and isinstance(_d.get("regression_id"), str)):
                            _i64_fail("I64-5", _ig_loc, f"malformed differential[] row {_d!r:.120}")
                            continue
                        _rid = _d["regression_id"]
                        _diff_ids.add(_rid)
                        _cm = _cmp.get(_rid)
                        _judge_out = not isinstance(_cm, str) or "stdout" in _cm.lower()
                        _differs = _d.get("base_exit") != _d.get("tip_exit") or (
                            _judge_out and _d.get("base_stdout_sha256") != _d.get("tip_stdout_sha256"))
                        _ref = _d.get("intended_change_ref")
                        if _differs and not (isinstance(_ref, str) and _ref in _intended):
                            _i64_fail("I64-5", f"differential {_rid!r:.60}", item=str(_rid), detail=
                                      f"base/tip differ (judged on {'exit+stdout' if _judge_out else 'exit'}) and "
                                      f"intended_change_ref {_ref!r:.80} is no unit's frame.intended_changes entry verbatim")
                    # Coverage applies unless fsm-state.blast.mode is "snapshot" AND the record carries no
                    # differential row: integrate.py writes differential rows ONLY in git mode — a snapshot run
                    # cannot rebuild the start tree and records exactly that as its differential_none_reason, so
                    # its declared commands are never compared (stated in the record, not a timeout). A snapshot
                    # record that nevertheless carries differential rows claims a comparison, so it is judged on
                    # coverage like any other mode. Otherwise a declared command with no row is a FAIL: one that
                    # timed out, could not run or was malformed leaves an errors[] row and no row here.
                    _ig_dnr = _ig.get("differential_none_reason")
                    _ig_ers = _ig.get("errors")
                    for _rid in ([] if _bl_mode == "snapshot" and not _dif_rows else sorted(set(_cmp) - _diff_ids)):
                        _i64_fail("I64-5", f"differential {_rid!r:.60}", item=str(_rid), detail=
                                  f"declared regression command has no differential row in blast mode {_bl_mode!r} — "
                                  + (f"the record says {_ig_dnr!r:.120}; " if isinstance(_ig_dnr, str) and _ig_dnr.strip() else "")
                                  + "a command that timed out, could not run or was malformed leaves an integration "
                                  f"errors[] row instead ({len(_ig_ers) if isinstance(_ig_ers, list) else 'no'} recorded)")
                    # I64-6 — every weakened-test row cites a frozen intended change verbatim.
                    for _t in _i6x_list(_ig, "test_weakening", _i64_fail, "I64-6", _ig_loc):
                        _ref = _t.get("intended_change_ref") if isinstance(_t, dict) else None
                        if not (isinstance(_ref, str) and _ref in _intended):
                            _tk = _t.get("kind") if isinstance(_t, dict) else None
                            _td = _t.get("detail") if isinstance(_t, dict) else None
                            _i64_fail("I64-6", f"test_weakening {(_tk if isinstance(_t, dict) else _t)!r:.60}",
                                      item=(f"{_tk} {_td}" if isinstance(_tk, str) and _tk.strip()
                                            and isinstance(_td, str) and _td.strip() else None), detail=
                                      f"intended_change_ref {_ref!r:.80} is no unit's frame.intended_changes entry verbatim")
                    # I64-7 — a must_not_increase census added nothing (GROSS: closures never offset an addition).
                    _cen = {}
                    _cen_rows = []
                    for _c in _i6x_list(_ig, "censuses", _i64_fail, "I64-7", _ig_loc):
                        if isinstance(_c, dict) and isinstance(_c.get("id"), str):
                            _cen[_c["id"]] = _c
                            _cen_rows.append(_c)
                    # With NO config visible nothing declares which census must not increase, so every recorded
                    # census row is judged as must_not_increase (each row, so a duplicated id cannot mask one).
                    for _c in (_cen_rows if _bc_absent else []):
                        if _as_int(_c.get("added")) != 0:
                            _i64_fail("I64-7", f"census {_c['id']!r:.60}", item=_c["id"], detail=f"added {_c.get('added')!r} "
                                      "!= 0 with no blast config visible (run dir or <workspace>/.dag/blast.json), so every "
                                      "recorded census is judged must_not_increase (gross, not net)")
                    for _c in _i6x_list(_bc, "censuses", _i64_fail, "I64-7", _bc_loc):
                        if not (isinstance(_c, dict) and _c.get("must_not_increase") is True and isinstance(_c.get("id"), str)):
                            continue
                        _row = _cen.get(_c["id"])
                        if _row is None:
                            _i64_fail("I64-7", f"census {_c['id']!r:.60}", "must_not_increase census has no integration censuses[] row",
                                      item=_c["id"])
                        elif _as_int(_row.get("added")) != 0:
                            _i64_fail("I64-7", f"census {_c['id']!r:.60}", item=_c["id"], detail=f"added {_row.get('added')!r} != 0 on a "
                                                                          "must_not_increase census (gross, not net)")
        if _i63_on and not _i6x_bad["I63"]:
            rep.ok(f"{_i63} (every passed command-form check replayed green; no file changed after its unit)")
        if _i64_on and not _i6x_bad["I64"]:
            rep.ok(f"{_i64} (integration recorded, owned, covered and explained before sign-off)")
        if _i64_on and _ba_items - set(_ba_hit):
            print(f"  NOTE  {LABEL_STEM['note_i64']}: over-broad — blast_accepted.items "
                  f"{json.dumps(sorted(_ba_items - set(_ba_hit)))[:300]} match(es) no I62-4/I64 finding on this run "
                  f"(an item downgrades only a FAIL row printing exactly that key, '<clause>:<subject>' with clause "
                  f"one of {', '.join(_BA_CLAUSES)}); advisory, nothing downgraded")

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
    # 1.14.0 / I51 — **REVISES**, declared. The TABLE above is UNCHANGED (spec_check SC3 diffs it
    # against the spec-derived gate map, and this widening must not move that diff); what is widened
    # is the SATISFACTION TEST: each of the three HUMAN gates is now satisfied by
    # `<g>_confirmed OR <g>_machine_closed`. The two MECHANICAL flags (cartography_done,
    # decomposition_approved) are untouched — they are phase-completion flags with no human
    # touchpoint, so they have nothing to record.
    #
    # WHAT THIS CHANGES, in one sentence: today a run at DONE asserts a human signed off; after this
    # it asserts a human signed off OR a machine closed sign-off under a recorded run_mode with a
    # recorded analyst. That is weaker, and it is the whole point — before this widening, honesty and
    # completion were MUTUALLY EXCLUSIVE, because SKILL.md says setting a gate flag without a human
    # is a defect while REQUIRED_GATES makes signoff_confirmed mandatory for DONE. `*_confirmed`
    # keeps its exact meaning and SKILL.md's sentence stays literally true and unedited; I51-2 makes
    # setting BOTH a hard FAIL, so the machine path cannot reach the human vocabulary even by
    # mistake.
    #
    # MIGRATION — three things change for EXISTING run directories, one of them unrepairable:
    #   (1) Nothing fails, BUT ONLY because I51-1 is version-gated: `run_mode` is a new top-level
    #       fsm-state property, so an unarmed presence check would red every archived run in .wip/.
    #   (2) Every archived `signoff_confirmed: true` becomes permanently AMBIGUOUS — a human, or a
    #       run written before the distinction existed. There is nothing honest to backfill, because
    #       the fact was never recorded. This breaks a READER'S INFERENCE, not a predicate, and it
    #       CANNOT BE REPAIRED.
    #   (3) Any external consumer of `gates` that reads the five known flags will read a
    #       fully-automatic run as unfinished until it is taught this OR.
    _N14_GATE_OR = {"personas_confirmed": "personas_machine_closed",
                    "clarification_resolved": "clarification_machine_closed",
                    "signoff_confirmed": "signoff_machine_closed"}
    #
    # THE WIDENING IS ITSELF VERSION-GATED, and this is the hole that made it necessary. Left
    # unversioned, `signoff_machine_closed` satisfied DONE at ANY stamp while every arm that gives
    # that flag meaning (I51-2..6, including the I51-3 backing check) is gated at 1.14.0 — so a run
    # stamped 1.13.0 could delete machine-decisions.json entirely, reach DONE with no human and no
    # machine record, exit 0 with ZERO I51 rows, and have the validator print "closed by the MACHINE
    # channel, not by a human" having verified nothing. Not an adversarial-only path: --restamp is
    # opt-in and unenforced, so any run scaffolded before the bump and continued after it keeps the
    # old stamp while the new SKILL.md tells the orchestrator to set the key. The flag must not be
    # load-bearing anywhere its guards are asleep. Archive-safe: no pre-1.14.0 run sets the key.
    _n14_or_armed = _i27_semver_ge(_n14_ver, _N14_SHIP)
    _skew_record("I51-GATE-OR", any(gates.get(_m) is True for _m in _N14_GATE_OR.values()),
                 _N14_SHIP, _n14_ver)
    if fsm:
        gates = fsm.get("gates", {})
        need = REQUIRED_GATES.get(phase, [])
        missing = [g for g in need
                   if not (gates.get(g, False)
                           or (_n14_or_armed and gates.get(_N14_GATE_OR.get(g, ""), False)))]
        if missing:
            rep.fail(f"{LABEL_STEM['gate_ordering']}",
                     f"phase {phase} requires gates {missing} = true "
                     f"(or the disjoint machine sibling {[_N14_GATE_OR[g] for g in missing if g in _N14_GATE_OR]})")
        elif need:
            _n14_via_machine = [g for g in need
                                if not gates.get(g, False) and _n14_or_armed
                                and gates.get(_N14_GATE_OR.get(g, ""), False)]
            rep.ok(f"{LABEL_STEM['gate_ordering']} (phase {phase}: prior gates satisfied"
                   + (f"; {_n14_via_machine} closed by the MACHINE channel, not by a human"
                      if _n14_via_machine else "") + ")")

    # N-I45 version-skew visibility (P3 §3.1(3)) — exit-neutral by CONSTRUCTION: a bare print, touching
    # neither rep.problems nor rep.checked. DELIBERATELY NOT gated on args.quiet (§3.3): SKILL.md mandates
    # --quiet, so a quiet-gated skew NOTE would be inert in THE MANDATED ORCHESTRATOR INVOCATION. That
    # wording is normative and deliberate (§3.3, §3.4, §9-R18): an earlier revision of this line called
    # --quiet the sole invocation of any consequence, which OVER-STATES it and is RETRACTED (§3.3 quotes
    # the retracted phrase verbatim; it is not re-published here, so that a `grep` for it locates only
    # loci that still ASSERT it) — a human, a
    # reviewer and the fixture harness all run the validator WITHOUT --quiet (run_tests.sh does), which is
    # why a quiet-gated N-I45 would still have passed the i45_skew_note row. The closest
    # sibling (the I39-4 "governance disarmed; unstamped" NOTE) IS quiet-gated; this deviates knowingly and
    # the divergence is filed as residual §9-R14 rather than left unexplained (an earlier revision of this
    # line cross-referenced it to §9-R7, which covers the INSERTION SITES, so the divergence was in fact
    # carried by no residual at all — corrected per §3.3). Zero suppressed arms emits
    # NOTHING. Wording is normative (§3.2/L16): this counts EVALUATION GATES, never failures.
    if len(_SKEW) >= 1:
        print(f"  NOTE  {LABEL_STEM['i45_version_skew']}: validator_version={_i27_ver!r} suppressed "
              f"{len(_SKEW)} version-gated arm(s) whose other preconditions HELD: "
              f"{sorted(a['arm'] for a in _SKEW)}. Suppressed arms are an UPPER BOUND on suppressed "
              "FAILs — an armed clause may have passed. Re-run with the stamp raised to see the actual "
              "verdicts.")

    # N-I57 run composition (1.14.0, Drift fix 5) — OBSERVABLE-ONLY and EXIT-NEUTRAL BY
    # CONSTRUCTION: a bare print touching neither rep.problems nor rep.checked, the exact N-I45
    # archetype. Deliberately NOT --quiet-gated, for the reason N-I45 records: SKILL.md mandates
    # --quiet, so a quiet-gated NOTE would be inert in the one invocation that matters.
    #
    # WHAT IT IS AND IS NOT. The gap the diagnosis actually establishes is NOT that housekeeping is
    # unbounded — searched by CAPABILITY rather than by activity name, executor repairs, panel
    # re-polls, re-verification, amendments, dialogue rounds and per-unit reading are all already
    # bounded — it is that a run's COMPOSITION is UNPUBLISHED. No artifact anywhere states the ratio
    # of work that ships to work that only informs, so no one could have been asked to choose. THIS
    # PROPOSAL MAKES THE AGGREGATE LEGIBLE AND DOES NOT BOUND IT. The enforced half — an `hk_fuel`
    # counter — is DEFERRED (no run has yet been MEASURED to lose delivery to housekeeping, and its
    # exhaustion route has no defined path in fully-automatic mode); its adoption trigger is the
    # first run whose N-I57 line records delivered units stalling while housekeeping counts rise.
    #
    # TWO GROUPS, KEPT APART, BECAUSE THEY ARE NOT COMPARABLE — and never summed. Unit-loop
    # artifacts are bounded by I4 (retries <= 2, iteration <= retries+1) and the R_MAX=3 re-poll cap;
    # run-level ledger acts are bounded by nothing. Where an input is absent the count prints `n/a`
    # rather than guessing, and the exit status is unchanged either way.
    def _n57(fn):
        try:
            return fn()
        except Exception:
            return None

    def _n57s(v):
        return "n/a" if v is None else str(v)

    def _n57_count(rel, pat):
        _t = None
        try:
            with open(os.path.join(rd, rel), "r", encoding="utf-8", errors="replace") as _f:
                _t = _f.read()
        except Exception:
            return None
        return len(re.findall(pat, _t, re.M | re.I))

    def _n57_glob(sub, pat):
        _base = os.path.join(rd, "units")
        if not os.path.isdir(_base):
            return None
        _n = 0
        for _u in os.listdir(_base):
            _ud = os.path.join(_base, _u)
            if not os.path.isdir(_ud):
                continue
            _n += sum(1 for _f in os.listdir(_ud) if re.match(pat, _f))
        return _n

    _n57_dec = _n57(lambda: _n57_count("DECISIONS.md", r"^## "))
    _n57_cor = _n57(lambda: _n57_count("PROGRESS.md", r"correct|supersed|retract|withdraw"))
    _n57_lrn = _n57(lambda: len(load_json(os.path.join(rd, "learnings.json")).get("entries") or []))
    _n57_pan = _n57(lambda: _n57_glob("units", r"^verify_p.*\.json$"))
    _n57_fbk = _n57(lambda: _n57_glob("units", r"^feedback_iter.*\.md$"))
    _n57_ship = None
    try:
        if any((_gu or {}).get("deliverable") for _gu in _n14_units_by_id.values()):
            _n57_ship = sum(1 for _u, _gu in _n14_units_by_id.items()
                            if _gu.get("deliverable") == "ships" and _n14_verdict(_u) == "PASS")
    except Exception:
        _n57_ship = None
    print(f"  NOTE  {LABEL_STEM['note_i57']}: delivered (deliverable:'ships' PASS-verified) = "
          f"{_n57s(_n57_ship)}; run-level housekeeping (bounded by NOTHING) = "
          f"{_n57s(_n57_dec)} DECISIONS entries, {_n57s(_n57_cor)} PROGRESS correction/supersession "
          f"mentions, {_n57s(_n57_lrn)} learnings.json entries; unit-loop artifacts (already bounded "
          f"by I4 and the R_MAX=3 re-poll cap — NOT comparable with the group above, never summed) = "
          f"{_n57s(_n57_pan)} verify_p files, {_n57s(_n57_fbk)} feedback_iter rounds. "
          "ADVISORY: this makes the aggregate LEGIBLE and does not bound it, and it counts RECORDED "
          "artifacts only.")

    # N-I65 blast summary (1.15.0) — EXIT-NEUTRAL BY CONSTRUCTION and printed even under --quiet (the
    # N-I45 reasoning: a bare print touching neither rep.problems nor rep.checked). On an armed run with
    # >= 1 footprint it makes the blast record LEGIBLE: changed paths (union of unit footprints),
    # blast-audit obligations by disposition, shared (multi-writer) paths, census added / closed /
    # still present PER CENSUS ID from integration.json (never summed across censuses, which may count
    # different things; "still present" = the census's sites at tip, this run's additions included),
    # plus two facts no I63/I64 clause judges — the count of integration errors[] rows, and, when the
    # blast config declares regression commands, that a snapshot-mode run compared none of them
    # (snapshot mode writes no differential rows). Only real integers are counted (a boolean is not 1).
    # It checks declared, visible surfaces only: it never claims the run broke nothing.
    if _blast_armed and _blast_fp:
        _n65_fps = [_v for _v in _blast_fp.values() if isinstance(_v, (set, frozenset))]
        _n65_all = set().union(*_n65_fps)
        _n65_shared = sorted(_p for _p in _n65_all if sum(1 for _v in _n65_fps if _p in _v) > 1)
        _n65_disp = {}
        for _u in sorted(_blast_units):
            _vf, _ = _blast_raw(os.path.join(units_dir, _u, "verify.json"))
            _au = _vf.get("blast_audit") if isinstance(_vf, dict) else None
            _rows = _au.get("rows") if isinstance(_au, dict) else None
            if not isinstance(_rows, list):
                continue
            for _r in _rows:
                _d = _r.get("disposition") if isinstance(_r, dict) else None
                _d = _d if isinstance(_d, str) else "malformed"
                _n65_disp[_d] = _n65_disp.get(_d, 0) + 1
        _n65_ig, _ = _blast_raw(os.path.join(rd, "integration.json"))
        _n65_ig = _n65_ig if isinstance(_n65_ig, dict) else {}
        _n65_cen = _n65_ig.get("censuses")
        _n65_cen = [_c for _c in _n65_cen if isinstance(_c, dict)] if isinstance(_n65_cen, list) else []
        _n65_num = lambda _x: str(_x) if type(_x) is int else "?"
        _n65_cs = "; ".join(f"{json.dumps(_c.get('id'))[:60]} added {_n65_num(_c.get('added'))}, closed (removed) "
                            f"{_n65_num(_c.get('closed'))}, still present at tip {_n65_num(_c.get('tip'))}"
                            for _c in _n65_cen[:8]) + (f"; +{len(_n65_cen) - 8} more" if len(_n65_cen) > 8 else "")
        _n65_err = _n65_ig.get("errors")
        _n65_bl = _blast_fsm.get("blast") if isinstance(_blast_fsm, dict) else None
        _n65_snap = isinstance(_n65_bl, dict) and _n65_bl.get("mode") == "snapshot"
        # The declared regression commands, read from the same config I64-5 reads (run dir, else workspace).
        _n65_bc, _n65_bce = _blast_raw(os.path.join(rd, "blast-config.json"))
        if _n65_bc is None and _n65_bce == "absent" and isinstance(_bl_ws, str):
            _n65_bc, _ = _blast_raw(os.path.join(_bl_ws, ".dag", "blast.json"))
        _n65_rc = _n65_bc.get("regression_commands") if isinstance(_n65_bc, dict) else None
        _n65_nrc = len(_n65_rc) if isinstance(_n65_rc, list) else 0
        print(f"  NOTE  {LABEL_STEM['note_i65']}: changed paths = {len(_n65_all)} (union of "
              f"{len(_n65_fps)} footprint(s)); obligations by outcome = "
              f"{json.dumps(dict(sorted(_n65_disp.items()))) if _n65_disp else 'none audited'}; shared "
              f"(multi-writer) paths = {len(_n65_shared)} {json.dumps(_n65_shared[:5])[:200]}; census = "
              + (f"{len(_n65_cen)} row(s), per census id (still present = sites at tip): {_n65_cs}"
                 if _n65_cen else "no integration censuses[] rows")
              + f"; integration errors[] = {len(_n65_err) if isinstance(_n65_err, list) else 'none recorded'}"
              + (f"; snapshot mode: the {_n65_nrc} declared regression command(s) were NOT compared (no "
                 "differential rows)" if _n65_snap and _n65_nrc else "")
              + ". ADVISORY: checks declared, visible surfaces only.")
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
