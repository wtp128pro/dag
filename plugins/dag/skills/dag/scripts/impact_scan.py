#!/usr/bin/env python3
"""impact_scan.py — out-of-frame consumers of what a unit changed (dag blast radius).

Usage:
  impact_scan.py <RUN_DIR> --unit U [--config C] [--workspace W]   scan; write units/<U>/impact.json + .sha256
  impact_scan.py <RUN_DIR> --unit U ... --preview                   same scan; print exactly that JSON; write nothing
  impact_scan.py <RUN_DIR> --unit U ... --predict                   known users of the PLANNED frame (no footprint)
  impact_scan.py --self-test                                        synthetic git repos; one line per case

Inputs (all runtime): the run's units/<U>/footprint.json (written by footprint.py), graph.json (the unit's
frame.modifies; units/<U>/brief.json `frame` as a fallback), the working repository, and a blast config
resolved as: --config, else <RUN_DIR>/blast-config.json, else <workspace>/.dag/blast.json, else built-in
defaults (no coupling rules, scan_excludes [".wip/**"]).

Contract restated (footprint.json, mode git|snapshot|none):
  * BEFORE content of a change: git mode `git cat-file blob <base_ref>:<path>` (from_path for a rename); base_ref
    is the PRE tree footprint.py recorded at wave start (HEAD + working tree), so a file already dirty when the
    wave began is diffed against its pre-wave content, never against HEAD. Snapshot mode: the content store
    <RUN_DIR>/blast/objects/<sha256_before>. The bytes must hash to sha256_before.
  * AFTER content: the file in the scanned workspace (snapshot mode: the content store as a second source);
    the bytes must hash to sha256_after. A missing blob or a hash mismatch is never skipped silently: it becomes
    a `scan-error` symbol plus a reference obligation naming it, and the exit status is 1.
Extractors (the extractor is chosen once per file, from its path and the first non-empty side's shebang, and
applied to both sides):
  * Python via ast: removed/renamed top-level functions, classes and methods; changed signatures; removed or
    changed module constants (`_*UPPER_CASE` names, so PEP 8 private constants count); a single-line string literal
    (3+ chars, one alphanumeric) of a module constant's value whose text is no longer an exact str literal
    (ast.Constant, whole module; equality, never a substring) in the AFTER content of ANY changed Python file (.py
    or python shebang) of the footprint (`string`, qual = the text): a renamed label stem is searched for as text,
    so a table that pins the old stem is reached. Covered, i.e. no literal is reported while the table's own name
    stays a changed name: renaming the table's binding to any name (UPPER or lower case), moving a literal between
    constants, wrapping the table in a function, moving the table into another changed Python file. Not covered: a
    table moved into a non-Python file (each literal is reported), and a literal changed in the table whose old text
    is still an identical literal elsewhere in a changed Python file (not reported); removed/renamed other
    module-level assignment targets of 3+ chars (`variable`; a value change of such a binding is not reported);
    argparse option strings. A renamed or deleted .py file also yields its import name (`module`: the stem, or
    the package directory for __init__.py) next to its `file` symbol (basename).
  * JSON schema: `properties` keys and `enum` values, each keyed by its location (JSON pointer, list indices
    collapsed to `*`), so a key removed from one object is reported although it survives in another. A .json
    file with no `properties`/`enum` on either side is not a schema and goes to the fallback.
  * Markdown headings, ATX and setext (a YAML front-matter block at the top is skipped; fenced code ignored).
  * Shell functions.
  * Fallback, for every other file and for any side that fails to parse under the chosen extractor:
    identifiers (3+ chars) present on removed lines and absent from every added line, string escapes blanked first
    (hex forms everywhere; `\\\\` and one-letter forms such as `\\n` in .json files and double-quoted spans only). An
    identifier that also survives on an UNCHANGED line is still reported.
Added names alone never create an obligation. Not extracted (by design): Markdown body text, names a Python
module only imports or binds inside an if/try block, JSON keys of a schema beyond `properties`/`enum`.
Search: git mode `git grep -n -I -z -w -F --untracked -e <name>` (tracked + untracked; ignored files stay
invisible; rc 1 = no hit; any other failure is recorded); snapshot mode a Python walk with the same whole-word
fixed-string rule. Every hit path is filtered with frame_match against the unit's frame.modifies, the config's
scan_excludes, `.wip/**` and the run directory. One obligation per changed NAME (never per hit): hit_count =
every counted hit, sample_hits capped, referencing_paths sorted/deduped/capped, obligations capped, the rest
counted in truncated_hits. Coupling: a footprint path matching a rule's when_paths raises a coupling obligation
unless the footprint also touches one of require.touch_any (a require.command rule always raises it).
Output is sorted and serialised with sorted keys, so the same inputs give the same bytes.

Exit status: 0 = done, no scan errors; 1 = impact JSON written (or, with --preview, printed) but scan errors
were recorded in it, or a --self-test case failed; 2 = fatal, nothing written (unreadable or malformed
footprint.json — including a changes[] path or from_path that is unsafe per frame_match.is_unsafe_path (absolute,
a '..' component, a NUL, empty), refused before any file is read — malformed blast config, no frame for the unit,
git failure resolving the workspace).
--self-test builds throwaway git repos (commit identity passed with -c, so it runs under an empty HOME), prints
one line per case, `case <rule> pos|neg ok|FAIL`, and exits 0 iff every case is ok.
"""
import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_match  # noqa: E402  (the single path matcher; no copy of it lives here)
import footprint  # noqa: E402  (workspace resolution, git runner, exclude logic, file walk)

VERSION = "impact_scan.py/1"
CAPS = {"sample_hits": 5, "referencing_paths": 50, "obligations": 200}
EXTRACTORS = ["argparse", "fallback-identifiers", "json-schema", "markdown-headings", "python-ast", "shell-functions"]
DEFAULT_CONFIG = {"coupling_rules": [], "scan_excludes": [".wip/**"]}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
# M2: #30 55d1c73 and #37 49c9bb5 - a reworded JSON prose string reported its `\u2014` escape as the
# identifier `u2014` (105 / 108 out-of-frame hits, all other JSON escapes). The fallback blanks string escapes
# before it tokenises, on both sides alike: the hex forms (HEX_ESCAPE) everywhere; an escaped backslash and the
# one-letter forms only in a .json file or inside a double-quoted span (ESCAPE), so `"\nold_name"` yields `old_name`
# while an unquoted Windows path `C:\tools` still yields `tools` (single quotes are literal in YAML, TOML and shell).
HEX_ESCAPE = re.compile(r"\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|x[0-9A-Fa-f]{2})")
ESCAPE = re.compile(r"\\(?:\\|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|x[0-9A-Fa-f]{2}|[abfnrtv])")
DQUOTED = re.compile(r'"(?:[^"\\\n]|\\.)*"')
CONST = re.compile(r"^_*[A-Z][A-Z0-9_]*$")
MD_HEAD = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
MD_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
MD_NOT_PARA = re.compile(r"^(?: {4}|\t| {0,3}(?:[>#|<]|[-+*](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$)))")
SH_FUNC = re.compile(r"^\s*(?:function\s+([A-Za-z_][\w:.-]*)\s*(?:\(\s*\))?|([A-Za-z_][\w:.-]*)\s*\(\s*\))\s*\{?")


