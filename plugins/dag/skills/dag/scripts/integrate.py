#!/usr/bin/env python3
"""integrate.py — whole-run blast-radius integration check (Phase 8) for a dag run.

Usage:
  integrate.py <RUN_DIR> [--config <blast-config.json>] [--replay-timeout SECONDS]
  integrate.py <RUN_DIR> --explain <mapping.json>
  integrate.py --self-test

Writes <RUN_DIR>/integration.json (schema schemas/integration.schema.json, closed objects) and its sidecar
<RUN_DIR>/integration.json.sha256 (`shasum -a 256` format: "<hex>  integration.json"). Exit 0 = written with an
empty errors[]; 1 = written, errors[] non-empty (every step that could not run is named there — fail closed and
visible, never silent); 2 = refused or fatal, nothing written.

Contract, restated so this file is self-describing (runtime inputs: the run dir, the working repository, its
.dag/ store):
- START STATE = fsm-state.json `blast` {mode git|snapshot, base_sha, base_tree_digest, workspace_root}. base_sha
  must be null or a 40/64-hex commit id, else the run is refused (exit 2) before any git call. git mode:
  the base tree is the first candidate whose content digest equals base_tree_digest — the earliest
  `blast/wave<N>.pre.json` snapshot's `tree` (a dirty start is then not charged to units), then base_sha^{tree};
  no match => an errors[] row and base_sha's tree is used (over-reporting, never under-reporting). snapshot mode:
  the earliest pre snapshot's `entries` are the base (no snapshot => errors[] row, union_changes []); their
  content digest (sha256 over the sorted "<path>\\t<sha256>\\n" lines) must equal base_tree_digest, else an errors[]
  row says that changes made between the start state and that snapshot are missing from union_changes (snapshot
  mode cannot see them, so the gap is made visible rather than silent).
- END STATE = the current working tree. Tree ids, the tip digest, exclusions (.wip/** and the run dir), the
  content-based change list (`git diff-tree` between trees) and snapshot-mode file hashing all come from
  footprint.py — never a second copy. The two digest formulas are mirrored here only to verify a base, and each
  is recomputed for the tip and must equal footprint.tree_digest's, a runtime guard against the formulas drifting.
- union_changes[] = every changed path {path, status A|M|D|T, sha256_base, sha256_tip}; a rename is split into
  D(old) + A(new) so each side's hash is null exactly where the path is absent. unowned_writes[] = changed paths in
  no unit's units/<U>/footprint.json (path or from_path); multi_writer_paths[] = paths in >= 2 footprints. A
  footprint with capture_error, or unreadable, is an errors[] row.
- replay[] {unit_id, case_id, command, exit_code}: every "passed command-form case_set check" — a brief.json
  case_set entry with check_form "command" whose row in the unit's CURRENT debrief.json case_set_discharge with
  origin "orchestrator" has outcome "discharged" — re-run under bash (else /bin/sh) from the workspace root with a
  per-command timeout (default 300 s; --replay-timeout SECONDS overrides it, and the same window bounds each census
  command; regression commands keep their own timeout_s; the process group is killed). SECONDS must be a finite
  number greater than 0 (an integer or a decimal), else the run is refused (exit 2, one line) before any file is
  read or written. A timeout or a check that cannot start is an errors[] row
  and no replay row (the schema's exit_code is an integer), so the validator sees the check as not re-run. An
  executed unit (units/<U>/debrief.json present on disk; presence decides, never the parsed value) whose
  debrief.json is not a JSON object (null, boolean, number, string or list), whose brief.json is missing or not
  an object, or whose debrief carries orchestrator rows while brief.json has no case_set list, is an errors[] row
  naming the unit: its checks cannot be selected (never a silent skip).
- censuses[] {id, base, tip, added, closed, shipped}: each blast-config census `command_template`, with `{root}`
  replaced by the shell-quoted absolute path of the tree measured (so templates must not quote it themselves), runs
  with cwd = that tree: BASE = `git archive <base_sha>` extracted (tarfile data filter) into a temp dir that is
  always deleted (no worktree); TIP = the workspace root. stdout: JSON with `sites: [{kind, src, ...}]` => multiset
  diff on (kind, src), added = tip - base, closed = base - tip; JSON with `total`, or a last non-empty line that is
  a bare integer => count-only: added = max(0, tip - base), closed = max(0, base - tip), noted on stderr (the schema
  has no field for it). shipped = added (two-point comparison). A non-zero exit, unparseable output, snapshot mode or
  no base_sha => errors[] row and no census row. Config: --config, else <RUN_DIR>/blast-config.json, else
  <workspace>/.dag/blast.json; none found or unreadable => errors[] row.
- differential[] {regression_id, base_exit, tip_exit, base_stdout_sha256, tip_stdout_sha256, intended_change_ref
  null}: each blast-config regression_commands {id, command, timeout_s, compare} entry runs under bash with its own
  timeout_s twice — at the START state with cwd = a fresh `git -c core.hooksPath=/dev/null worktree add --detach
  <tmp>/wt <base_sha>` (hooks off; tmp in the system temp dir, and a temp dir resolving inside the workspace is
  refused as an errors[] row), and at the END state with cwd = the workspace root. Every git worktree call and every
  command runs in its own process group, killed whole on a timeout or an interruption (DAG_BLAST_GIT_TIMEOUT bounds
  the git calls). A finally block always runs `git worktree remove --force --force` (clears a killed add's
  'initializing' lock too), deletes the temp dir and checks `git worktree list --porcelain`; only if this worktree
  is still registered does it run `git worktree prune`, which is repo-wide (it also drops other unlocked
  registrations whose directories are missing). The finally runs on a failing command, a timeout, an exception,
  KeyboardInterrupt and — through a temporary trap, main thread only — SIGTERM/SIGHUP, which are re-delivered to the
  previous handler after cleanup. A survivor is an errors[] row. A timeout on either side, a worktree that cannot be
  created, a signal or a malformed entry is an errors[] row and no differential row (exit codes are integers).
  No rows => differential_none_reason: snapshot mode => "snapshot mode cannot rebuild the start tree"; no
  regression_commands => the config's regression_none_reason (else a stated default); no config, no base_sha or no
  command that produced both results => a stated reason (the last two also as errors[] rows).
- test_weakening[] {kind, detail, intended_change_ref null} over blast-config test_surfaces {id, kind, path}; base =
  `git cat-file blob <base_sha>:<path>`, tip = the workspace file. expectations-tsv (columns fixture, expected_exit,
  pin, flags; blank and # lines ignored; flags not compared): rows matched per fixture as a multiset, so adding or
  reordering rows reports nothing; kinds tsv-row-removed, tsv-exit-changed, tsv-pin-dropped, tsv-pin-changed.
  test-glob (path is a frame_match pattern matched against base_sha's files): test-file-deleted,
  fewer-test-functions (`def test_` line count fell; '# def test_' is not counted), skip-added (non-comment
  pytest.mark.skip(if) / pytest.skip / unittest.skip* / skipTest / bare @skip* markers: the file's count rose, or
  a test present on both sides gained one, e.g. a marker moved onto it). Unrecognised: xfail, importorskip,
  conftest/collect_ignore deselection, early returns; markers inside strings are counted. Added rows, tests and
  files are not weakening. A tsv path present at neither base_sha nor the workspace, or a glob matching no file on
  either side, is an errors[] row. Snapshot mode or no base_sha => an errors[] row per surface.
- --explain mapping = {"differential": {"<regression_id>": "<ref>"}, "test_weakening": {"<index>": "<ref>"}}: each
  ref must equal (verbatim) an entry of some graph.json unit's frame.intended_changes and each key must name an
  existing row (a test_weakening index is ASCII digits only). Any refusal leaves both files untouched (exit 2); on success the sidecar is rewritten for the
  new bytes (it is an integrity record, not a tamper seal: --explain does not check the old sidecar first).
"""
import argparse
import ast
import collections
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_match  # noqa: E402  the single path matcher (footprint.py's exclusions use it too)
import footprint  # noqa: E402  snapshots, trees, diffs, digests and exclusions — reused, never re-implemented

TOOL_VERSION = "integrate.py/1"
DEFAULT_REPLAY_TIMEOUT = 300.0
SNAPSHOT_NONE_REASON = "snapshot mode cannot rebuild the start tree"
WORKTREE_PREFIX = "dag-integrate-wt-"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "schemas",
                           "integration.schema.json")
_UNIT = re.compile(r"^U[0-9]{2,}$")
_PRE = re.compile(r"^wave([0-9]+)\.pre\.json$")
_INT_LINE = re.compile(r"^\s*([0-9]+)\s*$")
_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_INDEX = re.compile(r"[0-9]+")


class IntegrateError(Exception):
    """A condition that refuses the whole operation (one-line reason, exit 2)."""


def _load(path, what):
    """Parsed JSON at path; None when absent; IntegrateError when unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise IntegrateError("%s unreadable (%s)" % (what, type(exc).__name__))


def _list(value):
    return value if isinstance(value, list) else []


def _json_kind(value):
    """The JSON name of a parsed value's type (null, boolean, number, string, list, object)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "list", dict: "object"}.get(type(value), type(value).__name__)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _tree_digest_of(tree):
    """footprint.tree_digest's git-mode formula, mirrored to digest a base candidate (guarded on the tip)."""
    return "sha256:" + _sha(("tree:%s\n" % tree).encode())


