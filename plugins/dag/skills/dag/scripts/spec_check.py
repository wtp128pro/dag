#!/usr/bin/env python3
"""spec_check.py — DEV-TIME prose ↔ spec ↔ code drift checker.

This tool DIFFS the descriptive spec (`spec/*.json`) against the enforcement code
(`scripts/validate_run.py`) and the JSON Schemas (`schemas/*.json`). It is invoked
ONLY by `run_tests.sh` and by hand.

It is NOT part of the run-validation path:
  * `validate_run.py` never reads `spec/` and never imports this module.
  * This module imports `validate_run` ONLY to read the importable `LABELS` table and
    to reuse `make_validator()`. `validate_run.main()` is `__main__`-guarded, so the
    import runs NO validation and touches no run artifacts.

Checks implemented here (U05): the harness core + SC1, SC3, SC4.
Extension points are left for U06 (SC2/SC5) and U07 (SC6/SC7) — see the `CHECKS`
registry near the bottom; append `(name, fn)` tuples there and add a check function
following the `def scN_...(ctx, rep)` convention below.

CLI:  spec_check.py [--quiet] [--root DIR]
  --quiet   print only NOTE/FAIL lines + the RESULT summary (suppress PASS + header)
  --root    override the skill-dir root every file read resolves against (default:
            this script's own skill dir, so the tool is CWD-independent). U09's
            negative fixtures pass a copied+mutated tree here.

Exit code: 0 iff no check FAILs (NOTE never fails).
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Reporting — PASS / NOTE / FAIL lines + a RESULT summary. Mirrors the shape of
# validate_run.Report but adds NOTE (advisory, never fails). Reusable by U06/U07.
# ---------------------------------------------------------------------------
class Report:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.passes = []
        self.notes = []
        self.fails = []

    def ok(self, label):
        self.passes.append(label)
        if not self.quiet:
            print(f"  PASS  {label}")

    def note(self, label):
        # NOTE is advisory: printed even under --quiet, but never affects exit code.
        self.notes.append(label)
        print(f"  NOTE  {label}")

    def fail(self, label, detail):
        self.fails.append((label, detail))
        print(f"  FAIL  {label}: {detail}")

    def summary(self):
        result = "FAIL" if self.fails else "PASS"
        print(f"\nRESULT: {result}  ·  PASS {len(self.passes)}"
              f"  NOTE {len(self.notes)}  FAIL {len(self.fails)}")
        return 1 if self.fails else 0


# ---------------------------------------------------------------------------
# Context — everything a check needs, all file reads routed through `root`.
# Reusable helpers for U06/U07: ctx.root, ctx.load_json(rel), ctx.validate /
# ctx.backend (from validate_run.make_validator), ctx.V (the validate_run module,
# for V.LABELS), ctx.parse_required_gates().
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, root, module, validate, backend):
        self.root = root
        self.V = module          # imported validate_run (for LABELS)
        self.validate = validate  # (instance, schema) -> [error strings]
        self.backend = backend

    def load_json(self, rel):
        """Load a JSON file at `rel` under the resolved root."""
        with open(self.root / rel, "r", encoding="utf-8") as f:
            return json.load(f)

    def parse_required_gates(self):
        """AST-parse the LOCAL `REQUIRED_GATES` dict out of validate_run.py source.

        REQUIRED_GATES lives INSIDE validate_run.main(), so it cannot be imported.
        We read the source (root copy first so --root fixtures can mutate it, else the
        imported module's own file), walk the AST for the `Assign` whose target is
        `REQUIRED_GATES`, and `ast.literal_eval` its value. Returns the dict, or None
        if it cannot be found/evaluated (the caller MUST fail loudly on None — a silent
        empty parse would let SC3 pass vacuously).
        """
        src_path = self.root / "scripts" / "validate_run.py"
        if not src_path.exists():
            src_path = Path(self.V.__file__).resolve()
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "REQUIRED_GATES":
                        try:
                            return ast.literal_eval(node.value)
                        except Exception:
                            return None
        return None


# ---------------------------------------------------------------------------
# SC1 — invariant registry (spec/invariants.json) ↔ validator labels (V.LABELS),
# BOTH directions.
# ---------------------------------------------------------------------------
def sc1_registry_labels(ctx, rep):
    reg = ctx.load_json("spec/invariants.json")
    entries = reg["entries"]
    labels = ctx.V.LABELS

    label_groups = sorted({e["invariant"] for e in labels})
    label_stems = {e["stem"] for e in labels}
    ids = {e["id"] for e in entries}
    mechanical = [e for e in entries if e.get("tier") == "mechanical"]

    failed = False

    # REVERSE: every distinct LABELS[].invariant group must have a registry entry.
    for g in label_groups:
        if g not in ids:
            rep.fail("SC1", f"label group '{g}' has no invariants.json entry")
            failed = True

    # FORWARD: every mechanical entry must carry non-empty, real label prefixes.
    for e in mechanical:
        prefixes = e.get("validator_label_prefixes") or []
        bad = [p for p in prefixes if p not in label_stems]
        if not prefixes:
            rep.fail("SC1", f"mechanical entry '{e['id']}' has empty/bogus "
                            f"label_prefixes: []")
            failed = True
        elif bad:
            rep.fail("SC1", f"mechanical entry '{e['id']}' has empty/bogus "
                            f"label_prefixes: {bad}")
            failed = True

    if not failed:
        rep.ok(f"SC1 registry<->labels bidirectional "
               f"({len(label_groups)} label groups, {len(mechanical)} mechanical entries)")


# ---------------------------------------------------------------------------
# SC3 — REQUIRED_GATES (code) == phase→gate map derived from spec/fsm.json guards.
# ---------------------------------------------------------------------------
def sc3_required_gates(ctx, rep):
    required_gates = ctx.parse_required_gates()
    # Guard against a vacuous pass: an empty/None parse must FAIL LOUDLY, not skip.
    if not required_gates:
        rep.fail("SC3", "REQUIRED_GATES not found (or empty) in validate_run.py source "
                        "— ast parse yielded nothing; cannot diff gate map")
        return

    fsm = ctx.load_json("spec/fsm.json")
    states = fsm["states"]
    idx = {s: i for i, s in enumerate(states)}
    guards = fsm["guards"]

    drift = False
    for phase, actual_list in required_gates.items():
        if phase not in idx:
            rep.fail("SC3", f"REQUIRED_GATES phase '{phase}' is not a member of fsm states[]")
            drift = True
            continue
        pi = idx[phase]
        # Prefix-closed accumulation: a flag-bearing guard's gate_flag is required
        # from its required_from_phase onward (index() <= index(P)).
        derived = sorted(
            g["gate_flag"] for g in guards
            if g.get("gate_flag") is not None
            and g.get("required_from_phase") in idx
            and idx[g["required_from_phase"]] <= pi
        )
        actual = sorted(actual_list)
        if derived != actual:
            rep.fail("SC3", f"gate drift at {phase}: spec-derived {derived} "
                            f"!= REQUIRED_GATES {actual}")
            drift = True

    if not drift:
        rep.ok(f"SC3 REQUIRED_GATES matches spec-derived gate map "
               f"({len(required_gates)} phases)")


# ---------------------------------------------------------------------------
# SC4 — spec/fsm.json constants[]: dereference each pointer against the live
# schema and compare to expected_value.
# ---------------------------------------------------------------------------
def _unescape_token(tok):
    # RFC 6901 JSON Pointer unescaping: ~1 -> "/", ~0 -> "~" (order matters).
    return tok.replace("~1", "/").replace("~0", "~")


def sc4_constants(ctx, rep):
    fsm = ctx.load_json("spec/fsm.json")
    constants = fsm.get("constants", [])

    bad = False
    for c in constants:
        name, ptr, expected = c["name"], c["pointer"], c["expected_value"]
        schema_file, _, json_ptr = ptr.partition("#")
        try:
            schema = ctx.load_json(f"schemas/{schema_file}")
        except Exception as ex:
            rep.fail("SC4", f"bad pointer '{name}': cannot load schema "
                            f"'{schema_file}': {ex}")
            bad = True
            continue

        cur = schema
        resolved = True
        for tok in [_unescape_token(t) for t in json_ptr.split("/") if t != ""]:
            try:
                if isinstance(cur, list):
                    cur = cur[int(tok)]
                elif isinstance(cur, dict):
                    cur = cur[tok]
                else:
                    raise KeyError(tok)
            except (KeyError, IndexError, ValueError):
                rep.fail("SC4", f"bad pointer '{name}': {ptr} does not resolve "
                                f"(stuck at token '{tok}')")
                resolved = False
                bad = True
                break
        if not resolved:
            continue

        if cur != expected:
            rep.fail("SC4", f"stale constant '{name}': pointer {ptr} dereferences "
                            f"to {cur!r} != expected {expected!r}")
            bad = True

    if not bad:
        rep.ok(f"SC4 constants dereference to expected ({len(constants)} constants)")


# ===========================================================================
# U06 additions — SC2 (FSM-table structure diff) + SC5 (example validation).
# APPENDED via the CHECKS registry; U05's core / SC1 / SC3 / SC4 are untouched.
# Both are dev-time, diff-only; every file read routes through ctx.root (U09's
# --root negative fixtures give them teeth). Structure/validation ONLY — SC2
# NEVER compares free-text wording, so prose stays freely editable.
# ===========================================================================

# ---------------------------------------------------------------------------
# SC2 — FSM tables (prose) structurally diffed against spec/fsm.json.
# Compares STRUCTURE ONLY: transition id / from / to / (guard-id where a column
# carries one) / the LT7-sole-back-edge property, plus the SKILL Phase-6
# adjudication rows against the LT3-LT6 outcomes. A cosmetic column/format drift
# is a NOTE; a structural mismatch (missing/duplicate/unknown id, wrong from/to,
# LT7 not the sole back-edge, an adjudication row inconsistent with the LT
# outcomes) is a FAIL naming the id. Robust to **bold**, `backticks`, ->/→, and
# decorated To-cells like "P2_CLARIFICATION (block; ask user)".
# ---------------------------------------------------------------------------
_SC2_ID_RE = re.compile(r"^(?:LT|T)[0-9]+$")


def _md_clean(cell):
    """Strip markdown decoration (**bold**, `code`, *em*) + surrounding space."""
    return cell.replace("**", "").replace("`", "").replace("*", "").strip()


def _iter_md_tables(text):
    """Yield each contiguous pipe-table block as a list of stripped '|...|' rows."""
    block = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|"):
            block.append(s)
        elif block:
            yield block
            block = []
    if block:
        yield block


def _row_cells(row):
    cells = row.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_sep_row(cells):
    return bool(cells) and all(c and set(c) <= set("-: ") for c in cells)


def _extract_state(cell, known):
    """Return the known state a (decorated) cell denotes: prefer a startswith
    match (so 'ESCALATE (->P7)' -> ESCALATE), else a whole-token match. `known`
    is sorted longest-first so 'P6_EXECUTE_VERIFY' wins over 'EXECUTE'."""
    c = _md_clean(cell)
    for st in known:
        if c.startswith(st):
            return st
    for st in known:
        if re.search(r"\b" + re.escape(st) + r"\b", c):
            return st
    return None


def _sc2_transition_table(id_rows, spec, known, loop_idx, rel, rep):
    """Diff one prose transition table (id/from/to + LT7 back-edge) vs spec.
    Returns True on any FAIL (never compares wording)."""
    bad = False
    seen = {}
    is_loop = any(_md_clean(r[0]).startswith("LT") for r in id_rows)
    for r in id_rows:
        tid = _md_clean(r[0])
        seen[tid] = seen.get(tid, 0) + 1
        if tid not in spec:
            rep.fail("SC2", f"{rel}: table id '{tid}' is not a spec/fsm.json transition")
            bad = True
            continue
        exp = spec[tid]
        frm = _extract_state(r[1], known)
        to = _extract_state(r[-1], known)
        if frm != exp["from"]:
            rep.fail("SC2", f"{rel}: {tid} from '{frm}' != spec '{exp['from']}'")
            bad = True
        if to != exp["to"]:
            rep.fail("SC2", f"{rel}: {tid} to '{to}' != spec '{exp['to']}'")
            bad = True

    for tid, n in sorted(seen.items()):
        if n > 1:
            rep.fail("SC2", f"{rel}: transition id '{tid}' appears {n}x (expected once)")
            bad = True

    # Completeness: an LT-table must carry every spec LT id; a T-table every T id.
    expected = {i for i in spec if i.startswith("LT")} if is_loop \
        else {i for i in spec if i.startswith("T")}
    missing = expected - set(seen)
    if missing:
        rep.fail("SC2", f"{rel}: {'LT' if is_loop else 'T'}-table missing spec "
                        f"id(s) {sorted(missing)}")
        bad = True

    # LT7-sole-back-edge (loop tables only): a back-edge is a row whose `to`
    # precedes its `from` in the loop-state ordering. Exactly {LT7} is legal.
    if is_loop:
        back = sorted(
            _md_clean(r[0]) for r in id_rows
            if _md_clean(r[0]) in spec
            and _extract_state(r[1], known) in loop_idx
            and _extract_state(r[-1], known) in loop_idx
            and loop_idx[_extract_state(r[-1], known)] < loop_idx[_extract_state(r[1], known)]
        )
        if back != ["LT7"]:
            rep.fail("SC2", f"{rel}: loop back-edge set {back} != ['LT7'] "
                            f"(LT7 must be the sole back-edge)")
            bad = True
    return bad


def _sc2_adjudication_table(adj_rows, spec, known, rel, rep):
    """SKILL Phase-6 adjudication rows (guard -> target) must be consistent with
    the spec LT3-LT6 outcomes (PASS->DONE=LT3, FAIL&<2->RETRY=LT4,
    FAIL&==2->ESCALATE=LT5, DISAGREE->ESCALATE=LT6). Returns True on any FAIL."""
    bad = False
    mapped = set()
    for r in adj_rows:
        guard = _md_clean(r[0]).lower()
        target = _extract_state(r[1], known)
        if "disagree" in guard:
            lt = "LT6"
        elif "pass" in guard:
            lt = "LT3"
        elif "fail" in guard and ("< 2" in guard or "<2" in guard):
            lt = "LT4"
        elif "fail" in guard and ("== 2" in guard or "==2" in guard):
            lt = "LT5"
        else:
            rep.fail("SC2", f"{rel}: adjudication guard '{_md_clean(r[0])}' maps to "
                            f"no LT3-LT6 outcome")
            bad = True
            continue
        mapped.add(lt)
        exp_to = spec[lt]["to"]
        if target != exp_to:
            rep.fail("SC2", f"{rel}: adjudication '{_md_clean(r[0])}' -> '{target}' "
                            f"inconsistent with {lt} (spec to '{exp_to}')")
            bad = True
    missing = {"LT3", "LT4", "LT5", "LT6"} - mapped
    if missing:
        rep.fail("SC2", f"{rel}: adjudication table missing LT outcome(s) {sorted(missing)}")
        bad = True
    return bad


def sc2_fsm_tables(ctx, rep):
    fsm = ctx.load_json("spec/fsm.json")
    spec = {t["id"]: t for t in fsm["transitions"]}
    known = sorted(set(fsm["states"]) | set(fsm["loop_states"]), key=len, reverse=True)
    loop_idx = {s: i for i, s in enumerate(fsm["loop_states"])}

    failed = False
    # Spec-side sanity: exactly one back_edge in the spec, and it is LT7.
    spec_back = [t["id"] for t in fsm["transitions"] if t.get("back_edge")]
    if spec_back != ["LT7"]:
        rep.fail("SC2", f"spec/fsm.json back_edge set {spec_back} != ['LT7']")
        failed = True

    sources = [
        "references/state-machine.md",       # §2 (T1-T12) + §2a (LT1-LT7)
        "references/self-learning-loops.md",  # §1.3 (LT1-LT7, canonical)
        "SKILL.md",                           # Phase-6 adjudication table
    ]
    n_tables = n_rows = 0
    for rel in sources:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8")
        except Exception as ex:
            rep.fail("SC2", f"cannot read {rel}: {ex}")
            failed = True
            continue
        for block in _iter_md_tables(text):
            rows = [c for c in (_row_cells(r) for r in block) if not _is_sep_row(c)]
            if len(rows) < 2:
                continue
            data = rows[1:]  # drop the header row (wording never compared)
            id_rows = [r for r in data if r and _SC2_ID_RE.match(_md_clean(r[0]))]
            adj_rows = [r for r in data if r and "verdict" in _md_clean(r[0]).lower()
                        and "==" in _md_clean(r[0])]
            if len(id_rows) >= 2:
                n_tables += 1
                n_rows += len(id_rows)
                if _sc2_transition_table(id_rows, spec, known, loop_idx, rel, rep):
                    failed = True
            elif len(adj_rows) >= 2:
                n_tables += 1
                n_rows += len(adj_rows)
                if _sc2_adjudication_table(adj_rows, spec, known, rel, rep):
                    failed = True

    if not failed:
        rep.ok(f"SC2 FSM tables structurally consistent with spec/fsm.json "
               f"({n_tables} tables, {n_rows} rows)")


# ---------------------------------------------------------------------------
# SC5 — embedded/standalone JSON examples validate against their declared schema.
# (1) Fenced ```json/```jsonc example blocks: a fence-adjacent HTML comment
#     `<!-- spec_check: <name>.schema.json -->` declares the schema; jsonc `//`
#     line comments are stripped (string-aware) before json.loads; the instance
#     is validated via ctx.validate against schemas/<name>. An UNDECLARED block
#     is a NOTE (coverage honesty, never FAIL); a declared-but-UNPARSEABLE block
#     is a NOTE (surfaced, not silently skipped); a declared+parseable+INVALID
#     block is a FAIL naming file+schema+first error.
# (2) Standalone template JSONs mapped {file -> schema} for the 2 known N-09
#     artifacts (amendment/persona) — schema-invalid => FAIL naming file+schema.
# ---------------------------------------------------------------------------
_SC5_DECL_RE = re.compile(r"<!--\s*spec_check:\s*([A-Za-z0-9_.\-]+\.schema\.json)\s*-->")
_SC5_STANDALONE = [
    ("templates/amendment.json", "amendment.schema.json"),
    ("templates/persona.json", "persona.schema.json"),
]
# Files scanned for fenced example blocks. templates/*.md carry no json fences
# today (confirmed), but are scanned so a future embedded example is covered.
_SC5_FENCE_SOURCES = ["references/self-learning-loops.md"]


def _strip_jsonc(src):
    """Remove `//` line comments OUTSIDE string literals (jsonc -> json). A `//`
    inside a JSON string (e.g. a URL) is preserved — the scan tracks string +
    escape state so it never truncates a value."""
    out = []
    in_str = esc = False
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _iter_fenced_json(text):
    """Yield (schema_name|None, body, fence_lineno) for each ```json/```jsonc
    fenced block, reading a fence-adjacent `<!-- spec_check: X.schema.json -->`
    comment above the opening fence (skipping blank lines) for the schema."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```") and s[3:].strip().lower() in ("json", "jsonc"):
            open_ln = i
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            schema = None
            j = open_ln - 1
            while j >= 0 and lines[j].strip() == "":
                j -= 1
            if j >= 0:
                m = _SC5_DECL_RE.search(lines[j])
                if m:
                    schema = m.group(1)
            yield schema, "\n".join(body), open_ln + 1
        i += 1