class ScanError(Exception):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _text(data):
    return None if data is None or b"\0" in data[:8000] else data.decode("utf-8", "replace")


def _dump(obj):
    return (json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


# --- extractors: text -> {(kind, name, qual): signature} ------------------------------------------------------
def _py_defs(text):
    tree = ast.parse(text)
    out = {}

    def fn_sig(node):
        return ast.dump(node.args)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[("function", node.name, node.name)] = (fn_sig(node), ast.dump(ast.Module(body=node.body, type_ignores=[])))
        elif isinstance(node, ast.ClassDef):
            out[("class", node.name, node.name)] = (ast.dump(ast.Tuple(elts=node.bases, ctx=ast.Load())), "")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[("method", sub.name, node.name + "." + sub.name)] = (fn_sig(sub), ast.dump(ast.Module(body=sub.body, type_ignores=[])))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]:
                if not isinstance(t, ast.Name):
                    continue
                if CONST.match(t.id):
                    out[("constant", t.id, t.id)] = (ast.dump(node.value) if node.value is not None else "", "")
                    # keyed by the TEXT alone (union over the file's constants): renaming a constant or moving a
                    # literal between constants changes no key; scan() then also drops a text that is still an exact
                    # str literal anywhere in a changed Python file's after side (_str_literals)
                    for lit in sorted({c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant)
                                       and isinstance(c.value, str)} if node.value is not None else ()):
                        if len(lit) >= 3 and lit.isprintable() and any(ch.isalnum() for ch in lit):
                            out[("string", lit, lit)] = ("", "")
                elif len(t.id) >= 3:  # other module-level binding: reported when it disappears, not on a value change
                    out[("variable", t.id, t.id)] = ("", "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("-"):
                    out[("cli-flag", a.value, a.value)] = ("", "")
    return out


def _json_defs(text):
    """Schema keys and enum values keyed by location: a JSON pointer whose list indices are collapsed to `*`
    (so inserting an allOf member does not make every later key look removed)."""
    out = {}

    def esc(k):
        return str(k).replace("~", "~0").replace("/", "~1")

    def walk(o, ptr):
        if isinstance(o, dict):
            if isinstance(o.get("properties"), dict):
                for k in o["properties"]:
                    if str(k).strip():
                        out[("schema-key", k, ptr + "/properties/" + esc(k))] = ("", "")
            if isinstance(o.get("enum"), list):
                for v in o["enum"]:
                    if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
                        out[("enum-value", str(v), ptr + "/enum/" + esc(v))] = ("", "")
            for k, v in o.items():
                walk(v, ptr + "/" + esc(k))
        elif isinstance(o, list):
            for v in o:
                walk(v, ptr + "/*")
    walk(json.loads(text), "")
    return out


def _md_defs(text):
    """ATX and setext headings outside fenced code; a leading YAML front-matter block is skipped."""
    out, fence, prev = {}, None, ""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].rstrip() == "---":
        start = next((i + 1 for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), 0)
    for line in lines[start:]:
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = None if fence and s.startswith(fence) else (fence or s[:3])
            prev = ""
            continue
        if fence:
            continue
        m = MD_HEAD.match(line)
        name = m.group(1) if m else (prev if prev and MD_SETEXT.match(line) else None)
        if name:
            out[("heading", name, name)] = ("", "")
        prev = "" if name or not line.strip() or MD_NOT_PARA.match(line) else line.strip()
    return out


def _sh_defs(text):
    out = {}
    for line in text.splitlines():
        m = SH_FUNC.match(line)
        if m and (m.group(1) or m.group(2)) not in ("if", "then", "while", "for", "case"):
            name = m.group(1) or m.group(2)
            out[("shell-function", name, name)] = ("", "")
    return out


def _extractor(path, text):
    """(extractor name, defs function) for a file type we understand; None when no structured extractor applies.
    The defs function raises ValueError/SyntaxError/RecursionError on a parse failure (the caller falls back)."""
    low = path.lower()
    first = text.split("\n", 1)[0] if text.startswith("#!") else ""
    if low.endswith(".py") or "python" in first:
        return "python-ast", _py_defs
    if low.endswith(".json"):
        return "json-schema", _json_defs
    if low.endswith((".md", ".markdown")):
        return "markdown-headings", _md_defs
    if low.endswith((".sh", ".bash")) or re.search(r"\b(ba|z|k)?sh\b", first):
        return "shell-functions", _sh_defs
    return None


def _structured(path, text):
    """(extractor name, defs) for one text; None when no structured extractor applies."""
    ex = _extractor(path, text)
    return None if ex is None else (ex[0], ex[1](text))


def _unescape(text, path):
    """Blank string escapes, which are text, not names: `\\u2014`, `\\U0001F600`, `\\x41` everywhere; `\\\\` and
    `\\n`-style one-letter escapes only in a .json file or inside a double-quoted span (see the M2 note at ESCAPE)."""
    if path.lower().endswith(".json"):
        return ESCAPE.sub(" ", text)
    return HEX_ESCAPE.sub(" ", DQUOTED.sub(lambda m: ESCAPE.sub(" ", m.group(0)), text))


def _fallback(before, after, path=""):
    """Identifiers (3+ chars) present on a removed line and absent from every added line, after _unescape."""
    rem, add = [], []
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("-") and not line.startswith("---"):
            rem.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            add.append(line[1:])
    words = lambda lines: set(IDENT.findall(_unescape("\n".join(lines), path)))
    return sorted(words(rem) - words(add))


def extract(path, before, after):
    """Changed names of one file: [(kind, name, qual, change)]. before/after are str ('' when absent).
    One extractor, chosen from the path and the first non-empty side, parses both sides; if either side
    fails to parse under it (e.g. a shebang that changes language), the whole file goes to the fallback."""
    ex = _extractor(path, before or after)
    try:
        if ex is not None:
            kind_of, defs = ex
            b = defs(before) if before else {}
            a = defs(after) if after else {}
            if kind_of == "json-schema" and not b and not a:
                raise ValueError("no JSON-schema keywords on either side: not a schema")
            out = []
            gone = [k for k in b if k not in a]
            new_bodies = {(k[0], a[k][1]) for k in a if k not in b and a[k][1]}
            for k in sorted(b):
                if k in a:
                    if b[k][0] != a[k][0]:
                        out.append((k[0], k[1], k[2], "signature-changed" if k[0] in ("function", "method", "class") else "modified"))
                    continue
                same_kind_gone = [g for g in gone if g[0] == k[0]]
                same_kind_new = [n for n in a if n not in b and n[0] == k[0]]
                renamed = (b[k][1] and (k[0], b[k][1]) in new_bodies) or (len(same_kind_gone) == 1 and len(same_kind_new) == 1)
                out.append((k[0], k[1], k[2], "renamed" if renamed else "removed"))
            return kind_of, out
    except (SyntaxError, ValueError, RecursionError):
        pass
    return "fallback-identifiers", [("identifier", n, n, "removed") for n in _fallback(before or "", after or "", path)]