def _entries_digest(entries):
    """footprint.tree_digest's snapshot-mode formula over {path: {sha256}} entries, mirrored to verify a base
    snapshot (guarded on the tip): sha256 over the sorted "<path>\\t<sha256>\\n" lines."""
    lines = "".join("%s\t%s\n" % (p, entries[p].get("sha256")) for p in sorted(entries))
    return "sha256:" + _sha(lines.encode("utf-8", "surrogateescape"))


def _unit_ids(run_dir):
    try:
        names = os.listdir(os.path.join(run_dir, "units"))
    except FileNotFoundError:
        return []
    return sorted((n for n in names if _UNIT.match(n) and os.path.isdir(os.path.join(run_dir, "units", n))),
                  key=lambda n: (len(n), n))


def _earliest_pre(run_dir):
    try:
        names = os.listdir(os.path.join(run_dir, "blast"))
    except FileNotFoundError:
        return None
    waves = sorted((int(m.group(1)), n) for n in names for m in [_PRE.match(n)] if m)
    return os.path.join(run_dir, "blast", waves[0][1]) if waves else None


def _kill_group(proc, grace=5.0):
    """SIGKILL proc's whole process group (it was started in its own session), reap proc, then wait up to `grace`
    seconds until no member of the group is left, so no child is still writing when the caller cleans up."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait()
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except OSError:  # ProcessLookupError: the group is gone
            return
        time.sleep(0.02)


def run_shell(command, cwd, timeout):
    """(exit_code, stdout bytes) of a shell command; exit_code None on timeout (its whole process group killed).
    stdout goes to a temp file, not a pipe, so an orphaned grandchild can never hang the wait. An interruption
    (KeyboardInterrupt, a trapped signal) also kills the group before it propagates: the command never outlives
    the call."""
    shell = shutil.which("bash") or "/bin/sh"
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen([shell, "-c", command], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise IntegrateError("cannot start %s (%s)" % (shell, type(exc).__name__))
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            return None, b""
        except BaseException:
            _kill_group(proc)
            raise
        out.seek(0)
        return rc, out.read()


# --- whole-run diff ------------------------------------------------------------------------------------------
def whole_run_diff(run_dir, ws, mode, blast, errors):
    """(union_changes rows, base_tree_digest, tip_tree_digest). Digest failures raise; diff failures => errors."""
    pats = footprint.exclude_patterns(ws, run_dir)
    tip = footprint.tree_digest(ws, run_dir)
    if tip["mode"] != mode:
        raise IntegrateError("fsm-state.blast.mode is %s but the workspace is in %s mode" % (mode, tip["mode"]))
    base_digest = blast.get("base_tree_digest")
    pre = _earliest_pre(run_dir)
    changes = []
    try:
        if mode == "git":
            if _tree_digest_of(tip["tree"]) != tip["digest"]:
                raise IntegrateError("footprint.tree_digest's formula changed; integrate.py cannot verify the base")
            candidates = []
            if pre:
                candidates.append(footprint.read_snapshot(pre, ws, "git")[0]["tree"])
            if blast.get("base_sha"):
                sha = blast["base_sha"]
                candidates.append(footprint._decode(footprint.git(ws, ["rev-parse", "--verify", "%s^{tree}" % sha])).strip())
            if not candidates:
                raise footprint.CaptureError("no base: fsm-state.blast has no base_sha and no pre snapshot exists")
            matched = [t for t in candidates if _tree_digest_of(t) == base_digest]
            if not matched:
                errors.append("base tree: no candidate tree matches fsm-state.blast.base_tree_digest; diffing from "
                              "%s (changes present at the start may be charged to units)" % candidates[-1])
            base_tree = (matched or candidates[-1:])[0]
            base_digest = base_digest or _tree_digest_of(base_tree)
            changes = footprint.git_changes(ws, base_tree, tip["tree"], pats)
        else:
            if not pre:
                raise footprint.CaptureError("snapshot mode: no blast/wave<N>.pre.json base snapshot")
            base = footprint.read_snapshot(pre, ws, "snapshot")[0]
            now = {p: {"sha256": footprint._sha_path(ws, p)} for p in footprint.walk_files(ws, pats)}
            if _entries_digest(now) != tip["digest"]:
                raise IntegrateError("footprint.tree_digest's snapshot formula changed (or the workspace changed "
                                     "during integration); integrate.py cannot verify the base")
            snap_digest = _entries_digest(base["entries"])
            if snap_digest != base_digest:
                errors.append("base snapshot: %s content digest %s does not match fsm-state.blast.base_tree_digest "
                              "%s; changes made between the start state and that snapshot are missing from "
                              "union_changes and are charged to no unit" % (os.path.basename(pre), snap_digest,
                                                                            base_digest or "(absent)"))
            base_digest = base_digest or snap_digest
            changes = footprint.snapshot_changes(base, {"entries": now})
    except footprint.CaptureError as exc:
        errors.append("whole-run diff not computed: %s" % exc)
        changes = []
    rows = []
    for c in changes:
        if c["status"] == "R":
            rows.append({"path": c["from_path"], "status": "D", "sha256_base": c["sha256_before"], "sha256_tip": None})
            rows.append({"path": c["path"], "status": "A", "sha256_base": None, "sha256_tip": c["sha256_after"]})
        else:
            rows.append({"path": c["path"], "status": c["status"], "sha256_base": c["sha256_before"],
                         "sha256_tip": c["sha256_after"]})
    if not base_digest:
        raise IntegrateError("fsm-state.blast.base_tree_digest is absent and no base tree could be resolved")
    return sorted(rows, key=lambda r: r["path"]), base_digest, tip["digest"]


def ownership(run_dir, union_rows, errors):
    """(unowned_writes, multi_writer_paths) from every units/<U>/footprint.json."""
    writers = collections.defaultdict(list)
    for uid in _unit_ids(run_dir):
        try:
            fp = _load(os.path.join(run_dir, "units", uid, "footprint.json"), "%s footprint.json" % uid)
        except IntegrateError as exc:
            errors.append(str(exc))
            continue
        if fp is None:
            continue
        if not isinstance(fp, dict) or fp.get("capture_error"):
            errors.append("%s footprint.json carries capture_error: %s" % (uid, (fp or {}).get("capture_error")
                                                                             if isinstance(fp, dict) else "malformed"))
            continue
        paths = set()
        for ch in _list(fp.get("changes")):
            got = [ch.get("path")] + ([ch["from_path"]] if ch.get("from_path") is not None else []) \
                if isinstance(ch, dict) else [None]
            if not all(isinstance(p, str) and p and not frame_match.is_unsafe_path(p) for p in got):
                errors.append("%s footprint.json has a malformed or unsafe change %r" % (uid, ch))
                continue
            paths.update(got)
        for p in paths:
            writers[p].append(uid)
    unowned = sorted({r["path"] for r in union_rows if r["path"] not in writers})
    multi = [{"path": p, "units": u} for p, u in sorted(writers.items()) if len(u) >= 2]
    return unowned, multi


# --- replay --------------------------------------------------------------------------------------------------
def passed_command_checks(run_dir, errors):
    """[(unit_id, case_id, command)] for every passed command-form case_set check of every executed unit."""
    out = []
    for uid in _unit_ids(run_dir):
        dpath = os.path.join(run_dir, "units", uid, "debrief.json")
        if not os.path.lexists(dpath):
            continue  # not executed: "executed" is decided by the file's presence, never by its parsed value
        try:
            debrief = _load(dpath, "%s debrief.json" % uid)
            brief = _load(os.path.join(run_dir, "units", uid, "brief.json"), "%s brief.json" % uid)
        except IntegrateError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(debrief, dict):
            kind = ("JSON " + _json_kind(debrief)) if debrief is not None or os.path.exists(dpath) else \
                "dangling link or a file removed while it was read"
            errors.append("%s: debrief.json is a %s, not an object; its case_set checks were not replayed"
                          % (uid, kind))
            continue
        rows = {r.get("id"): r for r in _list(debrief.get("case_set_discharge"))
                if isinstance(r, dict) and r.get("origin") == "orchestrator"}
        if not isinstance(brief, dict):
            errors.append("%s: debrief.json present but brief.json is %s; its case_set checks were not replayed"
                          % (uid, "missing" if brief is None else "not a JSON object"))
            continue
        if rows and not isinstance(brief.get("case_set"), list):
            errors.append("%s: debrief.json carries orchestrator case_set_discharge rows but brief.json has no "
                          "case_set list; its checks were not replayed" % uid)
            continue
        for e in _list(brief.get("case_set")):
            if not isinstance(e, dict) or e.get("check_form") != "command":
                continue
            if (rows.get(e.get("id")) or {}).get("outcome") != "discharged":
                continue
            if not isinstance(e.get("check"), str) or not e["check"].strip() or not isinstance(e.get("id"), str):
                errors.append("%s case %r: discharged command check has no runnable command" % (uid, e.get("id")))
                continue
            out.append((uid, e["id"], e["check"]))
    return out


def replay(ws, checks, timeout, errors):
    rows = []
    for uid, cid, command in checks:
        try:
            rc, _ = run_shell(command, ws, timeout)
        except IntegrateError as exc:
            errors.append("replay %s %s: %s" % (uid, cid, exc))
            continue
        if rc is None:
            errors.append("replay %s %s: timed out after %gs (not re-run)" % (uid, cid, timeout))
            continue
        rows.append({"unit_id": uid, "case_id": cid, "command": command, "exit_code": rc})
    return rows


# --- censuses ------------------------------------------------------------------------------------------------
def load_config(run_dir, ws, explicit, errors):
    for path in ([explicit] if explicit else [os.path.join(run_dir, "blast-config.json"),
                                              os.path.join(ws, ".dag", "blast.json")]):
        try:
            cfg = _load(path, "blast config %s" % os.path.basename(path))
        except IntegrateError as exc:
            errors.append(str(exc))
            return None
        if cfg is not None:
            if not isinstance(cfg, dict):
                errors.append("blast config %s is not a JSON object" % os.path.basename(path))
                return None
            return cfg
    errors.append("no blast config found (--config, <RUN_DIR>/blast-config.json, <workspace>/.dag/blast.json)")
    return None


def parse_census(stdout):
    """(Counter of (kind, src) or None for the count-only form, count). Unparseable => IntegrateError."""
    text = stdout.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict) and isinstance(doc.get("sites"), list):
        bag = collections.Counter()
        for s in doc["sites"]:
            if not isinstance(s, dict) or "kind" not in s or "src" not in s:
                raise IntegrateError("census site without kind/src: %r" % (s,))
            bag[(json.dumps(s["kind"], sort_keys=True), json.dumps(s["src"], sort_keys=True))] += 1
        return bag, sum(bag.values())
    if isinstance(doc, dict) and type(doc.get("total")) is int and doc["total"] >= 0:
        return None, doc["total"]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    m = _INT_LINE.match(lines[-1]) if lines else None
    if m:
        return None, int(m.group(1))
    raise IntegrateError("census output is neither JSON sites/total nor a bare last integer")


def _measure(template, root, timeout):
    rc, out = run_shell(template.replace("{root}", shlex.quote(root)), root, timeout)
    if rc != 0:
        raise IntegrateError("census command %s" % ("timed out" if rc is None else "exited %d" % rc))
    return parse_census(out)


def census_diff(cid, base, tip):
    (bbag, bn), (tbag, tn) = base, tip
    if bbag is not None and tbag is not None:
        added, closed = sum((tbag - bbag).values()), sum((bbag - tbag).values())
    else:
        sys.stderr.write("integrate.py: census %s used the count-only form (no sites): gross added/closed are the "
                         "count difference only\n" % cid)
        added, closed = max(0, tn - bn), max(0, bn - tn)
    return {"id": cid, "base": bn, "tip": tn, "added": added, "closed": closed, "shipped": added}


def export_tree(ws, rev, dest):
    """Read-only export of `rev` into dest through `git archive` (no worktree, no checkout)."""
    if not hasattr(tarfile, "data_filter"):
        raise IntegrateError("this Python's tarfile lacks the data filter; refusing an unfiltered extract")
    data = footprint.git(ws, ["archive", "--format=tar", rev])
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(dest, filter="data")


def censuses(cfg, ws, mode, blast, timeout, errors):
    specs = [c for c in _list((cfg or {}).get("censuses")) if isinstance(c, dict)]
    if not specs:
        return []
    if mode != "git" or not blast.get("base_sha"):
        errors.extend("census %s: no git base to measure (snapshot mode or no base_sha)" % c.get("id") for c in specs)
        return []
    rows, tmp = [], tempfile.mkdtemp(prefix="dag-integrate-base-")
    try:
        base_root = os.path.join(tmp, "base")
        os.mkdir(base_root)
        try:
            export_tree(ws, blast["base_sha"], base_root)
        except (footprint.CaptureError, IntegrateError, tarfile.TarError, OSError) as exc:
            errors.extend("census %s: base export failed: %s" % (c.get("id"), exc) for c in specs)
            return []
        for c in specs:
            cid, tpl = c.get("id"), c.get("command_template")
            if not isinstance(cid, str) or not isinstance(tpl, str) or not tpl.strip():
                errors.append("census %r: malformed (id and command_template required)" % (cid,))
                continue
            try:
                rows.append(census_diff(cid, _measure(tpl, base_root, timeout), _measure(tpl, ws, timeout)))
            except IntegrateError as exc:
                errors.append("census %s: %s" % (cid, exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


# --- old-vs-new differential ---------------------------------------------------------------------------------
def _regression(r):
    """(id, command, timeout_s) of a well-formed regression_commands entry, else None."""
    if not isinstance(r, dict):
        return None
    rid, cmd, tmo = r.get("id"), r.get("command"), r.get("timeout_s")
    if (isinstance(rid, str) and rid and isinstance(cmd, str) and cmd.strip() and type(tmo) is int and tmo >= 1):
        return rid, cmd, tmo
    return None


class _Interrupted(BaseException):
    """Raised by the temporary signal trap of _run_regression so its cleanup runs before the signal is re-delivered."""


def _git_wt(ws, args, timeout=None):
    """stdout of one `git worktree ...` call (args may start with `-c key=value` pairs), run in its OWN session
    with footprint.git's environment (GIT_OPTIONAL_LOCKS=0, LC_ALL=C) and DAG_BLAST_GIT_TIMEOUT. Unlike a plain
    subprocess timeout, which kills git alone, a timeout or any interruption kills and reaps git's whole process
    group (its checkout child, smudge filters), so nothing is still writing into the worktree when cleanup starts.
    A timeout or a non-zero exit raises footprint.CaptureError."""
    timeout = footprint.git_timeout() if timeout is None else timeout
    what = "git " + " ".join(args[args.index("worktree"):][:2]) if "worktree" in args else "git"
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    env.pop("LANGUAGE", None)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(["git"] + list(args), cwd=ws, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, start_new_session=True)
        except OSError as exc:
            raise footprint.CaptureError("%s is unavailable (%s)" % (what, type(exc).__name__))
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise footprint.CaptureError("%s did not finish within %gs (DAG_BLAST_GIT_TIMEOUT); its process group "
                                         "was killed" % (what, timeout))
        except BaseException:
            _kill_group(proc)
            raise
        out.seek(0)
        err.seek(0)
        if rc != 0:
            msg = " ".join(err.read().decode("utf-8", "replace").split())[:300]
            raise footprint.CaptureError("%s failed (rc %d): %s" % (what, rc, msg or "unknown error"))
        return out.read()


def _registered(ws, wt):
    """True/False: does `git worktree list --porcelain` still name wt? None when the list cannot be read."""
    try:
        listed = _git_wt(ws, ["worktree", "list", "--porcelain"]).decode("utf-8", "surrogateescape")
    except footprint.CaptureError:
        return None
    return any(os.path.realpath(ln[len("worktree "):]) == wt for ln in listed.splitlines()
               if ln.startswith("worktree "))


def _drop_worktree(ws, tmp, wt, errors, rid):
    """Remove THIS call's worktree and temp dir; any survivor is an errors[] row. `git worktree remove --force
    --force <wt>` runs whether or not wt exists: the double force also clears the 'initializing' lock a killed
    `worktree add` leaves behind and a registration whose directory is already gone ("not a working tree" is
    tolerated, the post-check decides). The temp dir is deleted (once more after a short pause if anything still
    held it). `git worktree list --porcelain` then confirms wt is no longer registered; only if it still is do a
    second remove and `git worktree prune` run, because prune is repo-wide: it would also drop the user's own
    unlocked registrations whose directories are missing (e.g. a worktree on an unmounted drive)."""
    removal = None
    try:
        _git_wt(ws, ["worktree", "remove", "--force", "--force", wt])
    except footprint.CaptureError as exc:
        removal = exc
    shutil.rmtree(tmp, ignore_errors=True)
    if os.path.lexists(tmp):
        time.sleep(0.2)
        shutil.rmtree(tmp, ignore_errors=True)
    still = _registered(ws, wt)
    if still:
        for args in (["worktree", "remove", "--force", "--force", wt], ["worktree", "prune"]):
            try:
                _git_wt(ws, args)
            except footprint.CaptureError as exc:
                removal = exc
        still = _registered(ws, wt)
    if still is None:
        errors.append("regression %s: cannot list worktrees to confirm %s was removed" % (rid, wt))
    elif still:
        errors.append("regression %s: worktree %s is still registered after remove --force --force and prune (%s)"
                      % (rid, wt, removal))
    if os.path.lexists(tmp):
        errors.append("regression %s: temporary worktree %s could not be deleted" % (rid, tmp))


def _trap_signals(trap, prev):
    """While a regression runs (main thread only), SIGINT/SIGTERM/SIGHUP raise _Interrupted instead of their usual
    action, so the worktree cleanup in a finally block runs even on a default-disposition SIGTERM. Signals already
    ignored stay ignored. Each signal is recorded in trap['signums']; once disarmed (cleanup started) a further
    signal is only recorded, so it cannot abort the cleanup. prev receives {signum: previous handler}."""
    if threading.current_thread() is not threading.main_thread():
        return

    def handler(signum, frame):
        trap.setdefault("signums", []).append(signum)
        if trap.get("armed"):
            trap["armed"] = False
            raise _Interrupted(signum)

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        num = getattr(signal, name, None)
        old = signal.getsignal(num) if num is not None else None
        if old is None or old == signal.SIG_IGN:
            continue
        prev[num] = old
        signal.signal(num, handler)


def _compare(ws, base_sha, rid, cmd, tmo, wt, errors):
    try:  # hooks off: the repo's post-checkout hook must not alter the start state the base run sees
        _git_wt(ws, ["-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", wt, base_sha])
    except footprint.CaptureError as exc:
        errors.append("regression %s: cannot create the start-state worktree: %s" % (rid, exc))
        return None
    try:
        base_rc, base_out = run_shell(cmd, wt, tmo)
        tip_rc, tip_out = run_shell(cmd, ws, tmo)
    except IntegrateError as exc:
        errors.append("regression %s: %s" % (rid, exc))
        return None
    late = [side for side, rc in (("base", base_rc), ("tip", tip_rc)) if rc is None]
    if late:
        errors.append("regression %s: timed out after %ds at %s" % (rid, tmo, " and ".join(late)))
        return None
    return {"regression_id": rid, "base_exit": base_rc, "tip_exit": tip_rc, "base_stdout_sha256": _sha(base_out),
            "tip_stdout_sha256": _sha(tip_out), "intended_change_ref": None}


def _run_regression(ws, base_sha, rid, cmd, tmo, errors):
    """One differential row, or None (errors[] row) when either side cannot produce an integer exit. The worktree
    lives in a fresh temp dir that must resolve outside the workspace (else an errors[] row: a nested start tree
    would be seen by the tip run). A finally block always removes it — after a failing command, a timeout, an
    exception, KeyboardInterrupt or a trapped SIGTERM/SIGHUP — and only then re-delivers a trapped signal to the
    previous handler (a default-disposition SIGTERM then ends the process as it would have)."""
    tmp = os.path.realpath(tempfile.mkdtemp(prefix=WORKTREE_PREFIX))
    root = os.path.realpath(ws)
    if os.path.commonpath([tmp, root]) == root:
        shutil.rmtree(tmp, ignore_errors=True)
        errors.append("regression %s: the temp dir %s is inside the workspace; refusing to nest the start-state "
                      "worktree there (point TMPDIR outside the repository)" % (rid, os.path.dirname(tmp)))
        return None
    wt = os.path.join(tmp, "wt")
    trap, prev = {"armed": True}, {}
    try:
        _trap_signals(trap, prev)
        return _compare(ws, base_sha, rid, cmd, tmo, wt, errors)
    except _Interrupted:
        return None
    finally:
        trap["armed"] = False
        _drop_worktree(ws, tmp, wt, errors, rid)
        for num, old in prev.items():
            signal.signal(num, old)
        got = trap.get("signums", [])
        for num in sorted(set(got), key=got.index):
            errors.append("regression %s: signal %d received; its worktree was removed before the signal was "
                          "re-delivered" % (rid, num))
            os.kill(os.getpid(), num)


def differential(cfg, ws, mode, blast, errors):
    """(rows, none_reason): each regression command at the start state (a detached worktree of base_sha, always
    removed) and at the end state (the workspace root)."""
    if cfg is None:
        return [], "no blast config, so no regression commands to compare"
    regs = _list(cfg.get("regression_commands"))
    if not regs:
        why = cfg.get("regression_none_reason")
        return [], why if isinstance(why, str) and why.strip() else "blast config declares no regression_commands"
    if mode != "git":
        return [], SNAPSHOT_NONE_REASON
    if not blast.get("base_sha"):
        errors.append("differential: git mode without a base_sha; the start tree cannot be rebuilt")
        return [], "no base_sha to rebuild the start tree"
    rows = []
    for r in regs:
        parsed = _regression(r)
        if parsed is None:
            errors.append("regression %r: malformed (id, command and integer timeout_s >= 1 required)"
                          % (r.get("id") if isinstance(r, dict) else r,))
            continue
        row = _run_regression(ws, blast["base_sha"], parsed[0], parsed[1], parsed[2], errors)
        if row is not None:
            rows.append(row)
    return rows, (None if rows else "no regression command produced a base and a tip result; see errors[]")


# --- weakened-test detection ---------------------------------------------------------------------------------
_DEF_TEST = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+test_", re.M)
# skip markers, counted per non-comment line: pytest.mark.skip(if), pytest.skip, unittest.skip(If|Unless),
# skipTest (self.skipTest), and a bare imported @skip / @skipIf / @skipUnless decorator.
_SKIP = re.compile(r"\b(?:pytest\.mark\.skip|pytest\.skip|unittest\.skip|skipTest\b)"
                   r"|^[ \t]*@[ \t]*(?:skip|skipIf|skipUnless)\b")


def _tsv_rows(text):
    """{fixture: [(expected_exit, pin), ...] in file order}; blank and #-comment lines ignored."""
    rows = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = (line.split("\t") + ["", "", ""])[:4]
        rows.setdefault(cols[0], []).append((cols[1].strip(), cols[2].strip()))
    return rows


def _leftover(rows, cancelled):
    """rows (in order) minus the multiset `cancelled`."""
    budget, out = collections.Counter(cancelled), []
    for r in rows:
        if budget[r] > 0:
            budget[r] -= 1
        else:
            out.append(r)
    return out


def _tip_text(ws, path):
    full = os.path.join(ws, path)
    if os.path.islink(full) or not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def _weak_tsv(sid, path, base, tip):
    """Rows are matched per fixture as a MULTISET of (expected_exit, pin): identical rows cancel first, so adding
    or reordering rows (also rows that share a fixture) reports nothing. Each leftover base row is then paired with
    a leftover tip row of its fixture — first one with the same pin and another exit, then one with the same exit
    and an empty pin, then one with the same exit, then any — and reported as tsv-exit-changed and/or
    tsv-pin-dropped / tsv-pin-changed; with no leftover tip row left it is tsv-row-removed."""
    if base is None:
        return []  # a new expectations file adds rows; it cannot weaken any
    b, t = _tsv_rows(base), _tsv_rows(tip or "")
    out = []
    for fx, brows in b.items():
        trows = t.get(fx, [])
        common = collections.Counter(brows) & collections.Counter(trows)
        left_t = _leftover(trows, common)
        for bexit, bpin in _leftover(brows, common):
            where = "%s %s: fixture %s" % (sid, path, fx)
            if len(brows) > 1:  # name the row when the fixture has several
                where += " (row: exit %s, pin %r)" % (bexit or "''", bpin)
            pick = None
            for fits in (lambda e, p: p == bpin and e != bexit, lambda e, p: e == bexit and not p,
                         lambda e, p: e == bexit, lambda e, p: True):
                pick = next((r for r in left_t if fits(*r)), None)
                if pick is not None:
                    break
            if pick is None:
                out.append(("tsv-row-removed", "%s row removed%s" % (where, " (file deleted)" if tip is None else "")))
                continue
            left_t.remove(pick)
            texit, tpin = pick
            if texit != bexit:
                out.append(("tsv-exit-changed", "%s expected exit %s -> %s" % (where, bexit or "''", texit or "''")))
            if bpin and not tpin:
                out.append(("tsv-pin-dropped", "%s pin %r dropped" % (where, bpin)))
            elif bpin and tpin != bpin:
                out.append(("tsv-pin-changed", "%s pin %r -> %r" % (where, bpin, tpin)))
    return out


def _skip_scopes(text):
    """(Counter {scope: skip markers}, set of test function scopes, total). A scope is the class-qualified name of
    the def test_* whose span (decorators included) holds the marker, else '<module>' (class decorators,
    pytestmark, module-level skips). '#' comment lines are not counted. The Counter and set are None when the
    file does not parse as Python (only the total is then compared)."""
    lines = text.splitlines()
    owner, names = {}, set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        tree = None

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                names.add(prefix + child.name)
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                for n in range(start, (child.end_lineno or child.lineno) + 1):
                    owner[n] = prefix + child.name
            else:
                visit(child, prefix + child.name + "." if isinstance(child, ast.ClassDef) else prefix)

    if tree is not None:
        visit(tree, "")
    count = collections.Counter()
    for n, line in enumerate(lines, 1):
        if not line.lstrip().startswith("#"):
            hits = len(_SKIP.findall(line))
            if hits:
                count[owner.get(n, "<module>")] += hits
    total = sum(count.values())
    return (count, names, total) if tree is not None else (None, None, total)


def _weak_glob(sid, path, base_text, tip_text):
    if tip_text is None:
        return [("test-file-deleted", "%s: %s test file deleted" % (sid, path))]
    out = []
    bn, tn = len(_DEF_TEST.findall(base_text)), len(_DEF_TEST.findall(tip_text))
    if tn < bn:
        out.append(("fewer-test-functions", "%s: %s def test_ count %d -> %d" % (sid, path, bn, tn)))
    (bc, bnames, bs), (tc, tnames, ts) = _skip_scopes(base_text), _skip_scopes(tip_text)
    # per scope present on both sides: a marker moved onto another existing test is a newly skipped test even when
    # the file's total is unchanged; a NEW test arriving with a skip is still caught by the total rising.
    newly = sorted(s for s in ({"<module>"} | (bnames & tnames)) if tc[s] > bc[s]) if bc is not None and \
        tc is not None else []
    if ts > bs or newly:
        out.append(("skip-added", "%s: %s skip markers %d -> %d%s" % (sid, path, bs, ts, " (newly skipped: %s)"
                                                                      % ", ".join(newly) if newly else "")))
    return out


def test_weakening(cfg, ws, mode, blast, errors):
    """Weakened-test rows over blast-config test_surfaces[], base = base_sha's tree, tip = the workspace."""
    surfaces = [s for s in _list((cfg or {}).get("test_surfaces")) if isinstance(s, dict)]
    if not surfaces:
        return []
    if mode != "git" or not blast.get("base_sha"):
        errors.extend("test surface %s: no git base to compare (snapshot mode or no base_sha)" % s.get("id")
                      for s in surfaces)
        return []
    sha = blast["base_sha"]
    try:
        listed = footprint.git(ws, ["ls-tree", "-r", "-z", "--name-only", sha]).decode("utf-8", "surrogateescape")
    except footprint.CaptureError as exc:
        errors.extend("test surface %s: cannot list the base tree: %s" % (s.get("id"), exc) for s in surfaces)
        return []
    base_files = sorted({p for p in listed.split("\0") if p and not frame_match.is_unsafe_path(p)})
    base_set = set(base_files)
    found = []
    for s in surfaces:
        sid, kind, pat = s.get("id"), s.get("kind"), s.get("path")
        if not (isinstance(sid, str) and isinstance(pat, str) and kind in ("expectations-tsv", "test-glob")) or (
                frame_match.is_unsafe_path(pat) if kind == "expectations-tsv" else not frame_match.is_valid_pattern(pat)):
            errors.append("test surface %r: malformed (id, kind expectations-tsv|test-glob, safe path required)" % (sid,))
            continue
        paths = [pat] if kind == "expectations-tsv" else [p for p in base_files if frame_match.match_any_pattern(p, [pat])]
        if not paths:  # a glob that matched nothing at base: fine if the workspace has (only new) matches
            try:
                now = footprint.git(ws, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
            except footprint.CaptureError as exc:
                errors.append("test surface %s: cannot list the workspace: %s" % (sid, exc))
                continue
            if not [p for p in now.decode("utf-8", "surrogateescape").split("\0")
                    if p and frame_match.match_any_pattern(p, [pat])]:
                errors.append("test surface %s: pattern %r matches no file at base_sha or in the workspace "
                              "(misconfigured surface?)" % (sid, pat))
        for p in paths:
            try:
                base = (footprint.git(ws, ["cat-file", "blob", "%s:%s" % (sha, p)]).decode("utf-8", "replace")
                        if p in base_set else None)
                tip = _tip_text(ws, p)
            except (footprint.CaptureError, OSError) as exc:
                errors.append("test surface %s: cannot read %s: %s" % (sid, p, exc))
                continue
            if base is None and tip is None:
                errors.append("test surface %s: %s exists neither at base_sha nor in the workspace (misconfigured "
                              "surface?)" % (sid, p))
                continue
            found.extend(_weak_tsv(sid, p, base, tip) if kind == "expectations-tsv" else _weak_glob(sid, p, base, tip))
    return [{"kind": k, "detail": d, "intended_change_ref": None} for k, d in found]


# --- assemble / write ----------------------------------------------------------------------------------------
def integrate(run_dir, config=None, timeout=DEFAULT_REPLAY_TIMEOUT):
    rd = os.path.realpath(run_dir)
    fsm = _load(os.path.join(rd, "fsm-state.json"), "fsm-state.json")
    blast = fsm.get("blast") if isinstance(fsm, dict) else None
    if not isinstance(blast, dict) or blast.get("mode") not in ("git", "snapshot"):
        raise IntegrateError("fsm-state.json has no git/snapshot blast start state")
    sha = blast.get("base_sha")
    if sha is not None and not (isinstance(sha, str) and _COMMIT.fullmatch(sha)):
        raise IntegrateError("fsm-state.blast.base_sha %.80r is neither null nor a 40/64-hex commit id; refusing "
                             "to pass it to git" % (sha,))
    try:
        ws, mode = footprint.resolve_workspace(rd)
        errors = []
        union, base_digest, tip_digest = whole_run_diff(rd, ws, mode, blast, errors)
    except footprint.CaptureError as exc:
        raise IntegrateError(str(exc))
    unowned, multi = ownership(rd, union, errors)
    cfg = load_config(rd, ws, config, errors)
    doc = {"base_sha": blast.get("base_sha"), "base_tree_digest": base_digest, "tip_tree_digest": tip_digest,
           "union_changes": union, "unowned_writes": unowned, "multi_writer_paths": multi,
           "replay": replay(ws, passed_command_checks(rd, errors), timeout, errors)}
    diff_rows, none_reason = differential(cfg, ws, mode, blast, errors)
    if diff_rows:
        doc["differential"] = diff_rows
    else:
        doc["differential_none_reason"] = none_reason
    doc["test_weakening"] = test_weakening(cfg, ws, mode, blast, errors)
    doc["censuses"] = censuses(cfg, ws, mode, blast, timeout, errors)
    doc["errors"] = errors
    return doc


def write_doc(run_dir, doc):
    """Validate (when the optional jsonschema backend is present) and write integration.json + sidecar."""
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if jsonschema is not None:
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            schema = json.load(fh)
        problems = sorted(e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc))
        if problems:
            raise IntegrateError("integration.json would not validate: %s" % problems[0])
    data = (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("ascii")
    path = os.path.join(os.path.realpath(run_dir), "integration.json")
    footprint._atomic_write(path, data)
    footprint._atomic_write(path + ".sha256", ("%s  integration.json\n" % _sha(data)).encode("ascii"))


def explain(run_dir, mapping_path):
    rd = os.path.realpath(run_dir)
    path = os.path.join(rd, "integration.json")
    doc = _load(path, "integration.json")
    if not isinstance(doc, dict):
        raise IntegrateError("integration.json is missing or not a JSON object")
    mapping = _load(mapping_path, "mapping")
    if not isinstance(mapping, dict) or set(mapping) - {"differential", "test_weakening"} or not all(
            isinstance(v, dict) and all(isinstance(r, str) for r in v.values()) for v in mapping.values()):
        raise IntegrateError("mapping must be {differential: {id: ref}, test_weakening: {index: ref}}")
    graph = _load(os.path.join(rd, "graph.json"), "graph.json")
    allowed = {ic for u in _list((graph or {}).get("units") if isinstance(graph, dict) else None) if isinstance(u, dict)
               for ic in _list((u.get("frame") or {}).get("intended_changes") if isinstance(u.get("frame"), dict) else None)
               if isinstance(ic, str)}
    for section in ("differential", "test_weakening"):
        rows = _list(doc.get(section))
        for key, ref in (mapping.get(section) or {}).items():
            if ref not in allowed:
                raise IntegrateError("%s %s: ref %r is not verbatim in any graph unit's frame.intended_changes"
                                     % (section, key, ref))
            if section == "differential":
                hits = [r for r in rows if r.get("regression_id") == key]
            else:
                hits = [rows[int(key)]] if _INDEX.fullmatch(key) and int(key) < len(rows) else []
            if not hits:
                raise IntegrateError("%s %s: no such row in integration.json" % (section, key))
            for r in hits:
                r["intended_change_ref"] = ref
    write_doc(rd, doc)


# --- self-test -----------------------------------------------------------------------------------------------
def _self_test():
    results = []

    def case(rule, polarity, ok):
        results.append(bool(ok))
        print("case %s %s %s" % (rule, polarity, "ok" if ok else "FAIL"))

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="dag-integrate-selftest-"))
    saved_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
    saved_tempdir, saved_git_timeout = tempfile.tempdir, os.environ.get("DAG_BLAST_GIT_TIMEOUT")
    os.environ["GIT_CEILING_DIRECTORIES"] = tmp  # a snapshot-mode workspace under tmp must never find a repo above
    try:
        # hermetic: every temp dir (worktrees included) lands in a private dir, so a leftover from another run or a
        # concurrent self-test in the shared temp dir can neither fail nor satisfy the leak assertions below.
        private = os.path.join(tmp, "tmp")
        os.mkdir(private)
        tempfile.tempdir = private
        ws = os.path.join(tmp, "repo")
        rd = os.path.join(ws, ".wip", "run")
        os.makedirs(rd)

        def put(rel, text, root=None):
            full = os.path.join(root or ws, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text if isinstance(text, str) else json.dumps(text))

        def g(*args):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
                           + list(args), cwd=ws, check=True, capture_output=True, stdin=subprocess.DEVNULL)

        put("a.txt", "old\n")
        put("b.txt", "b\n")
        put("c.txt", "c\n")
        put("census.json", {"sites": [{"kind": "k", "src": "x"}, {"kind": "k", "src": "y"}]})
        put("count.txt", "noise 9\n2\n")
        put("r_old.txt", "rename me\n" * 8)
        g("init", "-q")
        g("add", "-A")
        g("commit", "-q", "-m", "base")
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws, capture_output=True, text=True,
                                  check=True).stdout.strip()
        blast = {"mode": "git", "base_sha": base_sha, "workspace_root": os.path.realpath(ws),
                 "base_tree_digest": footprint.tree_digest(ws, rd)["digest"]}
        put(".wip/run/fsm-state.json", {"blast": blast})
        put("a.txt", "new\n")
        put("b.txt", "b2\n")
        put("c.txt", "c2\n")
        put("census.json", {"sites": [{"kind": "k", "src": "y"}, {"kind": "k", "src": "z"}, {"kind": "k", "src": "z"}]})
        put("count.txt", "1\n")
        os.rename(os.path.join(ws, "r_old.txt"), os.path.join(ws, "r_new.txt"))
        fp = lambda uid, paths: {"unit_id": uid, "changes": [{"path": p, "from_path": None} for p in paths],
                                 "capture_error": None}
        u01 = fp("U01", ["a.txt", "b.txt"])
        u01["changes"].append({"path": "r_new.txt", "from_path": "r_old.txt"})  # a rename owns both of its sides
        put(".wip/run/units/U01/footprint.json", u01)
        put(".wip/run/units/U02/footprint.json", fp("U02", ["a.txt", "census.json", "count.txt"]))
        put(".wip/run/units/U01/brief.json", {"case_set": [
            {"id": "C1", "check_form": "command", "check": "grep -q b2 b.txt"},
            {"id": "C2", "check_form": "command", "check": "grep -q old a.txt"},
            {"id": "C3", "check_form": "command", "check": "true"},
            {"id": "C4", "check_form": "locator", "check": "a.txt:1"}]})
        put(".wip/run/units/U01/debrief.json", {"case_set_discharge": [
            {"id": "C1", "origin": "orchestrator", "outcome": "discharged"},
            {"id": "C2", "origin": "orchestrator", "outcome": "discharged"},
            {"id": "C3", "origin": "orchestrator", "outcome": "vacuous"},
            {"id": "C4", "origin": "orchestrator", "outcome": "discharged"}]})
        put(".wip/run/blast-config.json", {"censuses": [
            {"id": "sites", "command_template": "cat {root}/census.json", "must_not_increase": True},
            {"id": "count", "command_template": "cat {root}/count.txt", "must_not_increase": True}]})
        put(".wip/run/graph.json", {"units": [{"id": "U01", "frame": {"intended_changes": ["a.txt now says new"]}}]})

        doc = integrate(rd)
        write_doc(rd, doc)
        paths = {r["path"] for r in doc["union_changes"]}
        case("unowned_write", "pos", "c.txt" in doc["unowned_writes"] and "c.txt" in paths)
        rh = _sha(("rename me\n" * 8).encode())
        case("unowned_write", "neg", not {"a.txt", "b.txt", "census.json", "r_old.txt", "r_new.txt"}
             & set(doc["unowned_writes"]) and {"a.txt", "b.txt"} <= paths
             and {"path": "r_old.txt", "status": "D", "sha256_base": rh, "sha256_tip": None} in doc["union_changes"]
             and {"path": "r_new.txt", "status": "A", "sha256_base": None, "sha256_tip": rh} in doc["union_changes"])
        case("multi_writer", "pos", {"path": "a.txt", "units": ["U01", "U02"]} in doc["multi_writer_paths"])
        case("multi_writer", "neg", not [m for m in doc["multi_writer_paths"] if m["path"] != "a.txt"])
        rep = {r["case_id"]: r["exit_code"] for r in doc["replay"]}
        case("replay", "pos", rep.get("C2") not in (None, 0))
        case("replay", "neg", rep.get("C1") == 0 and "C3" not in rep and "C4" not in rep)
        cen = {c["id"]: c for c in doc["censuses"]}
        case("census", "pos", (cen.get("sites") or {}).get("added") == 2 and cen["sites"]["closed"] == 1
             and cen["sites"]["base"] == 2 and cen["sites"]["tip"] == 3)
        case("census", "neg", (cen.get("count") or {}).get("added") == 0 and cen["count"]["closed"] == 1
             and not doc["errors"])
        # explain needs a differential row; simulate the later differential slot through the real writer.
        doc.pop("differential_none_reason")
        doc["differential"] = [{"regression_id": "r1", "base_exit": 0, "tip_exit": 1, "base_stdout_sha256": "0" * 64,
                                "tip_stdout_sha256": "1" * 64, "intended_change_ref": None}]
        write_doc(rd, doc)
        ipath = os.path.join(rd, "integration.json")
        put(".wip/run/map_bad.json", {"differential": {"r1": "a.txt now says NEW"}})
        before = open(ipath, "rb").read()
        try:
            explain(rd, os.path.join(rd, "map_bad.json"))
            refused = False
        except IntegrateError:
            refused = True
        case("explain", "neg", refused and open(ipath, "rb").read() == before)
        put(".wip/run/map_ok.json", {"differential": {"r1": "a.txt now says new"}})
        explain(rd, os.path.join(rd, "map_ok.json"))
        after = open(ipath, "rb").read()
        side = open(ipath + ".sha256").read()
        case("explain", "pos", json.loads(after)["differential"][0]["intended_change_ref"] == "a.txt now says new"
             and side == "%s  integration.json\n" % _sha(after))

        # snapshot mode (no git): the base is the earliest pre snapshot, verified against the start digest, so an
        # edit made after the start state but before that snapshot is an errors[] row, never silently missing.
        def snap_run(name, drift):
            sws = os.path.join(tmp, name)
            srd = os.path.join(sws, ".wip", "run")
            os.makedirs(srd)
            for rel, text in (("a.txt", "a\n"), ("d.txt", "d\n"), ("x.txt", "x\n")):
                put(rel, text, sws)
            put(".wip/run/fsm-state.json", {"blast": {
                "mode": "snapshot", "base_sha": None, "workspace_root": sws,
                "base_tree_digest": footprint.tree_digest(sws, srd)["digest"]}}, sws)
            put(".wip/run/blast-config.json", {"censuses": [], "regression_commands": [
                {"id": "R1", "command": "true", "timeout_s": 5, "compare": "exit"}]}, sws)
            if drift:
                put("x.txt", "x drifted before the wave\n", sws)
            footprint.write_snapshot(footprint.snapshot_path(srd, 1, None, "pre"),
                                     footprint.take_snapshot(srd, 1, None, "pre"))
            put("a.txt", "a2\n", sws)
            os.remove(os.path.join(sws, "d.txt"))
            put("n.txt", "n\n", sws)
            put(".wip/run/units/U01/footprint.json", fp("U01", ["a.txt", "d.txt", "n.txt"]), sws)
            return integrate(srd)

        h = lambda text: _sha(text.encode())
        want = [{"path": "a.txt", "status": "M", "sha256_base": h("a\n"), "sha256_tip": h("a2\n")},
                {"path": "d.txt", "status": "D", "sha256_base": h("d\n"), "sha256_tip": None},
                {"path": "n.txt", "status": "A", "sha256_base": None, "sha256_tip": h("n\n")}]
        drifted = snap_run("snap_drift", True)
        case("unowned_write", "pos", [e for e in drifted["errors"] if "wave1.pre.json" in e
                                      and "base_tree_digest" in e] and len(drifted["errors"]) == 1)
        clean = snap_run("snap_clean", False)
        case("unowned_write", "neg", clean["errors"] == [] and clean["unowned_writes"] == []
             and clean["union_changes"] == want and clean["base_sha"] is None)

        # differential + weakening in their own git repo: base -> tip edits, real worktrees, real git.
        dws = os.path.join(tmp, "dw")
        drd = os.path.join(dws, ".wip", "run")
        os.makedirs(drd)
        dg = lambda *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                                           "commit.gpgsign=false"] + list(args), cwd=dws, check=True,
                                          capture_output=True, stdin=subprocess.DEVNULL)
        two = "def test_a():\n    pass\n\ndef test_b():\n    pass\n"
        for rel, text in (("v.txt", "old\n"), ("t/exp.tsv", "fa\t0\tok pin\nfb\t1\tFAIL x\nfc\t1\tFAIL y\nfd\t0\tkeep\n"),
                          ("t/same.tsv", "fa\t0\tp\n# c\nfb\t1\tq\n"), ("t/grow.tsv", "fa\t0\tp\n"),
                          ("tests/test_one.py", two), ("tests/test_two.py", two), ("tests/test_three.py", two),
                          ("tests/test_four.py", two), ("tests/test_five.py", two), ("other/test_x.py", two),
                          ("t/ins.tsv", "fx\t1\tPIN A\nother\t0\t\n"), ("t/swap.tsv", "fy\t1\tA\nfy\t0\tB\n"),
                          ("t/rm2.tsv", "fz\t1\tA\nfz\t0\tB\nfw\t1\tA\nfw\t0\tB\n"),
                          ("sk/test_move.py", "import pytest\n\n@pytest.mark.skip\n" + two),
                          ("sk/test_bare.py", "import unittest\nfrom unittest import skip\n\nclass T(unittest.TestCase):\n"
                                              "    def test_a(self):\n        pass\n\n    def test_b(self):\n        pass\n"),
                          ("sk/test_comment.py", two), (".gitattributes", "slow.dat filter=slow\n"), ("slow.dat", "s\n")):
            put(rel, text, dws)
        dg("init", "-q")
        dg("add", "-A")
        dg("commit", "-q", "-m", "base")
        dsha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dws, capture_output=True, text=True,
                              check=True).stdout.strip()
        dblast = {"mode": "git", "base_sha": dsha, "workspace_root": dws,
                  "base_tree_digest": footprint.tree_digest(dws, drd)["digest"]}
        put(".wip/run/fsm-state.json", {"blast": dblast}, dws)
        put("v.txt", "new\n", dws)
        put("t/exp.tsv", "fa\t1\tok pin\nfb\t1\t\nfd\t0\tother\n", dws)  # fc removed, fa exit, fb pin, fd pin
        put("t/same.tsv", "# moved\nfb\t1\tq\n\nfa\t0\tp\n", dws)  # reordered + comments only
        put("t/grow.tsv", "fa\t0\tp\nfz\t0\tnew\n", dws)  # added row only
        put("tests/test_one.py", "def test_a():\n    pass\n", dws)  # fewer def test_
        os.remove(os.path.join(dws, "tests", "test_two.py"))  # deleted
        put("tests/test_three.py", "import pytest\n\n@pytest.mark.skip\n" + two, dws)  # skip added
        put("tests/test_five.py", two + "\ndef test_c():\n    pass\n", dws)  # a test added
        put("tests/test_new.py", "import pytest\n\n@pytest.mark.skip\ndef test_n():\n    pass\n", dws)  # new file
        os.remove(os.path.join(dws, "other", "test_x.py"))  # outside the glob
        put("t/ins.tsv", "fx\t1\tPIN NEW\nfx\t1\tPIN A\nother\t0\t\n", dws)  # a pin row inserted ABOVE its twin
        put("t/swap.tsv", "fy\t0\tB\nfy\t1\tA\n", dws)  # two rows of one fixture swapped
        put("t/rm2.tsv", "fz\t0\tB\nfw\t1\tA\nfw\t1\tB\n", dws)  # one fz row removed, one fw row's exit changed
        put("sk/test_move.py", "import pytest\n\ndef test_a():\n    pass\n\n@pytest.mark.skip\ndef test_b():\n    pass\n",
            dws)  # the skip moved onto another test: the file total stays 1
        put("sk/test_bare.py", "import unittest\nfrom unittest import skip\n\nclass T(unittest.TestCase):\n"
            "    @skip('x')\n    def test_a(self):\n        pass\n\n    def test_b(self):\n        self.skipTest('y')\n",
            dws)  # bare imported @skip and skipTest
        put("sk/test_comment.py", "# @pytest.mark.skip  (kept as a comment)\n" + two + "# self.skipTest('later')\n",
            dws)  # comments only
        put(".wip/run/blast-config.json", {"censuses": [], "regression_commands": [
            {"id": "R0", "command": "echo same", "timeout_s": 30, "compare": "exit+stdout"},
            {"id": "R1", "command": "cat v.txt; test \"$(cat v.txt)\" = new", "timeout_s": 30,
             "compare": "exit+stdout"}], "test_surfaces": [
            {"id": "T1", "kind": "expectations-tsv", "path": "t/exp.tsv"},
            {"id": "T3", "kind": "expectations-tsv", "path": "t/same.tsv"},
            {"id": "T4", "kind": "expectations-tsv", "path": "t/grow.tsv"},
            {"id": "T2", "kind": "test-glob", "path": "tests/test_*.py"}]}, dws)

        def wt_state():
            listed = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=dws, capture_output=True,
                                    text=True, check=True).stdout.count("worktree ")
            admin = os.path.join(dws, ".git", "worktrees")
            left = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith(WORKTREE_PREFIX)]
            return listed, bool(os.path.isdir(admin) and os.listdir(admin)), left

        clean_wt = wt_state()
        ddoc = integrate(drd)
        write_doc(drd, ddoc)  # schema-validated when the optional backend is present
        drow = {r["regression_id"]: r for r in ddoc.get("differential", [])}
        r0, r1 = drow.get("R0") or {}, drow.get("R1") or {}
        case("differential", "pos", r1.get("base_exit") == 1 and r1.get("tip_exit") == 0
             and r1.get("base_stdout_sha256") == _sha(b"old\n") and r1.get("tip_stdout_sha256") == _sha(b"new\n")
             and r1.get("intended_change_ref", "x") is None and ddoc["errors"] == [])
        case("differential", "neg", r0.get("base_exit") == 0 == r0.get("tip_exit")
             and r0.get("base_stdout_sha256") == r0.get("tip_stdout_sha256") == _sha(b"same\n")
             and "differential_none_reason" not in ddoc and wt_state() == clean_wt == (1, False, []))
        weak = {(w["kind"], w["detail"].split(":")[0] + (":" + w["detail"].split("fixture ")[1].split(" ")[0]
                                                           if "fixture " in w["detail"] else ""))
                for w in ddoc["test_weakening"]}
        tsv = {k for k in weak if k[0].startswith("tsv-")}
        case("weakening_tsv", "pos", {("tsv-row-removed", "T1 t/exp.tsv:fc"), ("tsv-exit-changed", "T1 t/exp.tsv:fa"),
                                      ("tsv-pin-dropped", "T1 t/exp.tsv:fb"),
                                      ("tsv-pin-changed", "T1 t/exp.tsv:fd")} == tsv)
        case("weakening_tsv", "neg", not [k for k in weak if k[1].startswith(("T3", "T4"))] and len(tsv) == 4)
        glob_rows = sorted((w["kind"], w["detail"].split(" ")[1]) for w in ddoc["test_weakening"]
                           if not w["kind"].startswith("tsv-"))
        case("weakening_glob", "pos", glob_rows == [("fewer-test-functions", "tests/test_one.py"),
                                                    ("skip-added", "tests/test_three.py"),
                                                    ("test-file-deleted", "tests/test_two.py")])
        case("weakening_glob", "neg", len(ddoc["test_weakening"]) == 7 and not [
            w for w in ddoc["test_weakening"] if any(n in w["detail"] for n in ("test_four", "test_five", "test_new",
                                                                                "other/"))])
        # rows sharing a fixture form a multiset: inserting a row above its twin or swapping two is not weakening,
        # removing one of them is; a skip moved onto another test, a bare @skip and skipTest are weakening.
        werrs = []
        extra = test_weakening({"test_surfaces": [
            {"id": "TI", "kind": "expectations-tsv", "path": "t/ins.tsv"},
            {"id": "TS", "kind": "expectations-tsv", "path": "t/swap.tsv"},
            {"id": "TR", "kind": "expectations-tsv", "path": "t/rm2.tsv"},
            {"id": "TK", "kind": "test-glob", "path": "sk/test_*.py"}]}, dws, "git", dblast, werrs)
        by = lambda sid: sorted((w["kind"], w["detail"]) for w in extra if w["detail"].startswith((sid + " ", sid + ":")))
        case("weakening_tsv", "neg", by("TI") == [] and werrs == [])
        case("weakening_tsv", "neg", by("TS") == [])
        case("weakening_tsv", "pos", by("TR") == [
            ("tsv-exit-changed", "TR t/rm2.tsv: fixture fw (row: exit 0, pin 'B') expected exit 0 -> 1"),
            ("tsv-row-removed", "TR t/rm2.tsv: fixture fz (row: exit 1, pin 'A') row removed")])
        case("weakening_glob", "pos", by("TK") == [
            ("skip-added", "TK: sk/test_bare.py skip markers 0 -> 2 (newly skipped: T.test_a, T.test_b)"),
            ("skip-added", "TK: sk/test_move.py skip markers 1 -> 1 (newly skipped: test_b)")])
        case("weakening_glob", "neg", not [w for w in extra if "test_comment" in w["detail"]] and len(extra) == 4)
        merrs = []  # a misconfigured surface is an errors[] row, never an empty green
        mis = test_weakening({"test_surfaces": [{"id": "TM", "kind": "expectations-tsv", "path": "t/EXP.tsv"},
                                                {"id": "TG", "kind": "test-glob", "path": "test/test_*.py"}]},
                             dws, "git", dblast, merrs)
        case("weakening_tsv", "pos", mis == [] and len(merrs) == 2
             and merrs[0].startswith("test surface TM: t/EXP.tsv exists neither at base_sha nor in the workspace"))
        case("weakening_glob", "pos", len(merrs) == 2
             and merrs[1].startswith("test surface TG: pattern 'test/test_*.py' matches no file at base_sha"))
        case("snapshot_none_reason", "pos", clean.get("differential_none_reason") == SNAPSHOT_NONE_REASON
             and "differential" not in clean and clean["errors"] == [])
        case("snapshot_none_reason", "neg", "differential_none_reason" not in ddoc and len(drow) == 2)

        # cleanup after a failing command, after a timeout, and on KeyboardInterrupt — each in isolation.
        def one(cmd, tmo):
            errs = []
            rows, why = differential({"regression_commands": [{"id": "RX", "command": cmd, "timeout_s": tmo,
                                                               "compare": "exit"}]}, dws, "git", dblast, errs)
            return rows, why, errs, wt_state()

        rows, why, errs, state = one("echo f; exit 3", 30)
        case("worktree_cleanup", "pos", [(r["base_exit"], r["tip_exit"]) for r in rows] == [(3, 3)] and errs == []
             and state == clean_wt)
        t0 = time.monotonic()
        rows, why, errs, state = one("sleep 30", 1)
        case("worktree_cleanup", "pos", rows == [] and why and len(errs) == 1 and errs[0].startswith("regression RX: ")
             and "timed out after 1s at base and tip" in errs[0] and state == clean_wt and time.monotonic() - t0 < 20)
        real_run_shell = run_shell

        def interrupted(command, cwd, timeout):
            raise KeyboardInterrupt

        globals()["run_shell"] = interrupted
        try:
            one("true", 5)
            propagated = False
        except KeyboardInterrupt:
            propagated = True
        finally:
            globals()["run_shell"] = real_run_shell
        case("worktree_cleanup", "neg", propagated and wt_state() == clean_wt)

        # the add itself interrupted after it registered the worktree: nothing may stay registered or locked.
        real_git_wt = _git_wt

        def add_then_interrupt(ws_, args, timeout=None):
            got = real_git_wt(ws_, args, timeout)
            if "add" in args:
                raise KeyboardInterrupt
            return got

        globals()["_git_wt"] = add_then_interrupt
        try:
            one("true", 5)
            propagated = False
        except KeyboardInterrupt:
            propagated = True
        finally:
            globals()["_git_wt"] = real_git_wt
        case("worktree_cleanup", "neg", propagated and wt_state() == clean_wt)

        # the add times out mid-checkout (a slow smudge filter, DAG_BLAST_GIT_TIMEOUT=1): its whole process group is
        # killed (the filter never reaches its `touch`), the 'initializing' lock is cleared, nothing is left.
        late_mark = os.path.join(tmp, "smudge_survived")
        dg("config", "filter.slow.smudge", "sleep 2; touch %s; cat" % shlex.quote(late_mark))
        os.environ["DAG_BLAST_GIT_TIMEOUT"] = "1"
        t0 = time.monotonic()
        try:
            rows, why, errs, state = one("true", 5)
        finally:
            os.environ.pop("DAG_BLAST_GIT_TIMEOUT", None)
            dg("config", "--unset", "filter.slow.smudge")
        time.sleep(max(0.0, 2.6 - (time.monotonic() - t0)))
        case("worktree_cleanup", "pos", rows == [] and len(errs) == 1 and "cannot create the start-state worktree"
             in errs[0] and "process group was killed" in errs[0] and state == clean_wt == wt_state()
             and not os.path.exists(late_mark) and time.monotonic() - t0 < 15)

        # a default-style SIGTERM while the base command runs: the trap runs the cleanup, kills the command's group
        # (the heartbeat stops) and re-delivers the signal to the previous handler.
        hb, started, got_sig = os.path.join(tmp, "hb"), os.path.join(tmp, "started"), []
        old_term = signal.signal(signal.SIGTERM, lambda num, frame: got_sig.append(num))

        def fire():
            for _ in range(400):
                if os.path.exists(started):
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                time.sleep(0.05)

        watcher = threading.Thread(target=fire, daemon=True)
        watcher.start()
        t0 = time.monotonic()
        try:
            rows, why, errs, state = one("touch %s; while :; do echo x >> %s; sleep 0.05; done"
                                         % (shlex.quote(started), shlex.quote(hb)), 60)
        finally:
            signal.signal(signal.SIGTERM, old_term)
        watcher.join(5)
        beat = os.path.getsize(hb) if os.path.exists(hb) else -1
        time.sleep(0.3)
        case("worktree_cleanup", "pos", got_sig == [signal.SIGTERM] and rows == [] and len(errs) == 1
             and "signal %d received" % signal.SIGTERM in errs[0] and state == clean_wt and beat > 0
             and os.path.getsize(hb) == beat and time.monotonic() - t0 < 20)

        # the repo's post-checkout hook must not run in the start-state worktree.
        hook = os.path.join(dws, ".git", "hooks", "post-checkout")
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        put(".git/hooks/post-checkout", "#!/bin/sh\necho HOOKRAN > \"$(pwd)/hook_marker\"\n", dws)
        os.chmod(hook, 0o755)
        try:
            rows, why, errs, state = one("cat hook_marker 2>/dev/null || echo NOHOOK", 30)
        finally:
            os.remove(hook)
        case("differential", "neg", [r["base_stdout_sha256"] for r in rows] == [_sha(b"NOHOOK\n")] and errs == []
             and state == clean_wt)

        # a temp dir that resolves inside the workspace is refused (the tip run would see the nested start tree).
        inner = os.path.join(dws, "inner_tmp")
        os.mkdir(inner)
        tempfile.tempdir = inner
        try:
            rows, why, errs, state = one("true", 5)
        finally:
            tempfile.tempdir = private
        left_inner = os.listdir(inner)
        shutil.rmtree(inner)
        case("differential", "neg", rows == [] and len(errs) == 1 and "is inside the workspace" in errs[0]
             and left_inner == [] and wt_state() == clean_wt)
        def debrief_case(debrief):
            """passed_command_checks over one executed unit whose debrief.json holds `debrief`."""
            nrd = os.path.join(tmp, "nonobj-%d" % len(results))
            put("units/U05/brief.json", {"case_set": [{"id": "C1", "check_form": "command", "check": "true"}]}, nrd)
            put("units/U05/debrief.json", debrief, nrd)
            errs = []
            return passed_command_checks(nrd, errs), errs
        row = {"id": "C1", "origin": "orchestrator", "outcome": "discharged"}
        for shaped, kind in (([{"unit_id": "U05", "case_set_discharge": [row]}], "list"), ('"U05"', "string"),
                             (7, "number"), ("null", "null"), ("true", "boolean")):  # each file is valid JSON
            got, errs = debrief_case(shaped)
            case("non_object_debrief", "pos", got == [] and len(errs) == 1
                 and errs[0].startswith("U05: debrief.json is a JSON %s, not an object" % kind))
        got, errs = debrief_case({"unit_id": "U05", "case_set_discharge": [row]})
        case("non_object_debrief", "neg", got == [("U05", "C1", "true")] and errs == [])
        # an ABSENT debrief.json is "not executed": no replay row and no errors[] row (a present null is not absent)
        nrd = os.path.join(tmp, "nonobj-absent")
        put("units/U05/brief.json", {"case_set": [{"id": "C1", "check_form": "command", "check": "true"}]}, nrd)
        errs = []
        case("non_object_debrief", "neg", passed_command_checks(nrd, errs) == [] and errs == [])

        # --replay-timeout through main(): a discharged check slower than the window is an errors[] row naming its
        # unit and case and no replay row (exit 1); a longer window replays it; a bad value is refused untouched.
        tws = os.path.join(tmp, "rt")
        trd = os.path.join(tws, ".wip", "run")
        os.makedirs(trd)
        put("a.txt", "a\n", tws)
        for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
                           + list(args), cwd=tws, check=True, capture_output=True, stdin=subprocess.DEVNULL)
        put(".wip/run/fsm-state.json", {"blast": {
            "mode": "git", "workspace_root": tws, "base_tree_digest": footprint.tree_digest(tws, trd)["digest"],
            "base_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=tws, capture_output=True, text=True,
                                       check=True).stdout.strip()}}, tws)
        put(".wip/run/blast-config.json", {"censuses": [], "regression_commands": [],
                                           "regression_none_reason": "self-test"}, tws)
        put(".wip/run/units/U01/brief.json", {"case_set": [{"id": "C7", "check_form": "command",
                                                            "check": "sleep 1"}]}, tws)
        put(".wip/run/units/U01/debrief.json", {"case_set_discharge": [
            {"id": "C7", "origin": "orchestrator", "outcome": "discharged"}]}, tws)
        put(".wip/run/units/U01/footprint.json", fp("U01", []), tws)
        tpath = os.path.join(trd, "integration.json")

        def cli(*extra):
            saved_err, sys.stderr = sys.stderr, io.StringIO()
            try:
                rc = main([trd] + list(extra))
            finally:
                sys.stderr = saved_err
            return rc, open(tpath, "rb").read() if os.path.exists(tpath) else None

        rc, out = cli("--replay-timeout", "0.3")
        tdoc = json.loads(out or b"{}")
        case("replay_timeout", "pos", rc == 1 and tdoc.get("replay") == [] and tdoc.get("errors") == [
            "replay U01 C7: timed out after 0.3s (not re-run)"])
        rc, out = cli("--replay-timeout", "5")
        tdoc = json.loads(out or b"{}")
        case("replay_timeout", "neg", rc == 0 and tdoc.get("errors") == [] and tdoc.get("replay") == [
            {"unit_id": "U01", "case_id": "C7", "command": "sleep 1", "exit_code": 0}])
        refused = [cli("--replay-timeout", bad) for bad in ("0", "-1", "nan", "inf", "abc", "9" * 400)]
        case("replay_timeout", "pos", refused and all(r == (2, out) for r in refused))
    except Exception as exc:  # a crash is a failed self-test, reported, never swallowed
        print("self-test crashed: %s: %s" % (type(exc).__name__, exc))
        results.append(False)
    finally:
        if saved_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = saved_ceiling
        if saved_git_timeout is None:
            os.environ.pop("DAG_BLAST_GIT_TIMEOUT", None)
        else:
            os.environ["DAG_BLAST_GIT_TIMEOUT"] = saved_git_timeout
        tempfile.tempdir = saved_tempdir
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if results and all(results) else 1


def replay_timeout_arg(text):
    """Seconds from a --replay-timeout value: a finite number greater than 0 written as an integer or a decimal.
    Anything else (0, a negative number, nan, inf, a non-number) raises IntegrateError."""
    value = float(text) if re.fullmatch(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+", text) else None
    if value is None or not 0 < value < float("inf"):
        raise IntegrateError("--replay-timeout must be a finite number greater than 0 (an integer or a decimal), "
                             "got %.40r" % (text,))
    return value


def main(argv):
    ap = argparse.ArgumentParser(prog="integrate.py", description="Whole-run blast-radius integration check.")
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--config")
    ap.add_argument("--explain")
    ap.add_argument("--replay-timeout", metavar="SECONDS",
                    help="per-command window for replayed case_set checks and census commands: a finite number "
                         "greater than 0 (default %g s); regression commands keep their own timeout_s"
                         % DEFAULT_REPLAY_TIMEOUT)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    timeout = DEFAULT_REPLAY_TIMEOUT
    if a.replay_timeout is not None:
        try:
            timeout = replay_timeout_arg(a.replay_timeout)
        except IntegrateError as exc:  # refused before any file is read or written
            sys.stderr.write("integrate.py: %s\n" % exc)
            return 2
    if a.self_test:
        return _self_test()
    if not a.run_dir:
        ap.error("RUN_DIR is required")
    try:
        if a.explain:
            explain(a.run_dir, a.explain)
            return 0
        doc = integrate(a.run_dir, a.config, timeout)
        write_doc(a.run_dir, doc)
    except (IntegrateError, footprint.CaptureError) as exc:
        sys.stderr.write("integrate.py: %s\n" % exc)
        return 2
    for e in doc["errors"]:
        sys.stderr.write("integrate.py: error: %s\n" % e)
    return 1 if doc["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
