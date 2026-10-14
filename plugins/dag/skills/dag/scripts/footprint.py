#!/usr/bin/env python3
"""footprint.py — wave snapshots, content tree records and per-unit FILE footprints (blast radius).

Usage:
  footprint.py snapshot <RUN_DIR> --wave N [--label L] [--window-units U1,U2,...]
  footprint.py capture  <RUN_DIR> --wave N [--label L] [--unit U]
  footprint.py capture  <RUN_DIR> --unit U --pre-tree X --post-tree Y
  footprint.py digest   <WORKSPACE_ROOT> [--run-dir RD]
  footprint.py --self-test

Contract (format "dag-blast-snapshot/1"), restated here so this file is self-describing:

Workspace root and mode: <RUN_DIR>/fsm-state.json `blast.workspace_root` / `blast.mode` when present, else
`git -C <RUN_DIR> rev-parse --show-toplevel` (git mode), else snapshot mode rooted at the directory that contains
`.wip`. Excludes are always [".wip/**", "<run dir relative to the workspace root>/**"], matched with frame_match
(this file defines no matcher and does no fnmatch/glob-module matching). frame_match has no escape character, so
every '[', '*' and '?' in the run-dir path is written as the one-character class '[[]', '[*]', '[?]' (a run dir
named `r[1]` gives `r[[]1]/**`, which matches only the literal `r[1]/...`). Every git call runs with
GIT_OPTIONAL_LOCKS=0 and LC_ALL=C (LANGUAGE unset), so git's messages are English whatever the host locale — the
snapshot-mode fallback recognises "not a git repository" by that text.

Snapshot file <RUN_DIR>/blast/wave<N>[.<L>].<pre|post>.json:
  {"format", "mode": "git"|"snapshot", "wave", "label", "phase", "head", "tree", "workspace_root", "excludes",
   "entries": {"<posix path>": {"xy", "from_path", "sha256"[, "stored"]}}, "tool_version", "taken_at"}
  * git mode: `head` = HEAD; `tree` = the tree id of HEAD + working tree minus excludes, written through a
    TEMPORARY index (copy of the real index; `git add -A .`; `git rm -r -q --cached --ignore-unmatch` of each
    exclude directory as a literal path; `git write-tree`; temp index deleted) so HEAD, the real index and the
    working tree are never touched. The copy MUST KEEP THE REAL INDEX'S MTIME (shutil.copy2, never copyfile):
    git re-hashes a "racily clean" entry — one whose file mtime is not older than the index file's mtime —
    instead of trusting its cached stat data; a fresh mtime on the copy disables that check, and a same-size
    rewrite made in the same second as the last index write would then be captured with its OLD content. `entries` = every path `git status --porcelain=v1 -z --untracked-files=all` lists minus
    excludes (GIT_OPTIONAL_LOCKS=0 on every git call); a staged rename `R  NEW\\0OLD\\0` yields NEW with
    from_path OLD and OLD with xy "R-"; sha256 = the current bytes (a symlink: its link text, never followed),
    null when absent. Gitignored paths are invisible (git's own rules).
  * snapshot mode (no git): head/tree null; entries = every regular file under the workspace root minus
    excludes, xy "", and every hashed file is stored write-once at <RUN_DIR>/blast/objects/<sha256> (files over
    5 MiB are not stored and carry "stored": false) — the only source of BEFORE content without git.

Capture writes units/<U>/footprint.json and footprint.json.sha256 (`<hex>  footprint.json`):
  {unit_id, iteration, mode, base_ref, pre_snapshot_sha256, post_snapshot_sha256,
   changes[{path, status A|M|D|R|T, from_path, sha256_before, sha256_after}], unattributed[], capture_error,
   tool_version}
  * wave mode: pre = blast/wave<N>[.<L>].pre.json; post = blast/wave<N>[.<L>].post.json if it exists, else a fresh
    snapshot written there.
  * retry (`--unit U` with --wave, iteration 1 included: every such per-unit capture needs its <U>-i<k> pre
    snapshot), the retry-window contract: when the orchestrator dispatches the retry of U at iteration k it first
    runs `snapshot <RUN_DIR> --wave N --label <U>-i<k> [--window-units <ids>]`, which writes the
    retry pre snapshot blast/wave<N>.<U>-i<k>.pre.json. That retry pre snapshot records the window units (the units
    dispatched in the retry's window: U itself plus every comma-separated --window-units id) as the JSON string list
    "window_units"; U must be a unit of wave N and every window unit a graph.json unit id, else exit 2 and nothing
    is written. The capture (k = units/<U>/debrief.json iteration) writes a fresh post snapshot to
    blast/wave<N>[.<L>].<U>-i<k>.post.json and rewrites only U's footprint: changes stay CUMULATIVE from the wave's
    original pre snapshot (base_ref = its tree) filtered to U's frame, while unattributed is computed only over the
    retry window, from the <U>-i<k> pre snapshot to now. In that window a changed path is claimed only when U or a
    recorded window unit claims it (both sides of a rename), so a stray write into the frame of a unit that was not
    dispatched in the window stays unattributed, while a later wave's write made before the retry pre snapshot is
    not in the window at all. When the retry pre snapshot for U's current iteration is absent (none, or only an
    earlier iteration's), the retry capture writes capture_error and changes [] and never falls back to the wave
    window. A retry must never run inside another wave's window: a wave capture attributes only to its own wave's
    units, so a retry's writes made while another wave is open would read as unattributed in that wave's capture.
  * tree mode (--pre-tree/--post-tree): no snapshot files (both snapshot hashes null), every non-excluded change
    belongs to U,
    base_ref = the pre tree-ish as given.
  * changes are by CONTENT: git = `git diff-tree -r -z -M --raw <pre tree> <post tree>` (a HEAD move or a commit
    without content change yields nothing); hashes are sha256 of the blob bytes. snapshot = entry hash compare
    (A, M, D only). base_ref = pre tree id (git wave), the pre tree-ish (tree mode), null (snapshot).
  * attribution: a change belongs to every unit of the wave (graph.json waves[]) whose frame.modifies matches its
    path (for R also its from_path) via frame_match.match_any_pattern; a change no unit claims is listed in
    `unattributed` (both sides of a rename) in EVERY footprint the capture writes.
  * iteration = units/<U>/debrief.json iteration, else 1.
  * FAIL-CLOSED: a git error, a git timeout (DAG_BLAST_GIT_TIMEOUT seconds, default 120; a value that is not a
    finite number > 0 is itself an error), ANY stderr line from the two working-tree walks (git status, and git
    add -A under the temporary index) that is not an allowlisted benign notice — advisory "hint:" lines,
    line-ending conversion notices, the embedded-repository notice, and never a line ending in a strerror text
    such as ": Permission denied" — because git reports a working-tree path it cannot read on stderr and still
    exits 0 ("warning: could not open directory '<d>/'" for an unreadable directory, "<path>: Permission denied"
    for a tracked file under a listable but unsearchable directory, "warning: unable to access '<path>'": the
    listing is then incomplete, and an unrecognised line is treated the same way), a missing retry pre snapshot, an
    unsafe path (absolute, `..`, NUL, empty), an unreadable or vanishing workspace file or directory, any other I/O
    error, or an unreadable/forged snapshot (wrong format, mode or workspace; an entry whose sha256 is not null or
    64 lowercase hex, whose xy is not a string, or whose from_path is not null or a safe path) sets capture_error
    to a one-line reason and changes to [] — never a partial list — and the command exits 1; a snapshot that hits
    any of these refuses (exit 2, nothing written).

Digest: tree_digest(workspace_root, run_dir=None) / `digest` prints
  {"mode", "head", "tree", "digest": "sha256:<hex>"}; git: sha256("tree:<tree id>\\n") (content only);
  snapshot: sha256 over the sorted "<path>\\t<sha256>\\n" lines of every file minus excludes.
Exit codes: 0 ok, 1 capture written with capture_error, 2 usage error or failed snapshot/digest (nothing written).
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_match  # noqa: E402  (the single path matcher; never re-implemented here)

FORMAT = "dag-blast-snapshot/1"
TOOL_VERSION = "footprint.py/1"
DEFAULT_GIT_TIMEOUT = 120.0
STORE_MAX_BYTES = 5 * 1024 * 1024
_OID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ZERO_OID = re.compile(r"^0+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_UNIT = re.compile(r"^U[0-9]{2,}$")
_RETRY_LABEL = re.compile(r"^(U[0-9]{2,})-i([1-9][0-9]*)$")  # <U>-i<k>: the retry pre snapshot of U's iteration k


class CaptureError(Exception):
    """Any condition that must fail the operation closed (one-line reason)."""


def _oneline(text):
    return " ".join(str(text).split())[:300] or "unknown error"


def git_timeout():
    raw = os.environ.get("DAG_BLAST_GIT_TIMEOUT")
    if raw is None or raw == "":
        return DEFAULT_GIT_TIMEOUT
    try:
        val = float(raw)
    except ValueError:
        raise CaptureError("DAG_BLAST_GIT_TIMEOUT=%r is not a number" % raw)
    if not (math.isfinite(val) and val > 0):
        raise CaptureError("DAG_BLAST_GIT_TIMEOUT=%r must be a finite number > 0" % raw)
    return val


def git(cwd, args, extra_env=None, stdin_bytes=None):
    """Run git fail-closed: timeout, missing binary or non-zero rc all raise CaptureError. Returns stdout bytes."""
    return _git_run(cwd, args, extra_env, stdin_bytes).stdout


# The only stderr lines a working-tree walk may print without failing closed (LC_ALL=C wording): advisory "hint:"
# lines, line-ending conversion notices (core.autocrlf / text attributes; current and pre-2.37 wording) and git add's
# embedded-repository notice (the nested repository is recorded as a gitlink, as it always was).
_BENIGN_STDERR = re.compile(
    rb"^(?:hint:.*"
    rb"|warning: in the working copy of '.*', (?:CR)?LF will be replaced by (?:CR)?LF the next time Git touches it"
    rb"|warning: (?:CR)?LF will be replaced by (?:CR)?LF in .*"
    rb"|The file will have its original line endings in your working directory\.?"
    rb"|warning: adding embedded git repository: .*)$")
# ...but a line ending in a C-locale strerror text always fails closed, even when it otherwise looks benign (a
# directory literally named "hint: x" must not smuggle "hint: x/f.txt: Permission denied" past the allowlist).
_STRERROR_TAIL = re.compile(rb": (?:Permission denied|Operation not permitted|Input/output error|No such file or "
                            rb"directory|Not a directory|Too many levels of symbolic links|File name too long|"
                            rb"Stale file handle)$")


def _git_complete(cwd, args, extra_env=None):
    """git() for a call that walks the working tree (status, add -A). git reports a working-tree path it cannot read
    on stderr and still exits 0 — "warning: could not open directory '<d>/'", the perror form "<path>: Permission
    denied", "warning: unable to access '<path>': ..." — and the listing it returns is then incomplete. Rule: EVERY
    non-empty stderr line fails closed (CaptureError) unless it matches the small allowlist _BENIGN_STDERR and does
    not end in a strerror text, so an unreadable-path report git words differently tomorrow fails closed too
    instead of slipping through a denylist."""
    cp = _git_run(cwd, args, extra_env, None)
    for line in cp.stderr.splitlines():
        line = line.rstrip(b"\r")
        if line.strip() and (_STRERROR_TAIL.search(line) or not _BENIGN_STDERR.match(line)):
            raise CaptureError("git %s reported on stderr that it cannot fully read the working tree (any stderr line "
                               "outside the benign allowlist fails closed): %s"
                               % (args[0], _oneline(line.decode("utf-8", "replace"))))
    return cp.stdout


def _git_run(cwd, args, extra_env, stdin_bytes):
    timeout = git_timeout()
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")  # C locale: English messages (see _git_toplevel)
    env.pop("LANGUAGE", None)
    env.update(extra_env or {})
    try:
        cp = subprocess.run(["git"] + list(args), cwd=cwd, env=env, capture_output=True, timeout=timeout,
                            input=stdin_bytes, stdin=None if stdin_bytes is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise CaptureError("git %s did not finish within %gs (DAG_BLAST_GIT_TIMEOUT)" % (args[0], timeout))
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureError("git %s is unavailable (%s)" % (args[0], type(exc).__name__))
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip().splitlines()
        raise CaptureError("git %s failed (rc %d): %s" % (args[0], cp.returncode, _oneline(err[0] if err else "")))
    return cp


def _decode(raw):
    return raw.decode("utf-8", "surrogateescape")


def _check_safe(path):
    if frame_match.is_unsafe_path(path):
        raise CaptureError("unsafe path rejected: %r" % (path,))
    return path


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha_path(ws, rel):
    """sha256 of the current bytes at ws/rel; a symlink hashes its link text (never followed); None if absent.
    Any other I/O error (unreadable, vanished mid-read) raises CaptureError: fail closed, never a traceback."""
    full = os.path.join(ws, rel)
    try:
        st = os.lstat(full)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise CaptureError("cannot stat %r (%s)" % (rel, type(exc).__name__))
    try:
        if stat.S_ISLNK(st.st_mode):
            return _sha_bytes(os.fsencode(os.readlink(full)))
        if not stat.S_ISREG(st.st_mode):
            return None
        h = hashlib.sha256()
        with open(full, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError as exc:
        raise CaptureError("cannot read %r (%s)" % (rel, type(exc).__name__))


# --- workspace, excludes -------------------------------------------------------------------------------------
_GLOB_CLASS = {"[": "[[]", "*": "[*]", "?": "[?]"}


def _glob_literal(text):
    """A frame_match pattern that matches `text` literally (frame_match has no escape character; a class is one)."""
    return "".join(_GLOB_CLASS.get(c, c) for c in text)


def _glob_unliteral(pattern):
    """Inverse of _glob_literal; None when `pattern` holds a real glob (anything but '[[]', '[*]', '[?]')."""
    out, i = [], 0
    while i < len(pattern):
        if pattern[i] == "[" and pattern[i + 1:i + 3] in ("[]", "*]", "?]"):
            out.append(pattern[i + 1])
            i += 3
        elif pattern[i] in "[*?":
            return None
        else:
            out.append(pattern[i])
            i += 1
    return "".join(out)


def exclude_patterns(ws, run_dir=None):
    """The exclude patterns for a workspace: .wip/** plus the run directory (relative to ws, glob chars escaped)."""
    pats = [".wip/**"]
    if run_dir is not None:
        pats.append(_glob_literal(os.path.relpath(os.path.realpath(run_dir), ws).replace(os.sep, "/")) + "/**")
    return pats


def is_excluded(path, patterns):
    return frame_match.match_any_pattern(path, patterns)


def _exclude_dirs(patterns):
    return [p[:-3] for p in patterns if p.endswith("/**") and not frame_match.is_unsafe_path(p[:-3])]


def _git_toplevel(path):
    """Top level of the repository containing `path`, or None when it is not inside one. A timeout fails closed."""
    try:
        return os.path.realpath(_decode(git(path, ["rev-parse", "--show-toplevel"])).rstrip("\n"))
    except CaptureError as exc:
        msg = str(exc)
        if "(FileNotFoundError)" in msg or "not a git repository" in msg:
            return None  # no git binary / not inside a repository: the documented snapshot-mode fallback
        raise  # a timeout or any other git failure fails closed, never silently downgrades to snapshot mode


def resolve_workspace(run_dir):
    """(workspace_root, mode) for a run directory, per the contract above."""
    rd = os.path.realpath(run_dir)
    try:
        with open(os.path.join(rd, "fsm-state.json"), encoding="utf-8") as fh:
            blast = (json.load(fh) or {}).get("blast") or {}
    except FileNotFoundError:
        blast = {}
    except (OSError, ValueError, AttributeError) as exc:
        raise CaptureError("fsm-state.json unreadable (%s)" % type(exc).__name__)
    if isinstance(blast, dict) and blast.get("workspace_root") and blast.get("mode") in ("git", "snapshot"):
        return os.path.realpath(blast["workspace_root"]), blast["mode"]
    top = _git_toplevel(rd)
    if top:
        return top, "git"
    parts = rd.split(os.sep)
    if ".wip" in parts:
        idx = len(parts) - 1 - parts[::-1].index(".wip")
        return os.sep.join(parts[:idx]) or os.sep, "snapshot"
    raise CaptureError("cannot determine the workspace root of %s (no git, no .wip ancestor)" % rd)


# --- git mode ------------------------------------------------------------------------------------------------
def git_tree(ws, patterns):
    """Tree id of HEAD + working tree minus excludes, via a temporary index (real index/HEAD/worktree untouched)."""
    idx_rel = _decode(git(ws, ["rev-parse", "--git-path", "index"])).rstrip("\n")
    real_idx = os.path.join(ws, idx_rel)
    tmpdir = tempfile.mkdtemp(prefix="dag-footprint-")
    try:
        tmp_idx = os.path.join(tmpdir, "index")
        if os.path.exists(real_idx):
            shutil.copy2(real_idx, tmp_idx)  # copy2 KEEPS the index mtime: git's racy-clean re-hash must still fire
        env = {"GIT_INDEX_FILE": tmp_idx}
        _git_complete(ws, ["add", "-A", "."], env)
        for d in _exclude_dirs(patterns):
            lit = _glob_unliteral(d)
            git(ws, ["--literal-pathspecs", "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--",
                     d if lit is None else lit], env)
        tree = _decode(git(ws, ["write-tree"], env)).strip()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not _OID.match(tree):
        raise CaptureError("git write-tree returned no tree id")
    return tree


def git_entries(ws, patterns):
    fields = _decode(_git_complete(ws, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])).split("\0")
    entries, i = {}, 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if rec == "":
            continue
        if len(rec) < 4 or rec[2] != " ":
            raise CaptureError("malformed git status record %r" % rec[:40])
        xy, path, frm = rec[:2], _check_safe(rec[3:]), None
        if "R" in xy or "C" in xy:
            if i >= len(fields) or fields[i] == "":
                raise CaptureError("git status rename record without its original path")
            frm = _check_safe(fields[i])
            i += 1
        if not is_excluded(path, patterns):
            entries[path] = {"xy": xy, "from_path": frm, "sha256": _sha_path(ws, path)}
        if frm and not is_excluded(frm, patterns):
            entries.setdefault(frm, {"xy": "R-", "from_path": None, "sha256": _sha_path(ws, frm)})
    return dict(sorted(entries.items()))


# --- snapshot mode -------------------------------------------------------------------------------------------
def walk_files(ws, patterns):
    """Sorted workspace-relative paths of every regular file under ws minus excludes (symlinks never followed).
    An unreadable directory or an unstat-able file raises CaptureError: its files would otherwise read as deleted."""
    def walk_error(exc):
        raise CaptureError("cannot list %r (%s)" % (os.path.relpath(exc.filename or ws, ws), type(exc).__name__))
    dirs_ex = _exclude_dirs(patterns)
    out = []
    for root, dirs, files in os.walk(ws, onerror=walk_error, followlinks=False):
        rel_root = os.path.relpath(root, ws).replace(os.sep, "/")
        rel_root = "" if rel_root == "." else rel_root + "/"
        dirs[:] = sorted(d for d in dirs if not frame_match.match_any_pattern(rel_root + d, dirs_ex))
        for name in files:
            rel = rel_root + name
            try:
                mode = os.lstat(os.path.join(root, name)).st_mode
            except OSError as exc:
                raise CaptureError("cannot stat %r (%s)" % (rel, type(exc).__name__))
            if stat.S_ISREG(mode) and not is_excluded(rel, patterns):
                out.append(_check_safe(rel))
    return sorted(out)


def _store(run_dir, ws, rel, digest):
    """Write-once content store; returns False for files over the size cap (not stored). I/O errors fail closed."""
    full = os.path.join(ws, rel)
    try:
        if os.path.getsize(full) > STORE_MAX_BYTES:
            return False
        od = os.path.join(run_dir, "blast", "objects")
        dst = os.path.join(od, digest)
        if os.path.exists(dst):
            return True
        os.makedirs(od, exist_ok=True)
        with open(full, "rb") as fh:
            data = fh.read()
        if _sha_bytes(data) != digest:
            raise CaptureError("file changed while being stored: %r" % rel)
        _atomic_write(dst, data)
    except OSError as exc:
        raise CaptureError("cannot store %r (%s)" % (rel, type(exc).__name__))
    return True


# --- snapshots -----------------------------------------------------------------------------------------------
def _atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _dump(obj):
    return (json.dumps(obj, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def _present_sha(ws, rel):
    """_sha_path of a file just listed by walk_files; a file that vanished in between fails closed."""
    digest = _sha_path(ws, rel)
    if digest is None:
        raise CaptureError("%r vanished while being hashed" % rel)
    return digest


def take_snapshot(run_dir, wave, label, phase):
    rd = os.path.realpath(run_dir)
    ws, mode = resolve_workspace(rd)
    pats = exclude_patterns(ws, rd)
    if mode == "git":
        head = _decode(git(ws, ["rev-parse", "--verify", "HEAD"])).strip()
        entries = git_entries(ws, pats)
        tree = git_tree(ws, pats)
    else:
        head = tree = None
        entries = {}
        for rel in walk_files(ws, pats):
            digest = _present_sha(ws, rel)
            entries[rel] = {"xy": "", "from_path": None, "sha256": digest}
            if not _store(rd, ws, rel, digest):
                entries[rel]["stored"] = False
    return {"format": FORMAT, "mode": mode, "wave": wave, "label": label, "phase": phase, "head": head,
            "tree": tree, "workspace_root": ws, "excludes": pats, "entries": entries, "tool_version": TOOL_VERSION,
            "taken_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}


def snapshot_path(run_dir, wave, label, phase):
    name = "wave%d%s.%s.json" % (wave, "." + label if label else "", phase)
    return os.path.join(os.path.realpath(run_dir), "blast", name)


def write_snapshot(path, snap):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = _dump(snap)
    _atomic_write(path, data)
    return _sha_bytes(data)


def read_snapshot(path, ws, mode):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        snap = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CaptureError("snapshot %s unreadable (%s)" % (os.path.basename(path), type(exc).__name__))
    if not isinstance(snap, dict) or snap.get("format") != FORMAT or snap.get("mode") != mode:
        raise CaptureError("snapshot %s is not a %s %s-mode snapshot" % (os.path.basename(path), FORMAT, mode))
    if snap.get("workspace_root") != ws:
        raise CaptureError("snapshot %s was taken in another workspace" % os.path.basename(path))
    entries = snap.get("entries")
    if not isinstance(entries, dict):
        raise CaptureError("snapshot %s has no entries object" % os.path.basename(path))
    for p, e in entries.items():
        _check_safe(p)
        frm = e.get("from_path") if isinstance(e, dict) else None
        if (not isinstance(e, dict) or not isinstance(e.get("xy"), str)
                or not (e.get("sha256") is None or (isinstance(e["sha256"], str) and _SHA256.match(e["sha256"])))
                or not (frm is None or (isinstance(frm, str) and not frame_match.is_unsafe_path(frm)))):
            raise CaptureError("snapshot %s has a malformed or unsafe entry %r" % (os.path.basename(path), p))
    if mode == "git" and not _OID.match(str(snap.get("tree"))):
        raise CaptureError("snapshot %s has no valid tree id" % os.path.basename(path))
    return snap, _sha_bytes(data)


# --- change lists --------------------------------------------------------------------------------------------
def git_changes(ws, pre, post, patterns=None):
    """Content changes between two tree-ishes minus excluded paths (fail-closed; unsafe paths rejected)."""
    for t in (pre, post):
        if not isinstance(t, str) or not t or t.startswith("-") or "\0" in t:
            raise CaptureError("invalid tree-ish %r" % (t,))
    fields = _decode(git(ws, ["diff-tree", "-r", "-z", "-M", "--raw", "--no-commit-id", pre, post])).split("\0")
    raw, i = [], 0
    while i < len(fields):
        meta = fields[i]
        i += 1
        if meta == "":
            continue
        parts = meta.split(" ")
        if not meta.startswith(":") or len(parts) != 5:
            raise CaptureError("malformed git diff-tree record %r" % meta[:60])
        old_oid, new_oid, status = parts[2], parts[3], parts[4][:1]
        if status not in "AMDRT":
            raise CaptureError("unsupported git diff-tree status %r" % parts[4])
        if i >= len(fields) or (status == "R" and i + 1 >= len(fields)):
            raise CaptureError("truncated git diff-tree output")
        if status == "R":
            frm, path = _check_safe(fields[i]), _check_safe(fields[i + 1])
            i += 2
        else:
            frm, path = None, _check_safe(fields[i])
            i += 1
        raw.append((path, status, frm, None if _ZERO_OID.match(old_oid) else old_oid,
                    None if _ZERO_OID.match(new_oid) else new_oid))
    if patterns:  # tree mode may span commits that carry run artifacts: drop excluded sides, never fail open
        kept = []
        for path, status, frm, a, b in raw:
            gone_new, gone_old = is_excluded(path, patterns), frm is not None and is_excluded(frm, patterns)
            if status == "R" and gone_new != gone_old:
                kept.append((frm, "D", None, a, None) if gone_new else (path, "A", None, None, b))
            elif not gone_new:
                kept.append((path, status, frm, a, b))
        raw = kept
    hashes = _blob_hashes(ws, sorted({o for r in raw for o in r[3:] if o}))
    return [{"path": p, "status": s, "from_path": f, "sha256_before": hashes[a] if a else None,
             "sha256_after": hashes[b] if b else None} for p, s, f, a, b in raw]


def _blob_hashes(ws, oids):
    """sha256 of each blob's bytes, read through one `git cat-file --batch` (missing object => fail closed)."""
    if not oids:
        return {}
    out = git(ws, ["cat-file", "--batch"], stdin_bytes=("\n".join(oids) + "\n").encode("ascii"))
    res, pos = {}, 0
    for oid in oids:
        nl = out.find(b"\n", pos)
        header = out[pos:nl].decode("ascii", "replace").split(" ") if nl >= 0 else []
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise CaptureError("git object %s is not a readable blob" % oid)
        size = int(header[2])
        res[oid] = _sha_bytes(out[nl + 1:nl + 1 + size])
        pos = nl + 1 + size + 1
    return res


def snapshot_changes(pre, post):
    a, b = pre["entries"], post["entries"]
    out = []
    for p in sorted(set(a) | set(b)):
        before = a[p].get("sha256") if p in a else None
        after = b[p].get("sha256") if p in b else None
        if before == after:
            continue
        status = "A" if before is None else "D" if after is None else "M"
        out.append({"path": p, "status": status, "from_path": None, "sha256_before": before, "sha256_after": after})
    return out


# --- capture -------------------------------------------------------------------------------------------------
def _wave_units(run_dir, wave):
    try:
        with open(os.path.join(run_dir, "graph.json"), encoding="utf-8") as fh:
            graph = json.load(fh)
        ids = next(w["units"] for w in graph["waves"] if w.get("wave") == wave)
        frames = {u["id"]: list(((u.get("frame") or {}).get("modifies")) or []) for u in graph["units"]}
        return {uid: frames.get(uid, []) for uid in ids}
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise CaptureError("graph.json gives no unit list for wave %d (%s)" % (wave, type(exc).__name__))


def _graph_frames(run_dir):
    """{unit id: frame.modifies} for EVERY graph.json unit (any wave)."""
    try:
        with open(os.path.join(run_dir, "graph.json"), encoding="utf-8") as fh:
            graph = json.load(fh)
        return {u["id"]: list(((u.get("frame") or {}).get("modifies")) or []) for u in graph["units"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaptureError("graph.json gives no unit list (%s)" % type(exc).__name__)


def retry_window_units(run_dir, wave, label, extra):
    """The window units a retry pre snapshot records: U (from the <U>-i<k> label; a unit of `wave`) first, then every
    other id of `extra` (each a graph.json unit id), sorted and de-duplicated. CaptureError on any violation."""
    m = _RETRY_LABEL.match(label or "")
    if not m:
        raise CaptureError("--window-units needs a retry label <U>-i<k> (got --label %r)" % (label,))
    rd = os.path.realpath(run_dir)
    unit = m.group(1)
    if unit not in _wave_units(rd, wave):
        raise CaptureError("retry label %s names %s, which is not a unit of wave %d" % (label, unit, wave))
    frames = _graph_frames(rd)
    bad = sorted(u for u in extra if u not in frames)
    if bad:
        raise CaptureError("--window-units %s: not graph.json unit id(s)" % ",".join(bad))
    return [unit] + sorted(set(extra) - {unit})


def _retry_window(rd, wave, unit, ws, mode):
    """(retry pre snapshot, {window unit: modifies}) for U's CURRENT iteration; absent or malformed => CaptureError
    (fail closed: a retry capture never falls back to the wave window)."""
    label = "%s-i%d" % (unit, _iteration(rd, unit))
    path = snapshot_path(rd, wave, label, "pre")
    if not os.path.exists(path):
        raise CaptureError("retry pre snapshot %s is absent (take `snapshot <RUN_DIR> --wave %d --label %s` when %s's "
                           "iteration %s is dispatched; every per-unit capture needs one, iteration 1 included); no "
                           "fallback to the wave window" % (os.path.basename(path), wave, label, unit, label.rsplit("-i", 1)[1]))
    rpre, _ = read_snapshot(path, ws, mode)
    window = rpre.get("window_units")
    frames = _graph_frames(rd)
    if (not isinstance(window, list) or unit not in window
            or not all(isinstance(u, str) and u in frames for u in window)):
        raise CaptureError("retry pre snapshot %s records no valid window_units list including %s"
                           % (os.path.basename(path), unit))
    return rpre, {u: frames[u] for u in window}


def _claims(change, modifies):
    if not frame_match.match_any_pattern(change["path"], modifies):
        return False
    return change["from_path"] is None or frame_match.match_any_pattern(change["from_path"], modifies)


def _iteration(run_dir, unit):
    try:
        with open(os.path.join(run_dir, "units", unit, "debrief.json"), encoding="utf-8") as fh:
            it = json.load(fh).get("iteration")
        return it if isinstance(it, int) and not isinstance(it, bool) and it >= 1 else 1
    except (OSError, ValueError, AttributeError):
        return 1


def _write_footprint(run_dir, unit, doc):
    ud = os.path.join(run_dir, "units", unit)
    os.makedirs(ud, exist_ok=True)
    data = _dump(doc)
    _atomic_write(os.path.join(ud, "footprint.json"), data)
    _atomic_write(os.path.join(ud, "footprint.json.sha256"), ("%s  footprint.json\n" % _sha_bytes(data)).encode())


def capture(run_dir, wave=None, label=None, unit=None, pre_tree=None, post_tree=None):
    """Write footprints; returns (written {unit: footprint}, error or None)."""
    rd = os.path.realpath(run_dir)
    tree_mode = pre_tree is not None or post_tree is not None
    ctx = {"mode": "none", "base_ref": None, "pre": None, "post": None}
    window, wchanges = None, []  # retry only: {window unit: modifies} and the retry window's own change list
    try:
        units = {unit: []} if tree_mode else _wave_units(rd, wave)
        if unit is not None and unit not in units:
            raise CaptureError("unit %s is not in wave %s" % (unit, wave))
        targets = [unit] if unit is not None else list(units)
    except CaptureError as exc:
        if unit is None:
            raise
        units, targets, early = {unit: []}, [unit], exc
    else:
        early = None
    try:
        if early:
            raise early
        ws, mode = resolve_workspace(rd)
        ctx["mode"] = mode
        if tree_mode:
            if mode != "git":
                raise CaptureError("tree mode needs a git workspace (mode is %s)" % mode)
            ctx["base_ref"] = pre_tree
            changes = git_changes(ws, pre_tree, post_tree, exclude_patterns(ws, rd))
        else:
            pre, ctx["pre"] = read_snapshot(snapshot_path(rd, wave, label, "pre"), ws, mode)
            if mode == "git":
                ctx["base_ref"] = pre["tree"]
            if unit is not None:
                rpre, window = _retry_window(rd, wave, unit, ws, mode)
                post = take_snapshot(rd, wave, label, "post")
                retry_name = "%s-i%d.post" % (unit, _iteration(rd, unit))
                ctx["post"] = write_snapshot(snapshot_path(rd, wave, label, retry_name), post)
            else:
                post_path = snapshot_path(rd, wave, label, "post")
                if not os.path.exists(post_path):
                    write_snapshot(post_path, take_snapshot(rd, wave, label, "post"))
                post, ctx["post"] = read_snapshot(post_path, ws, mode)
            changes = git_changes(ws, pre["tree"], post["tree"], exclude_patterns(ws, rd)) if mode == "git" else snapshot_changes(pre, post)
            if window is not None:
                wchanges = git_changes(ws, rpre["tree"], post["tree"], exclude_patterns(ws, rd)) if mode == "git" else snapshot_changes(rpre, post)
        error = None
    except CaptureError as exc:
        changes, wchanges, error = [], [], _oneline(exc)
    except OSError as exc:  # e.g. the post snapshot cannot be written: still a capture_error, never a traceback
        changes, wchanges, error = [], [], _oneline("I/O error: %s" % exc)
    claimed = {}
    unattributed = set()
    if window is None:  # wave or tree capture: attribution to the wave's own units over the wave window
        for ch in changes:
            owners = [u for u, mods in units.items() if tree_mode or _claims(ch, mods)]
            for u in owners:
                claimed.setdefault(u, []).append(ch)
            if not owners:
                unattributed.update(x for x in (ch["path"], ch["from_path"]) if x)
    else:  # retry: cumulative changes filtered to U's frame; unattributed over the retry window only
        claimed[unit] = [ch for ch in changes if _claims(ch, units[unit])]
        for ch in wchanges:
            if not any(_claims(ch, mods) for mods in window.values()):
                unattributed.update(x for x in (ch["path"], ch["from_path"]) if x)
    written = {}
    for u in targets:
        doc = {"unit_id": u, "iteration": _iteration(rd, u), "mode": ctx["mode"],
               "base_ref": None if ctx["mode"] == "snapshot" else ctx["base_ref"],
               "pre_snapshot_sha256": ctx["pre"], "post_snapshot_sha256": ctx["post"],
               "changes": [] if error else claimed.get(u, []), "unattributed": sorted(unattributed),
               "capture_error": error, "tool_version": TOOL_VERSION}
        _write_footprint(rd, u, doc)
        written[u] = doc
    return written, error


# --- digest --------------------------------------------------------------------------------------------------
def tree_digest(workspace_root, run_dir=None):
    """Content-based digest of a workspace (git: tree id minus excludes; snapshot: per-file hashes)."""
    ws = os.path.realpath(workspace_root)
    top = _git_toplevel(ws)
    if top is not None and top != ws:
        raise CaptureError("%s is inside the repository %s but is not its top level" % (ws, top))
    pats = exclude_patterns(ws, run_dir)
    if top is not None:
        tree = git_tree(ws, pats)
        head = _decode(git(ws, ["rev-parse", "--verify", "HEAD"])).strip()
        return {"mode": "git", "head": head, "tree": tree, "digest": "sha256:" + _sha_bytes(("tree:%s\n" % tree).encode())}
    lines = "".join("%s\t%s\n" % (p, _present_sha(ws, p)) for p in walk_files(ws, pats))
    return {"mode": "snapshot", "head": None, "tree": None,
            "digest": "sha256:" + _sha_bytes(lines.encode("utf-8", "surrogateescape"))}


# --- self-test -----------------------------------------------------------------------------------------------
def _self_test():
    import contextlib
    import io
    import time
    base = tempfile.mkdtemp(prefix="footprint-selftest-")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    env["GIT_CEILING_DIRECTORIES"] = base
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    results = []
    counter = [0]

    def sh(cwd, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"] + list(args),
                       cwd=cwd, check=True, capture_output=True, timeout=60)

    def put(ws, rel, text):
        os.makedirs(os.path.dirname(os.path.join(ws, rel)) or ws, exist_ok=True)
        with open(os.path.join(ws, rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def repo(git_mode=True, modifies=("**",)):
        counter[0] += 1
        ws = os.path.join(base, "r%d" % counter[0])
        rd = os.path.join(ws, ".wip", "run")
        os.makedirs(rd)
        put(ws, "a.txt", "alpha\n" * 20)
        put(ws, "b.txt", "bravo\n" * 20)
        put(ws, "keep/c.txt", "charlie\n" * 20)
        put(ws, ".gitignore", "*.log\n")
        if git_mode:
            sh(ws, "init", "-q")
            sh(ws, "add", "a.txt", "b.txt", "keep/c.txt", ".gitignore")
            sh(ws, "commit", "-q", "--no-verify", "-m", "base")
        graph = {"waves": [{"wave": 1, "units": ["U01", "U02"]}],
                 "units": [{"id": "U01", "frame": {"modifies": list(modifies), "immutable": [], "intended_changes": []}},
                           {"id": "U02", "frame": {"modifies": ["nothing/**"], "immutable": [], "intended_changes": []}}]}
        put(rd, "graph.json", json.dumps(graph))
        return ws, rd

    def run_capture(rd, **kw):
        with contextlib.redirect_stderr(io.StringIO()):
            written, err = capture(rd, **kw)
        return written["U01"] if "U01" in written else next(iter(written.values())), err

    def snap(rd):
        write_snapshot(snapshot_path(rd, 1, None, "pre"), take_snapshot(rd, 1, None, "pre"))

    def changes_of(fp):
        return {(c["path"], c["status"], c["from_path"]) for c in fp["changes"]}

    def case(rule, polarity, fn):
        try:
            ok = bool(fn())
        except Exception as exc:  # a crash is a FAIL, never a pass
            sys.stderr.write("self-test %s %s raised %s: %s\n" % (rule, polarity, type(exc).__name__, exc))
            ok = False
        results.append(ok)
        print("case %s %s %s" % (rule, polarity, "ok" if ok else "FAIL"))

    def wave(setup, mutate, git_mode=True, modifies=("**",), **kw):
        ws, rd = repo(git_mode, modifies)
        if setup:
            setup(ws)
        snap(rd)
        mutate(ws, rd)
        return run_capture(rd, wave=1, **kw)

    def clean(fp, err):
        return err is None and fp["capture_error"] is None

    try:
        case("modify", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("a.txt", "M", None)}
                                       and r[0]["changes"][0]["sha256_after"] == _sha_bytes(b"x\n"))(
            wave(None, lambda ws, rd: put(ws, "a.txt", "x\n"))))
        case("modify", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [])(
            wave(None, lambda ws, rd: (put(ws, "a.txt", "alpha\n" * 20), os.utime(os.path.join(ws, "a.txt"), (1, 1))))))

        def racy(final):
            """Arm git's racy-clean case: `git add` writes the real index and a same-size rewrite follows in the
            same fresh second; the capture runs a later second. A temp index without the real index's mtime
            trusts the stale stat data and records the STAGED bytes instead of `final`."""
            def mutate(ws, rd):
                for _ in range(5):
                    time.sleep(1.0 - time.time() % 1 + 0.01)
                    put(ws, "a.txt", "ALPHA\n" * 20)
                    sh(ws, "add", "a.txt")
                    put(ws, "a.txt", final)
                    if int(os.stat(os.path.join(ws, ".git", "index")).st_mtime) == int(os.stat(os.path.join(ws, "a.txt")).st_mtime):
                        break
                time.sleep(1.1)
            return wave(None, mutate)
        case("modify", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("a.txt", "M", None)}
                                       and r[0]["changes"][0]["sha256_after"] == _sha_bytes(b"omega\n" * 20))(
            racy("omega\n" * 20)))
        case("modify", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [])(racy("alpha\n" * 20)))
        case("add", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("n.txt", "A", None)}
                                    and r[0]["changes"][0]["sha256_before"] is None)(
            wave(None, lambda ws, rd: put(ws, "n.txt", "new\n"))))
        case("add", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [] and r[0]["unattributed"] == [])(
            wave(None, lambda ws, rd: (put(rd, "scratch.txt", "x"), put(ws, ".wip/other.txt", "y")))))
        case("delete", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("b.txt", "D", None)}
                                       and r[0]["changes"][0]["sha256_after"] is None)(
            wave(None, lambda ws, rd: os.remove(os.path.join(ws, "b.txt")))))
        case("delete", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [])(
            wave(None, lambda ws, rd: (os.remove(os.path.join(ws, "b.txt")), put(ws, "b.txt", "bravo\n" * 20)))))
        case("rename", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("b2.txt", "R", "b.txt"),
                                                                                       ("c2.txt", "R", "keep/c.txt")})(
            wave(None, lambda ws, rd: (sh(ws, "mv", "b.txt", "b2.txt"),
                                       os.rename(os.path.join(ws, "keep/c.txt"), os.path.join(ws, "c2.txt"))))))
        case("rename", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == []
                                       and r[0]["unattributed"] == ["b.txt", "new/b.txt"])(
            wave(None, lambda ws, rd: (os.makedirs(os.path.join(ws, "new")), sh(ws, "mv", "b.txt", "new/b.txt")),
                 modifies=("new/**",))))
        case("untracked_newdir", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("d1/d2/u.txt", "A", None)})(
            wave(None, lambda ws, rd: put(ws, "d1/d2/u.txt", "u\n"))))
        case("untracked_newdir", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [])(
            wave(None, lambda ws, rd: os.makedirs(os.path.join(ws, "e1", "e2")))))
        case("ignored", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("t.log", "M", None)})(
            wave(lambda ws: (put(ws, "t.log", "1\n"), sh(ws, "add", "-f", "t.log"), sh(ws, "commit", "-q", "--no-verify", "-m", "t")),
                 lambda ws, rd: put(ws, "t.log", "2\n"))))
        case("ignored", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [] and r[0]["unattributed"] == [])(
            wave(None, lambda ws, rd: put(ws, "sub/x.log", "ignored\n"))))

        def snap_pos():
            fp, err = wave(None, lambda ws, rd: (put(ws, "a.txt", "changed\n"), put(ws, "z/new.txt", "z\n"),
                                                 os.remove(os.path.join(ws, "b.txt"))), git_mode=False)
            rd = os.path.join(base, "r%d" % counter[0], ".wip", "run")
            before = next(c["sha256_before"] for c in fp["changes"] if c["path"] == "a.txt")
            with open(os.path.join(rd, "blast", "objects", before), "rb") as fh:
                stored_ok = fh.read() == b"alpha\n" * 20
            return (clean(fp, err) and fp["mode"] == "snapshot" and fp["base_ref"] is None and stored_ok
                    and changes_of(fp) == {("a.txt", "M", None), ("z/new.txt", "A", None), ("b.txt", "D", None)})
        case("snapshot_mode", "pos", snap_pos)
        case("snapshot_mode", "neg", lambda: (lambda r: clean(*r) and r[0]["mode"] == "snapshot" and r[0]["changes"] == [])(
            wave(None, lambda ws, rd: (put(rd, "notes.txt", "run-dir edit\n"), put(ws, ".wip/x.txt", "x")), git_mode=False)))

        fakebin = os.path.join(base, "fakebin")
        os.makedirs(fakebin)
        for name, body in (("sleep", "#!/bin/sh\nexec sleep 30\n"), ("fail", "#!/bin/sh\necho boom >&2\nexit 3\n"),
                           ("l10n", "#!/bin/sh\nif [ \"$LC_ALL\" = C ]; then echo 'fatal: not a git repository "
                                    "(or any of the parent directories): .git' >&2\nelse echo 'Schwerwiegend: Kein "
                                    "Git-Repository (oder irgendeines der Elternverzeichnisse): .git' >&2\nfi\nexit 128\n"),
                           ("dubious", "#!/bin/sh\necho 'fatal: detected dubious ownership in repository' >&2\nexit 128\n")):
            os.makedirs(os.path.join(fakebin, name))
            put(fakebin, name + "/git", body)
            os.chmod(os.path.join(fakebin, name, "git"), 0o755)

        def faked(kind, timeout):
            def mutate(ws, rd):
                put(ws, "a.txt", "x\n")
                os.environ["PATH"] = os.path.join(fakebin, kind) + os.pathsep + env.get("PATH", "")
                os.environ["DAG_BLAST_GIT_TIMEOUT"] = timeout
            try:
                return wave(None, mutate)
            finally:
                os.environ["PATH"] = env.get("PATH", "")
                os.environ.pop("DAG_BLAST_GIT_TIMEOUT", None)

        def timeout_pos():
            fp, err = faked("sleep", "1")
            fp2, err2 = faked("fail", "1")
            return (err and "did not finish within 1s" in fp["capture_error"] and fp["changes"] == []
                    and err2 and "rc 3" in fp2["capture_error"] and fp2["changes"] == [])
        case("timeout", "pos", timeout_pos)
        case("timeout", "neg", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("a.txt", "M", None)})(
            wave(None, lambda ws, rd: (put(ws, "a.txt", "x\n"), os.environ.__setitem__("DAG_BLAST_GIT_TIMEOUT", "30")))))
        os.environ.pop("DAG_BLAST_GIT_TIMEOUT", None)

        def localized(kind, fn):
            """Run fn with a fake git on PATH under a German host locale (git's messages are translated unless
            footprint.py forces LC_ALL=C), so the snapshot-mode fallback must not depend on the host locale."""
            os.environ["PATH"] = os.path.join(fakebin, kind) + os.pathsep + env.get("PATH", "")
            os.environ.update(LC_ALL="de_DE.UTF-8", LANG="de_DE.UTF-8", LANGUAGE="de")
            try:
                return fn()
            finally:
                for k in ("PATH", "LC_ALL", "LANG", "LANGUAGE"):
                    if k in env:
                        os.environ[k] = env[k]
                    else:
                        os.environ.pop(k, None)
        case("snapshot_mode", "pos", lambda: (lambda r: clean(*r) and r[0]["mode"] == "snapshot"
                                              and changes_of(r[0]) == {("a.txt", "M", None)})(
            localized("l10n", lambda: wave(None, lambda ws, rd: put(ws, "a.txt", "x\n"), git_mode=False))))

        def dubious_neg():
            ws, rd = repo(git_mode=False)
            try:
                take_snapshot(rd, 1, None, "pre")
                snapshot_refused = False
            except CaptureError as exc:
                snapshot_refused = "dubious ownership" in str(exc)
            fp, err = run_capture(rd, wave=1)
            return (snapshot_refused and err and "dubious ownership" in fp["capture_error"] and fp["changes"] == []
                    and fp["mode"] == "none")
        case("snapshot_mode", "neg", lambda: localized("dubious", dubious_neg))

        def forged(ws, rd):
            p = snapshot_path(rd, 1, None, "pre")
            with open(p, encoding="utf-8") as fh:
                s = json.load(fh)
            s["entries"]["../escape.txt"] = {"xy": "", "from_path": None, "sha256": "0" * 64}
            write_snapshot(p, s)
            put(ws, "a.txt", "x\n")
        case("unsafe_path", "pos", lambda: (lambda r: r[1] and "unsafe path" in r[0]["capture_error"] and r[0]["changes"] == [])(
            wave(None, forged, git_mode=False)))
        case("unsafe_path", "neg", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("we ird\nname\udcff.txt", "A", None)})(
            wave(None, lambda ws, rd: open(os.path.join(os.fsencode(ws), b"we ird\nname\xff.txt"), "wb").write(b"q"))))
        case("content_free_commit", "pos", lambda: (lambda r: clean(*r) and changes_of(r[0]) == {("a.txt", "M", None)})(
            wave(None, lambda ws, rd: (put(ws, "a.txt", "x\n"), sh(ws, "commit", "-q", "--no-verify", "-am", "c")))))
        case("content_free_commit", "neg", lambda: (lambda r: clean(*r) and r[0]["changes"] == [])(
            wave(lambda ws: put(ws, "a.txt", "dirty-before-wave\n"),
                 lambda ws, rd: (sh(ws, "commit", "-q", "--no-verify", "-am", "c"),
                                 sh(ws, "commit", "-q", "--no-verify", "--allow-empty", "-m", "e")))))

        def tree_pos():
            ws, rd = repo()
            pre = _decode(subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws, capture_output=True, check=True).stdout).strip()
            put(ws, "a.txt", "x\n")
            put(ws, "n.txt", "n\n")
            os.remove(os.path.join(ws, "keep/c.txt"))
            sh(ws, "add", "-A")
            sh(ws, "mv", "b.txt", "b3.txt")
            sh(ws, "commit", "-q", "--no-verify", "-m", "t")
            fp, err = run_capture(rd, unit="U07", pre_tree=pre, post_tree="HEAD")
            return (clean(fp, err) and fp["base_ref"] == pre and fp["pre_snapshot_sha256"] is None
                    and changes_of(fp) == {("a.txt", "M", None), ("n.txt", "A", None), ("keep/c.txt", "D", None),
                                           ("b3.txt", "R", "b.txt")})
        case("tree_mode", "pos", tree_pos)

        def tree_neg():
            ws, rd = repo()
            sh(ws, "commit", "-q", "--no-verify", "--allow-empty", "-m", "e")
            fp, err = run_capture(rd, unit="U07", pre_tree="HEAD~1", post_tree="HEAD")
            return clean(fp, err) and fp["changes"] == [] and fp["base_ref"] == "HEAD~1"
        case("tree_mode", "neg", tree_neg)

        def cli(*args):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    return main(list(args))
                except SystemExit as exc:  # argparse usage errors
                    return exc.code

        def retry_fixture():
            """wave 1 = U01 (u1/**), U02 (u2/**); wave 2 = U03 (u3/**). Waves 1 and 2 run and are captured, then U01
            is retried at iteration 2 (U03 wrote u3/y.txt in wave 2, i.e. BEFORE the retry pre snapshot)."""
            ws, rd = repo()
            put(ws, "u1/a.txt", "a0\n")
            put(ws, "u2/x.txt", "x0\n")
            put(ws, "u3/y.txt", "y0\n")
            sh(ws, "add", "-A")
            sh(ws, "commit", "-q", "--no-verify", "-m", "fixture")
            put(rd, "graph.json", json.dumps({
                "waves": [{"wave": 1, "units": ["U01", "U02"]}, {"wave": 2, "units": ["U03"]}],
                "units": [{"id": u, "frame": {"modifies": [m]}} for u, m in
                          (("U01", "u1/**"), ("U02", "u2/**"), ("U03", "u3/**"))]}))
            snap(rd)
            put(ws, "u1/a.txt", "a1\n")
            ok = run_capture(rd, wave=1)[1] is None and cli("snapshot", rd, "--wave", "2") == 0
            put(ws, "u3/y.txt", "y1\n")
            ok = ok and run_capture(rd, wave=2)[1] is None
            put(rd, "units/U01/debrief.json", json.dumps({"unit_id": "U01", "iteration": 2}))
            return ws, rd, ok

        def retry_pos():
            ws, rd, ok = retry_fixture()
            refused = (cli("snapshot", rd, "--wave", "1", "--label", "U01-i2", "--window-units", "U99") == 2
                       and cli("snapshot", rd, "--wave", "1", "--label", "U03-i2") == 2
                       and not os.path.exists(snapshot_path(rd, 1, "U01-i2", "pre")))
            ok = ok and refused and cli("snapshot", rd, "--wave", "1", "--label", "U01-i2", "--window-units", "U02") == 0
            with open(snapshot_path(rd, 1, "U01-i2", "pre"), encoding="utf-8") as fh:
                recorded = json.load(fh).get("window_units") == ["U01", "U02"]
            put(ws, "u1/a.txt", "a2\n")
            put(ws, "u3/stray.txt", "s\n")  # into the frame of U03, which was not dispatched in the window
            fp, err = run_capture(rd, wave=1, unit="U01")
            return ok and recorded and clean(fp, err) and fp["unattributed"] == ["u3/stray.txt"]
        case("retry_window", "pos", retry_pos)

        def retry_absent():
            ws, rd, ok = retry_fixture()  # iteration 2, no wave1.U01-i2.pre.json; then iteration 3 with only i2's
            put(ws, "u1/a.txt", "a2\n")
            fp, err = run_capture(rd, wave=1, unit="U01")
            first = err and "absent" in fp["capture_error"] and fp["changes"] == []
            ok = ok and cli("snapshot", rd, "--wave", "1", "--label", "U01-i2") == 0
            put(rd, "units/U01/debrief.json", json.dumps({"unit_id": "U01", "iteration": 3}))
            fp, err = run_capture(rd, wave=1, unit="U01")
            return ok and first and err and "U01-i3.pre.json is absent" in fp["capture_error"] and fp["changes"] == []
        case("retry_window", "pos", retry_absent)

        def retry_same_wave():
            ws, rd, ok = retry_fixture()
            ok = ok and cli("snapshot", rd, "--wave", "1", "--label", "U01-i2") == 0  # window = [U01] only
            put(ws, "u1/a.txt", "a2\n")
            put(ws, "u2/x.txt", "x2\n")  # U02 is a unit of wave 1, but it was NOT dispatched in the retry window
            fp, err = run_capture(rd, wave=1, unit="U01")
            return ok and clean(fp, err) and fp["unattributed"] == ["u2/x.txt"]
        case("retry_window", "pos", retry_same_wave)

        def retry_neg():
            ws, rd, ok = retry_fixture()
            ok = ok and cli("snapshot", rd, "--wave", "1", "--label", "U01-i2", "--window-units", "U02") == 0
            put(ws, "u1/a.txt", "a2\n")
            put(ws, "u2/x.txt", "x2\n")  # a recorded window unit, inside its own frame
            fp, err = run_capture(rd, wave=1, unit="U01")
            with open(snapshot_path(rd, 1, None, "pre"), encoding="utf-8") as fh:
                wave_pre_tree = json.load(fh)["tree"]
            return (ok and clean(fp, err) and fp["unattributed"] == [] and fp["base_ref"] == wave_pre_tree
                    and [(c["path"], c["status"], c["sha256_before"], c["sha256_after"]) for c in fp["changes"]]
                    == [("u1/a.txt", "M", _sha_bytes(b"a0\n"), _sha_bytes(b"a2\n"))])
        case("retry_window", "neg", retry_neg)

        def unreadable(at_snapshot):
            """newdir/ (untracked) is chmod 000 while the capture runs, or while the pre snapshot is taken."""
            ws, rd = repo()
            put(ws, "newdir/f.txt", "s\n")
            d = os.path.join(ws, "newdir")
            if not at_snapshot:
                snap(rd)
            if os.geteuid() == 0 or not _locks(d):
                sys.stderr.write("self-test unreadable_dir: cannot arm the precondition (euid %d: chmod 000 does "
                                 "not block listing %s)\n" % (os.geteuid(), d))
                return None
            try:
                if at_snapshot:
                    try:
                        snap(rd)
                    except CaptureError as exc:
                        refused = "could not open directory" in str(exc)
                    else:
                        refused = False
                    os.chmod(d, 0o755)
                put(ws, "a.txt", "x\n")
                fp, err = run_capture(rd, wave=1)
            finally:
                os.chmod(d, 0o755)
            return fp, err, refused if at_snapshot else None

        def _locks(d):
            os.chmod(d, 0)
            try:
                os.listdir(d)
            except PermissionError:
                return True
            os.chmod(d, 0o755)
            return False

        def unreadable_pos():
            a, b = unreadable(False), unreadable(True)
            return (a is not None and b is not None
                    and a[1] and "could not open directory" in a[0]["capture_error"] and a[0]["changes"] == []
                    and b[2] is True and b[1] and b[0]["changes"] == [])
        case("unreadable_dir", "pos", unreadable_pos)

        def unreadable_neg():
            ws, rd = repo()
            put(ws, "newdir/f.txt", "s\n")
            snap(rd)
            put(ws, "a.txt", "x\n")
            fp, err = run_capture(rd, wave=1)
            fp2, err2 = wave(None, lambda ws, rd: (put(ws, "a.txt", "x\n"), put(ws, "newdir/f.txt", "s\n")))
            return (clean(fp, err) and changes_of(fp) == {("a.txt", "M", None)}
                    and clean(fp2, err2) and changes_of(fp2) == {("a.txt", "M", None), ("newdir/f.txt", "A", None)})
        case("unreadable_dir", "neg", unreadable_neg)

        def unreadable_tracked(mode, at_snapshot, dname="keep"):
            """<dname>/ is TRACKED and chmod `mode` (listable, not searchable) with <dname>/c.txt modified, while the
            capture runs or while the pre snapshot is taken: git prints '<dname>/c.txt: Permission denied' on stderr
            and exits 0, and its listing silently omits the modification."""
            ws, rd = repo()  # keep/c.txt is committed by repo(); any other dname is committed here
            if dname != "keep":
                put(ws, dname + "/c.txt", "charlie\n" * 20)
                sh(ws, "add", "--", dname)
                sh(ws, "commit", "-q", "--no-verify", "-m", "tracked dir")
            d = os.path.join(ws, dname)
            if not at_snapshot:
                snap(rd)
            put(ws, dname + "/c.txt", "changed\n")
            refused = None
            os.chmod(d, mode)
            try:
                try:
                    os.stat(os.path.join(d, "c.txt"))
                except PermissionError:
                    pass
                else:
                    sys.stderr.write("self-test unreadable_dir: cannot arm the precondition (euid %d: chmod %o does "
                                     "not block search of %s)\n" % (os.geteuid(), mode, d))
                    return None
                if at_snapshot:
                    try:
                        snap(rd)
                    except CaptureError as exc:
                        refused = "Permission denied" in str(exc)
                    else:
                        refused = False
                    os.chmod(d, 0o755)
                    put(ws, "a.txt", "x\n")
                fp, err = run_capture(rd, wave=1)
            finally:
                os.chmod(d, 0o755)
            return fp, err, refused

        for mode in (0o644, 0o600):
            # capture time: capture_error naming the unreadable path, changes []
            case("unreadable_dir", "pos", lambda m=mode: (lambda r: r is not None and r[1]
                 and "Permission denied" in r[0]["capture_error"] and r[0]["changes"] == [])(unreadable_tracked(m, False)))
            # pre-snapshot time: the snapshot refuses, so the following capture fails closed too
            case("unreadable_dir", "pos", lambda m=mode: (lambda r: r is not None and r[2] is True and r[1]
                 and r[0]["changes"] == [])(unreadable_tracked(m, True)))
        # a strerror tail fails closed even inside a line the allowlist would otherwise pass ("hint: x/c.txt: ...")
        case("unreadable_dir", "pos", lambda: (lambda r: r is not None and r[1] and r[0]["changes"] == [])(
            unreadable_tracked(0o644, False, "hint: x")))

        def unreadable_tracked_neg():
            """the same tracked layouts left readable capture normally, and an allowlisted notice does not fail."""
            ws, rd = repo()
            snap(rd)
            put(ws, "keep/c.txt", "changed\n")
            fp, err = run_capture(rd, wave=1)
            ws2, rd2 = repo()
            put(ws2, "keep/c.txt", "changed\n")  # dirty before the wave: in both snapshots, so not a change
            snap(rd2)
            put(ws2, "a.txt", "x\n")
            fp2, err2 = run_capture(rd2, wave=1)
            ws3, rd3 = repo()
            sh(ws3, "config", "core.autocrlf", "true")  # git add -A prints "LF will be replaced by CRLF" notices
            snap(rd3)
            put(ws3, "new.txt", "n\n")
            fp3, err3 = run_capture(rd3, wave=1)
            return (clean(fp, err) and changes_of(fp) == {("keep/c.txt", "M", None)}
                    and clean(fp2, err2) and changes_of(fp2) == {("a.txt", "M", None)}
                    and clean(fp3, err3) and changes_of(fp3) == {("new.txt", "A", None)})
        case("unreadable_dir", "neg", unreadable_tracked_neg)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(base, ignore_errors=True)
    return 0 if results and all(results) else 1


# --- CLI -----------------------------------------------------------------------------------------------------
def main(argv):
    if argv == ["--self-test"]:
        return _self_test()
    ap = argparse.ArgumentParser(prog="footprint.py", description="Wave snapshots, file footprints and tree digests.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("run_dir")
    s.add_argument("--wave", type=int, required=True)
    s.add_argument("--label")
    s.add_argument("--window-units", help="retry pre snapshot only (--label <U>-i<k>): comma-separated unit ids "
                                          "dispatched in the retry window besides U")
    c = sub.add_parser("capture")
    c.add_argument("run_dir")
    c.add_argument("--wave", type=int)
    c.add_argument("--label")
    c.add_argument("--unit")
    c.add_argument("--pre-tree")
    c.add_argument("--post-tree")
    d = sub.add_parser("digest")
    d.add_argument("workspace_root")
    d.add_argument("--run-dir")
    a = ap.parse_args(argv)
    label = getattr(a, "label", None)
    if label is not None and not _LABEL.match(label):
        ap.error("--label must match %s" % _LABEL.pattern)
    if getattr(a, "unit", None) is not None and not _UNIT.match(a.unit):
        ap.error("--unit must match %s" % _UNIT.pattern)
    if getattr(a, "wave", None) is not None and a.wave < 0:
        ap.error("--wave must be >= 0")
    try:
        if a.cmd == "snapshot":
            extra = None if a.window_units is None else [u.strip() for u in a.window_units.split(",") if u.strip()]
            if extra is not None and (not extra or not all(_UNIT.match(u) for u in extra)):
                ap.error("--window-units must be a comma-separated list of unit ids (%s)" % _UNIT.pattern)
            retry = _RETRY_LABEL.match(label or "") is not None
            if extra is not None and not retry:
                ap.error("--window-units needs a retry label --label <U>-i<k>")
            window = retry_window_units(a.run_dir, a.wave, label, extra or []) if retry else None
            snap = take_snapshot(a.run_dir, a.wave, label, "pre")
            if window is not None:
                snap["window_units"] = window
            path = snapshot_path(a.run_dir, a.wave, label, "pre")
            write_snapshot(path, snap)
            print(path)
            return 0
        if a.cmd == "digest":
            print(json.dumps(tree_digest(a.workspace_root, a.run_dir), ensure_ascii=True))
            return 0
        tree_mode = a.pre_tree is not None or a.post_tree is not None
        if tree_mode and (a.pre_tree is None or a.post_tree is None or a.unit is None or a.wave is not None):
            ap.error("tree mode needs --unit, --pre-tree and --post-tree (and no --wave)")
        if not tree_mode and a.wave is None:
            ap.error("capture needs --wave N (or --unit/--pre-tree/--post-tree)")
        written, err = capture(a.run_dir, a.wave, label, a.unit, a.pre_tree, a.post_tree)
        for u in written:
            print(os.path.join(os.path.realpath(a.run_dir), "units", u, "footprint.json"))
        if err:
            sys.stderr.write("footprint.py: capture_error: %s\n" % err)
            return 1
        return 0
    except (CaptureError, OSError) as exc:
        sys.stderr.write("footprint.py: %s\n" % _oneline(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