def sc5_examples_validate(ctx, rep):
    failed = False
    n_ok = 0

    # (1) Fenced example blocks (declared -> validate; undeclared/unparseable -> NOTE).
    for rel in _SC5_FENCE_SOURCES:
        try:
            text = (ctx.root / rel).read_text(encoding="utf-8")
        except Exception as ex:
            rep.fail("SC5", f"cannot read {rel}: {ex}")
            failed = True
            continue
        for schema_name, body, ln in _iter_fenced_json(text):
            if schema_name is None:
                rep.note(f"SC5 {rel}:{ln} fenced json block is UNDECLARED "
                         f"(no '<!-- spec_check: <name>.schema.json -->'); not validated")
                continue
            try:
                inst = json.loads(_strip_jsonc(body))
            except Exception as ex:
                rep.note(f"SC5 {rel}:{ln} declared block ({schema_name}) is UNPARSEABLE "
                         f"after // strip: {ex}")
                continue
            try:
                schema = ctx.load_json(f"schemas/{schema_name}")
            except Exception as ex:
                rep.fail("SC5", f"{rel}:{ln} declared schema schemas/{schema_name} "
                                f"cannot be loaded: {ex}")
                failed = True
                continue
            errs = ctx.validate(inst, schema)
            if errs:
                rep.fail("SC5", f"{rel}:{ln} block invalid against {schema_name}: {errs[0]}")
                failed = True
            else:
                n_ok += 1

    # (2) Standalone template JSONs (the illustrative example must obey the schema).
    for rel, schema_name in _SC5_STANDALONE:
        try:
            inst = ctx.load_json(rel)
        except Exception as ex:
            rep.fail("SC5", f"{rel} cannot be loaded/parsed: {ex}")
            failed = True
            continue
        try:
            schema = ctx.load_json(f"schemas/{schema_name}")
        except Exception as ex:
            rep.fail("SC5", f"schema schemas/{schema_name} for {rel} cannot be loaded: {ex}")
            failed = True
            continue
        errs = ctx.validate(inst, schema)
        if errs:
            rep.fail("SC5", f"{rel} invalid against {schema_name}: {errs[0]}")
            failed = True
        else:
            n_ok += 1

    if not failed:
        rep.ok(f"SC5 embedded/standalone examples valid ({n_ok} examples)")