# --- content access -------------------------------------------------------------------------------------------
def _before_bytes(run_dir, ws, fp, ch):
    want = ch["sha256_before"]
    if want is None:
        return None
    src = ch["from_path"] or ch["path"]
    if fp["mode"] == "git":
        try:
            data = footprint.git(ws, ["cat-file", "blob", "%s:%s" % (fp["base_ref"], src)])
        except footprint.CaptureError as exc:
            raise ScanError("before content of %s unreadable: %s" % (src, exc))
    else:
        try:
            with open(os.path.join(run_dir, "blast", "objects", want), "rb") as fh:
                data = fh.read()
        except OSError:
            raise ScanError("before content of %s missing from the content store" % src)
    if _sha(data) != want:
        raise ScanError("before content of %s does not hash to sha256_before" % src)
    return data


def _after_bytes(run_dir, ws, fp, ch):
    want = ch["sha256_after"]
    if want is None:
        return None
    cands = [os.path.join(ws, ch["path"])]
    if fp["mode"] == "snapshot":
        cands.append(os.path.join(run_dir, "blast", "objects", want))
    for c in cands:
        try:
            with open(c, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if _sha(data) == want:
            return data
    raise ScanError("after content of %s missing or does not hash to sha256_after" % ch["path"])


# --- search ---------------------------------------------------------------------------------------------------
def _word_hit(line, name):
    i = line.find(name)
    while i >= 0:
        pre = line[i - 1] if i else " "
        j = i + len(name)
        post = line[j] if j < len(line) else " "
        if not (pre.isalnum() or pre == "_") and not (post.isalnum() or post == "_"):
            return True
        i = line.find(name, i + 1)
    return False


def search(ws, mode, name, skip, run_dir):
    """All (path, line_no, text) hits of `name` as a whole word, minus paths matching `skip`. Sorted.
    Directory-shaped skip patterns (`D/**`, D free of glob characters) are also handed to git grep as
    `:(exclude,literal)D` pathspecs, so those trees are not read at all; frame_match stays the authoritative
    post-filter for every pattern."""
    hits = []
    if mode == "git":
        args = ["grep", "-n", "-I", "-z", "-w", "-F", "--untracked", "-e", name, "--", "."]
        dirs = footprint._exclude_dirs(footprint.exclude_patterns(ws, run_dir))
        dirs += [d for d in footprint._exclude_dirs(skip) if d not in dirs and not re.search(r"[][*?{}\\]", d)]
        args += [":(exclude,literal)" + d for d in dirs]
        env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
        try:
            cp = subprocess.run(["git"] + args, cwd=ws, env=env, capture_output=True, stdin=subprocess.DEVNULL,
                                timeout=footprint.git_timeout())
        except (OSError, subprocess.SubprocessError, footprint.CaptureError) as exc:
            raise ScanError("git grep for %r failed (%s)" % (name, type(exc).__name__))
        if cp.returncode == 1:
            return []
        if cp.returncode != 0:
            raise ScanError("git grep for %r failed (rc %d)" % (name, cp.returncode))
        for rec in cp.stdout.split(b"\n"):
            parts = rec.split(b"\0", 2)
            if len(parts) == 3:
                hits.append((footprint._decode(parts[0]), int(parts[1]), parts[2].decode("utf-8", "replace")))
    else:
        for rel in footprint.walk_files(ws, list(skip)):  # skip already holds .wip/** and the run dir
            try:
                with open(os.path.join(ws, rel), "rb") as fh:
                    text = _text(fh.read())
            except OSError:
                continue
            for n, line in enumerate((text or "").split("\n"), 1):
                if name in line and _word_hit(line, name):
                    hits.append((rel, n, line))
    return sorted(h for h in hits if not frame_match.match_any_pattern(h[0], skip))


# --- run-dir inputs -------------------------------------------------------------------------------------------
def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def frame_modifies(run_dir, unit):
    try:
        for u in _load_json(os.path.join(run_dir, "graph.json")).get("units", []):
            if u.get("id") == unit:
                return list((u.get("frame") or {}).get("modifies") or [])
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return list((_load_json(os.path.join(run_dir, "units", unit, "brief.json")).get("frame") or {}).get("modifies") or [])
    except (OSError, ValueError, AttributeError):
        raise ScanError("no frame.modifies for %s in graph.json or units/%s/brief.json" % (unit, unit))


def _strs(v, nonempty=False):
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v) and bool(v or not nonempty)


def _check_config(cfg, where):
    """Reject the shapes the scanner would crash on (the blast-config schema's rules for the keys it reads)."""
    if not isinstance(cfg, dict):
        raise ScanError("blast config %s is not a JSON object" % where)
    if not _strs(cfg.get("scan_excludes", [])):
        raise ScanError("blast config %s: scan_excludes must be a list of non-empty strings" % where)
    rules = cfg.get("coupling_rules", [])
    if not isinstance(rules, list):
        raise ScanError("blast config %s: coupling_rules must be a list" % where)
    seen = set()
    for i, r in enumerate(rules):
        req = r.get("require") if isinstance(r, dict) else None
        ok = isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"] and r["id"] not in seen \
            and _strs(r.get("when_paths"), True) and isinstance(req, dict) and ("command" in req) != ("touch_any" in req) \
            and (_strs(req["touch_any"], True) if "touch_any" in req else isinstance(req["command"], str) and req["command"].strip())
        if not ok:
            raise ScanError("blast config %s: coupling_rules[%d] needs a unique non-empty id, a non-empty when_paths list "
                            "and a require object with exactly one of command / touch_any" % (where, i))
        seen.add(r["id"])


def _check_footprint(fp, unit):
    keys = ("path", "status", "from_path", "sha256_before", "sha256_after")
    chs = (fp.get("changes") or []) if isinstance(fp, dict) else None
    if not isinstance(chs, list) or not all(isinstance(c, dict) and all(k in c for k in keys)
                                            and isinstance(c["path"], str) and c["path"] for c in chs):
        raise ScanError("units/%s/footprint.json malformed: changes[] must hold objects with %s" % (unit, ", ".join(keys)))
    for c in chs:  # before ANY read: an absolute or '..' path would be read from outside the workspace
        for key in ("path", "from_path"):
            if (c[key] is not None or key == "path") and (not isinstance(c[key], str) or frame_match.is_unsafe_path(c[key])):
                raise ScanError("units/%s/footprint.json: unsafe changes[].%s %r refused before any read" % (unit, key, c[key]))


def load_config(run_dir, ws, explicit):
    for p in ([explicit] if explicit else [os.path.join(run_dir, "blast-config.json"), os.path.join(ws, ".dag", "blast.json")]):
        if explicit or os.path.isfile(p):
            try:
                cfg = _load_json(p)
            except (OSError, ValueError) as exc:
                raise ScanError("blast config %s unreadable (%s)" % (p, type(exc).__name__))
            break
    else:
        cfg, p = DEFAULT_CONFIG, "(built-in defaults)"
    _check_config(cfg, p)
    pats = list(cfg.get("scan_excludes") or [])
    for rule in cfg.get("coupling_rules") or []:
        pats += list(rule.get("when_paths") or []) + list((rule.get("require") or {}).get("touch_any") or [])
    bad = [p for p in pats if not frame_match.is_valid_pattern(p)]
    if bad:
        raise ScanError("blast config has invalid path patterns: %r" % bad)
    return cfg