# ===========================================================================
# U07 additions — SC6 (fixture-coverage index) + SC7 (TLA pragma presence).
# APPENDED via the CHECKS registry; U05's core / SC1 / SC3 / SC4 and U06's
# SC2 / SC5 are untouched. Both are dev-time, diff-only; every file read routes
# through ctx.root (U09's --root negative fixtures give SC6 teeth). SC7 is a
# PRESENCE check (pragma coverage) ONLY — it deliberately does NOT verify that a
# tagged TLA action semantically models its transition id.
# ===========================================================================

# ---------------------------------------------------------------------------
# SC6 — fixture-coverage index. Cross-checks the registry's fixtures[] paths
# against the on-disk scripts/tests/ dirs (forward, FAIL) and against the
# expectations.tsv fixture list (reverse, NOTE). A broad expectations fixture
# (good/bad/…) that no invariant claims is a NOTE, never a FAIL; a registry
# fixture with no dir on disk is a FAIL naming the entry; and if the registry
# carries NO fixtures[] at all the mapping is absent (FAIL — never a vacuous pass).
# ---------------------------------------------------------------------------
def _read_expectations_fixtures(ctx):
    """Return col-1 fixture paths from scripts/tests/expectations.tsv (comments/
    blank lines skipped; sub-dir paths like 'p4_advisory/regrounded_required' kept),
    or None if the file cannot be read."""
    path = ctx.root / "scripts" / "tests" / "expectations.tsv"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        col1 = line.split("\t")[0].strip()
        if col1:
            out.append(col1)
    return out


def sc6_fixture_coverage(ctx, rep):
    reg = ctx.load_json("spec/invariants.json")
    entries = reg["entries"]
    tests_dir = ctx.root / "scripts" / "tests"

    # Registry fixtures: path -> list of entry ids that reference it.
    registry_fixtures = {}
    for e in entries:
        for fx in e.get("fixtures", []) or []:
            registry_fixtures.setdefault(fx, []).append(e["id"])

    # mapping-absence (FAIL): a registry with NO fixtures[] anywhere maps nothing —
    # a silent pass would hide that the whole coverage index is empty.
    if not registry_fixtures:
        rep.fail("SC6", "fixture-coverage mapping absent")
        return

    expectations = _read_expectations_fixtures(ctx)
    if expectations is None:
        rep.fail("SC6", "cannot read scripts/tests/expectations.tsv")
        return

    failed = False

    # FORWARD (teeth, FAIL): every registry fixtures[] path must exist as a dir.
    on_disk = 0
    for fx in sorted(registry_fixtures):
        if (tests_dir / fx).is_dir():
            on_disk += 1
        else:
            for eid in registry_fixtures[fx]:
                rep.fail("SC6", f"registry fixture '{fx}' (entry {eid}) not on disk")
            failed = True

    # REVERSE (NOTE): every expectations.tsv fixture referenced by >=1 registry
    # entry. Unreferenced is advisory only (broad good/bad fixtures need no 1:1 map).
    reg_set = set(registry_fixtures)
    mapped = 0
    for d in expectations:
        if d in reg_set:
            mapped += 1
        else:
            rep.note(f"SC6 fixture '{d}' unmapped to any invariant")

    if not failed:
        rep.ok(f"SC6 fixture coverage ({on_disk} registry fixtures on disk, "
               f"{mapped}/{len(expectations)} expectations mapped)")