def _skip(run_dir, ws, frame, cfg):
    return list(frame) + list(cfg.get("scan_excludes") or []) + footprint.exclude_patterns(ws, run_dir)


def _str_literals(texts):
    """Every str literal (ast.Constant, whole module) of the given Python texts, compared by exact equality, never
    as a substring (a surviving 'N-I9 stem' must not hide a removed 'I9 stem'). A text that does not parse adds none."""
    out = set()
    for t in texts:
        try:
            out |= {c.value for c in ast.walk(ast.parse(t)) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        except (SyntaxError, ValueError, RecursionError):
            pass
    return out


def _module_name(path):
    """Import name a .py path provides: its stem, or the package directory for pkg/__init__.py; else None."""
    parts = path[:-3].split("/") if path.endswith(".py") else []
    name = (parts[-2] if len(parts) > 1 else "") if parts[-1:] == ["__init__"] else (parts[-1] if parts else "")
    return name if name.isidentifier() else None


# --- scan -----------------------------------------------------------------------------------------------------
def scan(run_dir, unit, config=None, workspace=None):
    """Return (impact document, error list). Pure apart from git reads; writes nothing."""
    run_dir = os.path.realpath(run_dir)
    fpath = os.path.join(run_dir, "units", unit, "footprint.json")
    try:
        with open(fpath, "rb") as fh:
            raw = fh.read()
        fp = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ScanError("units/%s/footprint.json unreadable (%s)" % (unit, type(exc).__name__))
    _check_footprint(fp, unit)
    ws = os.path.realpath(workspace) if workspace else footprint.resolve_workspace(run_dir)[0]
    cfg = load_config(run_dir, ws, config)
    skip = _skip(run_dir, ws, frame_modifies(run_dir, unit), cfg)
    symbols, errors, py_after = [], [], []
    if fp.get("capture_error"):
        errors.append(("footprint.json", "capture_error: %s" % fp["capture_error"]))
    for ch in sorted(fp.get("changes") or [], key=lambda c: c["path"]):
        try:
            b, a = _before_bytes(run_dir, ws, fp, ch), _after_bytes(run_dir, ws, fp, ch)
        except ScanError as exc:
            errors.append((ch["path"], str(exc)))
            continue
        tb, ta = _text(b), _text(a)
        if ta and (_extractor(ch["path"], ta) or ("",))[0] == "python-ast":
            py_after.append(ta)
        src = ch["from_path"] or ch["path"]
        names = []
        if not ((b is not None and tb is None) or (a is not None and ta is None)):  # binary content: no names
            try:
                names = extract(src, tb or "", ta or "")[1]
            except Exception as exc:  # an extractor defect is a recorded scan error, never a traceback
                errors.append((ch["path"], "extracting names from %s failed (%s)" % (src, type(exc).__name__)))
        if ch["status"] in ("D", "R"):
            change = "removed" if ch["status"] == "D" else "renamed"
            names.append(("file", os.path.basename(src), src, change))
            if _module_name(src):
                names.append(("module", _module_name(src), src, change))
        for kind, name, qual, change in names:
            symbols.append({"id": "%s#%s:%s" % (src, kind, qual), "name": name, "kind": kind, "change": change, "source_path": src})
    if any(s["kind"] == "string" for s in symbols):  # a literal still present in the after side has not left
        kept = _str_literals(py_after)
        symbols = [s for s in symbols if s["kind"] != "string" or s["name"] not in kept]
    by_name = {}
    for s in symbols:
        by_name.setdefault(s["name"], []).append(s["id"])
    refs = []
    for name in sorted(by_name):
        try:
            hits = search(ws, fp.get("mode"), name, skip, run_dir)
        except ScanError as exc:
            errors.append((name, str(exc)))
            continue
        if hits:
            paths = sorted({h[0] for h in hits})
            refs.append({"id": "ref:" + name, "kind": "reference", "symbol_ids": sorted(set(by_name[name])), "rule_id": None,
                         "referencing_paths": paths[:CAPS["referencing_paths"]], "hit_count": len(hits),
                         "sample_hits": ["%s:%d:%s" % (p, n, t.strip()[:200]) for p, n, t in hits[:CAPS["sample_hits"]]]})
    for where, why in sorted(errors):
        sid = "%s#scan-error" % where
        symbols.append({"id": sid, "name": where, "kind": "scan-error", "change": why, "source_path": where})
        refs.append({"id": "error:" + where, "kind": "reference", "symbol_ids": [sid], "rule_id": None,
                     "referencing_paths": [], "hit_count": 0, "sample_hits": [why]})
    touched = sorted({p for c in fp.get("changes") or [] for p in (c["path"], c["from_path"]) if p})
    coupling = []
    for rule in sorted(cfg.get("coupling_rules") or [], key=lambda r: r["id"]):
        trig = [p for p in touched if frame_match.match_any_pattern(p, rule["when_paths"])]
        req = rule.get("require") or {}
        if not trig or ("touch_any" in req and any(frame_match.match_any_pattern(p, req["touch_any"]) for p in touched)):
            continue
        need = ("touch one of: " + ", ".join(req["touch_any"])) if "touch_any" in req else ("run: " + req.get("command", ""))
        coupling.append({"id": "coupling:" + rule["id"], "kind": "coupling", "symbol_ids": [], "rule_id": rule["id"],
                         "referencing_paths": trig[:CAPS["referencing_paths"]], "hit_count": len(trig), "sample_hits": [need]})
    keep = sorted(refs, key=lambda o: (o["id"].startswith("ref:"), -o["hit_count"], o["id"]))[:CAPS["obligations"]]
    dropped = [o for o in refs if o not in keep]
    truncated = sum(o["hit_count"] - len(o["sample_hits"]) for o in keep if o["kind"] == "reference" and o["hit_count"]) \
        + sum(o["hit_count"] for o in dropped)
    doc = {"unit_id": unit, "iteration": int(fp.get("iteration") or 1), "footprint_sha256": _sha(raw),
           "symbols": sorted(symbols, key=lambda s: s["id"]),
           "obligations": sorted(keep + coupling, key=lambda o: (o["kind"], o["id"])),
           "truncated_hits": truncated, "caps": dict(CAPS),
           "scanner": {"version": VERSION, "extractors": list(EXTRACTORS)}}
    return doc, errors


def write_impact(run_dir, unit, doc):
    data = _dump(doc)
    ud = os.path.join(os.path.realpath(run_dir), "units", unit)
    footprint._atomic_write(os.path.join(ud, "impact.json"), data)
    footprint._atomic_write(os.path.join(ud, "impact.json.sha256"), ("%s  impact.json\n" % _sha(data)).encode())
    return data


# --- predict --------------------------------------------------------------------------------------------------
def predict(run_dir, unit, config=None, workspace=None):
    """Known users of the names the planned frame DEFINES: file and module names plus the structured extractors'
    names, except methods and `string` literals (data, not definitions; a large constant table would otherwise
    fill the consumer cap and push the frame's function and flag consumers out)."""
    run_dir = os.path.realpath(run_dir)
    ws, mode = footprint.resolve_workspace(run_dir)
    ws = os.path.realpath(workspace) if workspace else ws
    cfg = load_config(run_dir, ws, config)
    frame = frame_modifies(run_dir, unit)
    skip = _skip(run_dir, ws, frame, cfg)
    if mode == "git":
        raw = footprint.git(ws, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        files = sorted({footprint._decode(p) for p in raw.split(b"\0") if p})
    else:
        files = footprint.walk_files(ws, footprint.exclude_patterns(ws, run_dir))
    names = {}
    for rel in files:
        if not frame_match.match_any_pattern(rel, frame) or not os.path.isfile(os.path.join(ws, rel)):
            continue
        with open(os.path.join(ws, rel), "rb") as fh:
            text = _text(fh.read())
        found = {os.path.basename(rel)}
        if rel.endswith(".py"):
            found.add(os.path.basename(rel)[:-3])
        try:
            st = _structured(rel, text or "") if text else None
            found |= {k[1] for k in (st[1] if st else {}) if k[0] not in ("method", "string")}
        except (SyntaxError, ValueError, RecursionError):
            pass
        for n in found:
            if len(n) >= 3:
                names.setdefault(n, rel)
    consumers = []
    for n in sorted(names):
        hits = search(ws, mode, n, skip, run_dir)
        if hits:
            consumers.append({"name": n, "source_path": names[n], "hit_count": len(hits),
                              "referencing_paths": sorted({h[0] for h in hits})[:CAPS["referencing_paths"]]})
    consumers.sort(key=lambda c: (-c["hit_count"], c["source_path"], c["name"]))
    return {"unit_id": unit, "consumers": sorted(consumers[:CAPS["obligations"]], key=lambda c: (c["source_path"], c["name"]))}


# --- self-test ------------------------------------------------------------------------------------------------
def _g(ws, *args):
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"] + list(args)
    return subprocess.run(cmd, cwd=ws, check=True, capture_output=True, stdin=subprocess.DEVNULL).stdout


def _put(ws, files):
    for p, c in files.items():
        full = os.path.join(ws, p)
        if c is None:
            os.remove(full)
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(c)


def _fixture(root, base, change, frame, cfg=None, dirty=None, renames=None):
    """Commit `base`, apply `dirty` (pre-wave, uncommitted), record the pre tree, apply `change` and `renames`
    ({new_path: old_path}), hand-build the footprint (base_ref = pre tree) and return (run_dir, ws)."""
    renames = renames or {}
    ws = tempfile.mkdtemp(dir=root)
    _g(ws, "init", "-q")
    _put(ws, dict(base, **{".gitignore": ".wip/\n"}))
    _g(ws, "add", "-A")
    _g(ws, "commit", "-q", "-m", "base")
    rd = os.path.join(ws, ".wip", "RUN")
    os.makedirs(os.path.join(rd, "units", "U01"))
    _put(ws, dirty or {})
    pre = footprint.git_tree(ws, footprint.exclude_patterns(ws, rd))
    _put(ws, change)
    for new, old in sorted(renames.items()):
        os.rename(os.path.join(ws, old), os.path.join(ws, new))
    changes = []
    for p in sorted(set(change) | set(renames)):
        src = renames.get(p, p)
        b = subprocess.run(["git", "cat-file", "blob", "%s:%s" % (pre, src)], cwd=ws, capture_output=True).stdout \
            if src in base or src in (dirty or {}) else None
        a = None
        if change.get(p, "") is not None:
            with open(os.path.join(ws, p), "rb") as fh:
                a = fh.read()
        st = "R" if p in renames else "A" if b is None else "D" if a is None else "M"
        changes.append({"path": p, "status": st, "from_path": src if st == "R" else None,
                        "sha256_before": _sha(b) if b is not None else None, "sha256_after": _sha(a) if a is not None else None})
    fp = {"unit_id": "U01", "iteration": 1, "mode": "git", "base_ref": pre, "pre_snapshot_sha256": None,
          "post_snapshot_sha256": None, "changes": changes, "unattributed": [], "capture_error": None, "tool_version": "self-test"}
    with open(os.path.join(rd, "units", "U01", "footprint.json"), "wb") as fh:
        fh.write(_dump(fp))
    with open(os.path.join(rd, "graph.json"), "w") as fh:
        json.dump({"units": [{"id": "U01", "frame": {"modifies": frame}}]}, fh)
    with open(os.path.join(rd, "blast-config.json"), "w") as fh:
        json.dump(cfg or {"coupling_rules": [], "scan_excludes": []}, fh)
    return rd, ws


def _obl(doc, name):
    ids = {s["id"] for s in doc["symbols"] if s["name"] == name}
    return [o for o in doc["obligations"] if ids & set(o["symbol_ids"])]


def _refs(doc, name):
    return [o["referencing_paths"] for o in _obl(doc, name)]


def _self_test():
    root = tempfile.mkdtemp(prefix="impact_scan_selftest_")
    results = []

    def run(rule, pol, fn):
        try:
            ok = bool(fn())
        except Exception as exc:  # a crash is a FAIL, never a pass
            sys.stderr.write("%s %s: %s: %s\n" % (rule, pol, type(exc).__name__, exc))
            ok = False
        results.append(ok)
        print("case %s %s %s" % (rule, pol, "ok" if ok else "FAIL"))

    def doc_of(*a, **k):
        """A lazy scan, built on first use INSIDE a case: a crash in fixture or scan is that case's FAIL."""
        memo = []

        def get():
            if not memo:
                memo.append(scan(_fixture(root, *a, **k)[0], "U01")[0])
            return memo[0]
        return get

    def cfg_rejected(cfg):
        fd, p = tempfile.mkstemp(dir=root, suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
        try:
            load_config(root, root, p)
        except ScanError:
            return True
        return False

    try:
        lib0 = "def foo(a):\n    return a\n\ndef keep():\n    pass\n"
        base = {"lib.py": lib0, "use.py": "from lib import foo, keep\nfoo(1)\n", "cli.py":
                "import argparse\np = argparse.ArgumentParser()\np.add_argument('--old-flag')\n",
                "docs/README.md": "# Docs\n\nRun with --old-flag.\n", "inner.py": "import lib\n", "CHANGELOG.md": "# Log\n"}
        # removed_function: foo removed (used in use.py) -> 1 obligation; an ADDED function used elsewhere -> none.
        d = doc_of(base, {"lib.py": "def keep():\n    pass\n\ndef newfn():\n    pass\n", "use.py": base["use.py"] + "newfn()\n"},
                   ["lib.py"])
        run("removed_function", "pos", lambda: _refs(d(), "foo") == [["use.py"]])
        run("removed_function", "neg", lambda: _obl(d(), "newfn") == [] and _obl(d(), "keep") == [])
        # renamed_flag: --old-flag -> --new-flag, old one mentioned in docs -> obligation; the new flag -> none.
        d = doc_of(base, {"cli.py": base["cli.py"].replace("--old-flag", "--new-flag"),
                          "docs/README.md": base["docs/README.md"].replace("Run with", "Use --new-flag; run with")}, ["cli.py"])
        run("renamed_flag", "pos", lambda: _refs(d(), "--old-flag") == [["docs/README.md"]])
        run("renamed_flag", "neg", lambda: _obl(d(), "--new-flag") == [] and not any(s["name"] == "--new-flag" for s in d()["symbols"]))
        # no_outside_refs: keep() changes signature, used only inside the frame -> 0; plus an outside use -> 1 (control).
        lib_sig = "def foo(a):\n    return a\n\ndef keep(x):\n    pass\n"
        only_in = dict(base, **{"use.py": "from lib import foo\nfoo(1)\n", "inner.py": "from lib import keep\nkeep()\n"})
        d = doc_of(only_in, {"lib.py": lib_sig}, ["lib.py", "inner.py"])
        run("no_outside_refs", "neg", lambda: d()["obligations"] == [] and any(s["name"] == "keep" for s in d()["symbols"]))
        d = doc_of(only_in, {"lib.py": lib_sig}, ["lib.py"])
        run("no_outside_refs", "pos", lambda: _refs(d(), "keep") == [["inner.py"]])
        # coupling: lib.py touched without CHANGELOG.md -> coupling obligation; touching it too -> none.
        rules = {"coupling_rules": [{"id": "log", "when_paths": ["*.py"], "require": {"touch_any": ["CHANGELOG.md"]}}], "scan_excludes": []}
        d = doc_of(base, {"lib.py": lib0 + "\n"}, ["lib.py"], cfg=rules)
        run("coupling", "pos", lambda: [(o["kind"], o["rule_id"]) for o in d()["obligations"]] == [("coupling", "log")])
        d = doc_of(base, {"lib.py": lib0 + "\n", "CHANGELOG.md": "# Log\n- x\n"}, ["lib.py", "CHANGELOG.md"], cfg=rules)
        run("coupling", "neg", lambda: d()["obligations"] == [])
        # excluded_path: a use under ex/ counts without scan_excludes and is not searched with ex/** excluded.
        ex = dict(base, **{"ex/old.txt": "foo\n"})
        gone = {"lib.py": "def keep():\n    pass\n"}
        d = doc_of(ex, gone, ["lib.py"])
        run("excluded_path", "pos", lambda: "ex/old.txt" in _obl(d(), "foo")[0]["referencing_paths"])
        d = doc_of(ex, gone, ["lib.py"], cfg={"coupling_rules": [], "scan_excludes": ["ex/**"]})
        run("excluded_path", "neg", lambda: _refs(d(), "foo") == [["use.py"]])
        # one_obligation_per_name: foo removed from TWO frame files, used 12x in 6 files -> one obligation, all hits counted.
        many = dict(base, **{"use.py": "", "lib2.py": lib0}, **{"m%d.py" % i: "foo()\nfoo()\n" for i in range(6)})
        d = doc_of(many, {"lib.py": "def keep():\n    pass\n", "lib2.py": "def keep():\n    pass\n"}, ["lib.py", "lib2.py"])
        run("one_obligation_per_name", "pos", lambda: len(_obl(d(), "foo")) == 1 and _obl(d(), "foo")[0]["hit_count"] == 12
            and len(_obl(d(), "foo")[0]["sample_hits"]) == 5 and len(_obl(d(), "foo")[0]["symbol_ids"]) == 2
            and d()["truncated_hits"] == 7)
        run("one_obligation_per_name", "neg", lambda: len(d()["obligations"]) == 1)
        # dirty_at_start: HEAD has old_head(); before the wave it was already replaced (uncommitted) by prewave();
        # the unit then removes prewave(). Diffing against the pre-wave tree reports prewave, never old_head.
        dbase = dict(base, **{"w.py": "def old_head():\n    pass\n", "user.py": "old_head()\nprewave()\n"})
        d = doc_of(dbase, {"w.py": "def other():\n    pass\n"}, ["w.py"], dirty={"w.py": "def prewave():\n    pass\n"})
        run("dirty_at_start", "pos", lambda: len(_obl(d(), "prewave")) == 1)
        run("dirty_at_start", "neg", lambda: _obl(d(), "old_head") == [] and not any(s["name"] == "old_head" for s in d()["symbols"]))
        # nonschema_json: a key removed from a plain JSON file (no properties/enum) goes to the identifier fallback ->
        # 1 obligation; a JSON schema in the same change still goes through the schema extractor only.
        jb = dict(base, **{"cfg.json": json.dumps({"retry_limit": 3, "keep_me": 1}, indent=1), "ops.txt": "retry_limit\n",
                           "s.schema.json": json.dumps({"properties": {"keep": {}, "gonekey": {}}}, indent=1), "ref.txt": "gonekey\n"})
        d = doc_of(jb, {"cfg.json": json.dumps({"keep_me": 1}, indent=1),
                        "s.schema.json": json.dumps({"properties": {"keep": {}}}, indent=1)}, ["cfg.json", "s.schema.json"])
        run("nonschema_json", "pos", lambda: _refs(d(), "retry_limit") == [["ops.txt"]])
        run("nonschema_json", "neg", lambda: [(s["name"], s["kind"]) for s in d()["symbols"]
                                              if s["source_path"] == "s.schema.json"] == [("gonekey", "schema-key")])
        # schema_key_scope: `note` removed from object a while b.note survives -> reported; inserting an allOf
        # member (list positions shift) makes no key under it look removed.
        sb = {"properties": {"a": {"properties": {"note": {}, "x1": {}}}, "b": {"properties": {"note": {}}}},
              "allOf": [{"properties": {"deep": {}}}]}
        sa = {"properties": {"a": {"properties": {"x1": {}}}, "b": {"properties": {"note": {}}}},
              "allOf": [{"required": []}, {"properties": {"deep": {}}}]}
        d = doc_of(dict(base, **{"k.json": json.dumps(sb), "ref.txt": "note deep\n"}), {"k.json": json.dumps(sa)}, ["k.json"])
        run("schema_key_scope", "pos", lambda: _refs(d(), "note") == [["ref.txt"]])
        run("schema_key_scope", "neg", lambda: not any(s["name"] == "deep" for s in d()["symbols"]))
        # fallback_rule (unstructured file): beta_key leaves its line but survives on an UNCHANGED line -> reported;
        # alpha_key, present on an added line, and words only on unchanged lines -> not reported.
        yb = dict(base, **{"c.yaml": "alpha_key: 1\nbeta_key: 2\nnote: beta_key again\n", "ref2.txt": "alpha_key beta_key\n"})
        d = doc_of(yb, {"c.yaml": "alpha_key: 5\nnote: beta_key again\n"}, ["c.yaml"])
        run("fallback_rule", "pos", lambda: _refs(d(), "beta_key") == [["ref2.txt"]])
        run("fallback_rule", "neg", lambda: not any(s["name"] in ("alpha_key", "note", "again") for s in d()["symbols"]))
        # constant_strings: a stem renamed inside LABELS's value is searched as text and reaches the .tsv that pins it;
        # the sibling stem left unchanged, and a multi-line literal, are never changed names.
        lb = 'LABELS = [{"stem": "I9 old stem"}, {"stem": "I8 kept stem"}]\nHELP = """two\nlines"""\n'
        la = 'LABELS = [{"stem": "I9 new stem"}, {"stem": "I8 kept stem"}]\nHELP = """other"""\n'
        d = doc_of(dict(base, **{"lab.py": lb, "pin.tsv": "x\tI9 old stem\nI8 kept stem\n"}), {"lab.py": la}, ["lab.py"])
        run("constant_strings", "pos", lambda: _refs(d(), "I9 old stem") == [["pin.tsv"]])
        run("constant_strings", "neg", lambda: not any(s["name"] in ("I8 kept stem", "stem", "two\nlines") for s in d()["symbols"]))
        # fallback_escapes: a reworded JSON prose value; `\u2014second` and `\nold_name` are escapes glued to words ->
        # only old_name is reported, never u2014 / u2014second / nold_name (the M2 noise on #30 and #37).
        eb, ea = '{"note": "first\\u2014second\\nold_name \\u00a7 x"}\n', '{"note": "first, second \\u00a7 x"}\n'
        run("fallback_escapes", "pos", lambda: [n[1] for n in extract("n.json", eb, ea)[1]] == ["old_name"])
        run("fallback_escapes", "neg", lambda: not {"u2014", "u2014second", "nold_name", "u00a7"} & {n[1] for n in extract("n.json", eb, ea)[1]})
        # escape_scope: outside .json the one-letter escapes are blanked only inside a double-quoted span, so
        # `"\nold_name"` in YAML yields old_name, and an unquoted Windows path C:\tools\build_dir yields tools and
        # build_dir, never ools / uild_dir.
        run("escape_scope", "pos", lambda: [n[1] for n in extract("c.yaml", 'msg: "first\\nold_name"\n', 'msg: "first"\n')[1]]
            == ["old_name"])
        run("escape_scope", "neg", lambda: [n[1] for n in extract("cfg.ini", "root = C:\\tools\\build_dir\n", "root = C:\\opt\n")[1]]
            == ["build_dir", "tools"])
        # constant_rename: LABELS -> LABEL_TABLE with every literal unchanged (205 of them, each pinned twice in a
        # .tsv) and one literal moved to another constant: no `string` symbol, and the two genuine obligations
        # (the renamed constant, the constant whose value names it) are kept, far below the obligations cap.
        big = ['"row%03d label"' % i for i in range(205)]
        tb = "LABELS = [%s]\nFIRST_LABEL = LABELS[0]\nMOVED_A = ['moved text']\nMOVED_B = []\n" % ", ".join(big)
        ta = "LABEL_TABLE = [%s]\nFIRST_LABEL = LABEL_TABLE[0]\nMOVED_A = []\nMOVED_B = ['moved text']\n" % ", ".join(big)
        pins = "".join("x\trow%03d label\ny\trow%03d label\n" % (i, i) for i in range(205)) + "moved text\n"
        cb = dict(base, **{"tab.py": tb, "pin.tsv": pins, "tuse.py": "from tab import LABELS, FIRST_LABEL\n"})
        d = doc_of(cb, {"tab.py": ta}, ["tab.py"])
        run("constant_rename", "pos", lambda: _refs(d(), "LABELS") == [["tuse.py"]] and _refs(d(), "FIRST_LABEL") == [["tuse.py"]])
        run("constant_rename", "neg", lambda: not any(s["kind"] == "string" for s in d()["symbols"]) and len(d()["obligations"]) == 2)
        # table_lower_rename / table_move / table_wrap: the same pinned table (plus 'N-row000 label', which CONTAINS
        # the stem 'row000 label') renamed to a lowercase name, moved into another changed .py file, or wrapped in a
        # function. neg: no literal text changed -> no `string` symbol and only the genuine obligations (the table's
        # name; FIRST_LABEL too on the rename, its value names the table). pos: the same refactor also renames the
        # stem -> exactly that stem is reported and reaches the .tsv (exact equality: 'N-row000 label' must not hide it).
        rows = big + ['"N-row000 label"']

        def shaped(stem):
            tbl = "[%s]" % ", ".join('"%s"' % stem if r == '"row000 label"' else r for r in rows)
            return {"lower": ({"tab.py": "label_table = %s\nFIRST_LABEL = label_table[0]\n" % tbl}, ["tab.py"]),
                    "move": ({"tab.py": "from tabdata import LABELS\nFIRST_LABEL = LABELS[0]\n", "tabdata.py": "LABELS = %s\n" % tbl},
                             ["tab.py", "tabdata.py"]),
                    "wrap": ({"tab.py": "def _labels():\n    return %s\n\n\nLABELS = _labels()\nFIRST_LABEL = LABELS[0]\n" % tbl}, ["tab.py"])}

        def strs(doc):
            return sorted(s["name"] for s in doc["symbols"] if s["kind"] == "string")

        def obl_names(doc):
            return sorted({s["name"] for o in doc["obligations"] for s in doc["symbols"] if s["id"] in o["symbol_ids"]})
        sb = dict(base, **{"tab.py": "LABELS = [%s]\nFIRST_LABEL = LABELS[0]\n" % ", ".join(rows), "pin.tsv": pins + "N-row000 label\n",
                           "tuse.py": "from tab import LABELS, FIRST_LABEL\n"})
        for shp, rule, genuine in (("lower", "table_lower_rename", ["FIRST_LABEL", "LABELS"]), ("move", "table_move", ["LABELS"]),
                                   ("wrap", "table_wrap", ["LABELS"])):
            dp, dn = doc_of(sb, *shaped("row000 renamed")[shp]), doc_of(sb, *shaped("row000 label")[shp])
            run(rule, "pos", lambda dp=dp: strs(dp()) == ["row000 label"] and _refs(dp(), "row000 label") == [["pin.tsv"]])
            run(rule, "neg", lambda dn=dn, g=genuine: strs(dn()) == [] and obl_names(dn()) == g)
        # predict_names: a planned frame holding the same 205-literal table, a function and a CLI flag: --predict
        # lists the function and flag consumers and no literal (literals would fill the consumer cap first).
        pf = "import argparse\nLABELS = [%s]\n\ndef find_cycle():\n    pass\n\ndef main():\n    ap = argparse.ArgumentParser()\n" \
             "    ap.add_argument('--json')\n" % ", ".join(big)
        pmemo = []

        def pred():
            if not pmemo:
                pr = _fixture(root, dict(base, **{"tbl.py": pf, "pin.tsv": pins, "pcall.py": "from tbl import find_cycle\n",
                                                  "docs/use.md": "Run tbl.py --json.\n"}), {}, ["tbl.py"])
                pmemo.append({c["name"] for c in predict(pr[0], "U01")["consumers"]})
            return pmemo[0]
        run("predict_names", "pos", lambda: {"find_cycle", "--json"} <= pred())
        run("predict_names", "neg", lambda: not any(n.endswith(" label") or n == "moved text" for n in pred()))
        # module_names: a removed and a value-changed PEP 8 private constant and a removed lowercase binding, all
        # imported elsewhere, each get an obligation; a lowercase binding whose VALUE changes and a 2-char one do not.
        mb = dict(base, **{"m.py": "_PRIV = 3\n_LIMIT = 1\nlower_cfg = 4\nkept_cfg = 1\nzz = 0\n",
                           "mu.py": "from m import _PRIV, _LIMIT, lower_cfg, kept_cfg, zz\n"})
        d = doc_of(mb, {"m.py": "_LIMIT = 2\nkept_cfg = 2\n"}, ["m.py"])
        run("module_names", "pos", lambda: all(_refs(d(), n) == [["mu.py"]] for n in ("_PRIV", "_LIMIT", "lower_cfg")))
        run("module_names", "neg", lambda: not any(s["name"] in ("kept_cfg", "zz") for s in d()["symbols"]))
        # module_rename: old_mod.py renamed to new_mod.py -> `import old_mod` gets an obligation; the new name none.
        rb = dict(base, **{"old_mod.py": "def f1():\n    pass\n", "imp.py": "import old_mod\n", "imp2.py": "import new_mod\n"})
        d = doc_of(rb, {}, ["old_mod.py", "new_mod.py"], renames={"new_mod.py": "old_mod.py"})
        run("module_rename", "pos", lambda: _refs(d(), "old_mod") == [["imp.py"]])
        run("module_rename", "neg", lambda: _obl(d(), "new_mod") == [] and not any(s["name"] == "new_mod" for s in d()["symbols"]))
        # setext_heading: a renamed setext heading mentioned elsewhere -> obligation; a YAML front-matter edit is
        # not a heading and the new heading gets none.
        gb = dict(base, **{"guide.md": "---\ntitle: Intro Page\n---\n\nSetup Steps\n===========\n\ntext\n",
                           "ref3.txt": "Setup Steps\ntitle: Intro Page\nNew Steps\n"})
        d = doc_of(gb, {"guide.md": "---\ntitle: Other Page\n---\n\nNew Steps\n=========\n\ntext\n"}, ["guide.md"])
        run("setext_heading", "pos", lambda: _refs(d(), "Setup Steps") == [["ref3.txt"]])
        run("setext_heading", "neg", lambda: not any(s["name"] != "Setup Steps" for s in d()["symbols"]))
        # extractor_switch: an extensionless python script rewritten without a shebang: no crash; its removed
        # function is reported through the fallback; no scan error, and the added word is not a changed name.
        xb = dict(base, **{"bin/tool": "#!/usr/bin/env python3\ndef toolfn():\n    pass\n", "callers.txt": "toolfn\n"})
        d = doc_of(xb, {"bin/tool": "echo hi\n"}, ["bin/tool"])
        run("extractor_switch", "pos", lambda: _refs(d(), "toolfn") == [["callers.txt"]])
        run("extractor_switch", "neg", lambda: not any(s["kind"] == "scan-error" or s["name"] == "echo" for s in d()["symbols"]))
        # bad_config: a non-object config, a coupling rule without id, a require with neither form and a string
        # scan_excludes are each rejected with ScanError (main exits 2); well-formed configs are accepted.
        run("bad_config", "pos", lambda: all(cfg_rejected(c) for c in (
            [], {"coupling_rules": [{"when_paths": ["*.py"], "require": {"touch_any": ["X"]}}]},
            {"coupling_rules": [{"id": "r", "when_paths": ["*.py"], "require": {}}]}, {"scan_excludes": "ex/**"})))
        def unsafe_rejected(extra, files=None):
            """Append `extra` to a real fixture's footprint; True iff scan() refuses it with the unsafe-path ScanError
            (any other outcome, including a scan that reads the path, is False)."""
            rd, ws = _fixture(root, base, {"lib.py": lib0.replace("def foo(a):", "def foo(a, b):")}, ["lib.py"])
            _put(ws, files or {})
            fpath = os.path.join(rd, "units", "U01", "footprint.json")
            with open(fpath, encoding="utf-8") as fh:
                fpd = json.load(fh)
            fpd["changes"].append(extra)
            with open(fpath, "wb") as fh:
                fh.write(_dump(fpd))
            try:
                scan(rd, "U01")
            except ScanError as exc:
                return "unsafe changes[]" in str(exc)
            return False
        outside = os.path.join(root, "outside.py")
        _put(root, {"outside.py": "def outside_fn():\n    pass\n"})
        row = {"status": "A", "from_path": None, "sha256_before": None, "sha256_after": _sha(b"def outside_fn():\n    pass\n")}
        run("unsafe_footprint_path", "pos", lambda: all(unsafe_rejected(dict(row, path=p)) for p in (outside, "../outside.py"))
            and all(unsafe_rejected(dict(row, path="new.py", status="R", from_path=f), {"new.py": "x = 1\n"})
                    for f in (outside, "../outside.py", "a\0b.py")))
        run("unsafe_footprint_path", "neg", lambda: not unsafe_rejected(dict(row, path="inside.py"), {"inside.py": "def outside_fn():\n    pass\n"})
            and _obl(doc_of(base, {"lib.py": lib0.replace("def foo(a):", "def foo(a, b):")}, ["lib.py"])(), "foo"))
        run("bad_config", "neg", lambda: not cfg_rejected(rules) and not cfg_rejected(
            {"coupling_rules": [{"id": "c", "when_paths": ["*.py"], "require": {"command": "make test"}}], "scan_excludes": ["ex/**"]}))
    except Exception as exc:  # outside any case: still a FAIL, and the temp root is still removed
        sys.stderr.write("self-test aborted: %s: %s\n" % (type(exc).__name__, exc))
        results.append(False)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if results and all(results) else 1


EPILOG = """modes:
  impact_scan.py --self-test   run the built-in cases on throwaway git repos; one line per case,
                               'case <rule> pos|neg ok|FAIL'; exit 0 iff every case is ok
exit status:
  0  done, no scan errors
  1  impact JSON written (--preview: printed) but scan errors are recorded in it; or a self-test case failed
  2  fatal, nothing written: unreadable/malformed footprint.json, malformed blast config, no frame for the unit"""


def main(argv):
    if argv == ["--self-test"]:
        return _self_test()
    ap = argparse.ArgumentParser(prog="impact_scan.py", description="Out-of-frame consumers of what a dag unit changed.",
                                 epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--unit", required=True)
    ap.add_argument("--config")
    ap.add_argument("--workspace")
    mx = ap.add_mutually_exclusive_group()
    mx.add_argument("--predict", action="store_true")
    mx.add_argument("--preview", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.predict:
            sys.stdout.write(_dump(predict(a.run_dir, a.unit, a.config, a.workspace)).decode("utf-8"))
            return 0
        doc, errors = scan(a.run_dir, a.unit, a.config, a.workspace)
    except (ScanError, footprint.CaptureError) as exc:
        sys.stderr.write("impact_scan: %s\n" % exc)
        return 2
    data = _dump(doc) if a.preview else write_impact(a.run_dir, a.unit, doc)
    sys.stdout.write(data.decode("utf-8"))
    for where, why in errors:
        sys.stderr.write("impact_scan: error at %s: %s\n" % (where, why))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