# ---------------------------------------------------------------------------
# SC7 — TLA cross-check LITE (presence only). Greps formal/Pipeline.tla for the
# comment-only `\* spec: <id>` pragmas and confirms every transition id in
# {T1..T12, LT1..LT7} appears in some pragma. This is PRESENCE checking (pragma
# coverage) — it asserts a human tagged each modeled action, NOT that the action
# semantically implements that transition (that is TLC's job, not a grep's). The
# disclaimer below is printed on every run so the guarantee is never overclaimed.
# ---------------------------------------------------------------------------
_SC7_PRAGMA = "\\* spec:"
_SC7_UNMODELED_PRAGMA = "\\* spec-unmodeled:"   # D12: ids tagged on a COMMENT / intentionally unmodeled
_SC7_ID_RE = re.compile(r"\b(?:LT|T)[0-9]+\b")


def sc7_tla_pragmas(ctx, rep):
    # Honesty guardrail: state the LIMITATION of this check up front, every run.
    print("  SC7 is presence-checking (pragma coverage), NOT semantic verification.")

    rel = "formal/Pipeline.tla"
    try:
        text = (ctx.root / rel).read_text(encoding="utf-8")
    except Exception as ex:
        rep.fail("SC7", f"cannot read {rel}: {ex}")
        return

    # D12: two pragma forms. `\* spec:` tags an id realized by a modeled action; `\* spec-unmodeled:`
    # tags an id that is DELIBERATELY not a modeled action (an unfair self-loop, or the BGA `Amend`
    # re-arm that the model abstracts). Coverage is satisfied by EITHER form; the unmodeled ids are
    # reported separately so "presence" no longer masks "tagged a comment, not an action" (the old drift).
    modeled = set()
    unmodeled = set()
    for line in text.splitlines():
        uidx = line.find(_SC7_UNMODELED_PRAGMA)
        if uidx != -1:                                  # spec-unmodeled is NOT a substring of spec:
            unmodeled.update(_SC7_ID_RE.findall(line[uidx + len(_SC7_UNMODELED_PRAGMA):]))
            continue
        idx = line.find(_SC7_PRAGMA)
        if idx == -1:
            continue
        modeled.update(_SC7_ID_RE.findall(line[idx + len(_SC7_PRAGMA):]))

    found = modeled | unmodeled
    expected = {f"T{i}" for i in range(1, 13)} | {f"LT{i}" for i in range(1, 8)}
    missing = sorted(expected - found, key=lambda s: (s.startswith("LT"), int(s.lstrip("LT"))))
    if missing:
        for mid in missing:
            rep.fail("SC7", f"missing pragma for {mid}")
        return

    if unmodeled:
        print("  SC7 intentionally-unmodeled (\\* spec-unmodeled:) ids: "
              + ", ".join(sorted(unmodeled, key=lambda s: (s.startswith("LT"), int(s.lstrip("LT"))))))
    rep.ok(f"SC7 all T*/LT* ids present as \\* spec:/spec-unmodeled: pragmas "
           f"({len(modeled)} modeled, {len(unmodeled)} unmodeled; presence-check only)")


# ---------------------------------------------------------------------------
# CHECKS registry — EXTENSION POINT.
# Order here == order of output. Each entry is (display_name, fn(ctx, rep)).
#   * U06 appended SC2 and SC5 (registered in numeric order below).
#   * U07 appended SC6 and SC7 (registered below).
# Add checks by defining `def scN_<name>(ctx, rep):` above and appending the tuple.
# ---------------------------------------------------------------------------
CHECKS = [
    ("SC1", sc1_registry_labels),
    ("SC2", sc2_fsm_tables),
    ("SC3", sc3_required_gates),
    ("SC4", sc4_constants),
    ("SC5", sc5_examples_validate),
    ("SC6", sc6_fixture_coverage),
    ("SC7", sc7_tla_pragmas),
    # --- U06 (DONE): SC2 + SC5 registered above (numeric order) ---
    # --- U07 (DONE): SC6 + SC7 registered above ---
]


# ---------------------------------------------------------------------------
# Harness core.
# ---------------------------------------------------------------------------
def build_ctx(root):
    # Import validate_run from THIS script's own scripts dir (not from --root), so
    # LABELS/make_validator come from the installed validator. main() is
    # __main__-guarded, so this import runs NO validation.
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import validate_run as V
    validate, backend = V.make_validator()
    return Ctx(root, V, validate, backend)


def run(root, quiet=False):
    ctx = build_ctx(root)
    rep = Report(quiet=quiet)
    if not quiet:
        print(f"spec_check — dev-time prose<->spec<->code drift checker  ·  "
              f"root: {root}  ·  schema backend: {ctx.backend}")
    for name, fn in CHECKS:
        try:
            fn(ctx, rep)
        except Exception as ex:
            # Fail closed: an unexpected crash in a check is a FAIL, never a silent pass.
            rep.fail(name, f"check raised {type(ex).__name__}: {ex}")
    return rep.summary()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Dev-time prose<->spec<->code drift checker (SC1/SC3/SC4).")
    ap.add_argument("--quiet", action="store_true",
                    help="print only NOTE/FAIL lines + RESULT summary")
    ap.add_argument("--root", default=None,
                    help="skill-dir root all file reads resolve against "
                         "(default: this script's skill dir)")
    args = ap.parse_args(argv)
    root = (Path(args.root).resolve() if args.root
            else Path(__file__).resolve().parent.parent)
    return run(root, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
