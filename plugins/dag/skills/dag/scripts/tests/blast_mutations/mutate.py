#!/usr/bin/env python3
"""Regenerate the blast-radius derived fixtures from scripts/tests/blast_green, ONE defect each.

Usage:
  python3 mutate.py                 # rewrite every derived fixture listed in MUTATIONS
  python3 mutate.py NAME [NAME ...] # rewrite only the named fixtures
  python3 mutate.py --check [NAME]  # rebuild into a temp dir and compare with the committed
                                    # fixtures; exit 1 on any drift (nothing is written)

Each fixture is a fresh copy of blast_green with one mutation applied. A sha256 sidecar
(`<hex>  <name>`, the `shasum -a 256` form) is refreshed after the mutation UNLESS the defect is
the sidecar itself, so a red fixture differs from blast_green in at most the mutated file and its
sidecar. Fixtures that need two files to stay coherent (blast_frame_overlap_note: a graph frame and
its brief mirror) are notes/greens, never single-defect reds. Edit blast_green first, then re-run
this script; later fixture units extend MUTATIONS rather than hand-editing a copy.
Stdlib only; paths are resolved relative to this file.
"""
import filecmp
import hashlib
import json
import os
import shutil
import sys
import tempfile

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GREEN = os.path.join(TESTS, "blast_green")


def _load(d, rel):
    with open(os.path.join(d, rel), encoding="utf-8") as fh:
        return json.load(fh)


def _save(d, rel, obj):
    with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, indent=2) + "\n")


def _sidecar(d, rel):
    with open(os.path.join(d, rel), "rb") as fh:
        hx = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(d, rel + ".sha256"), "w", encoding="utf-8") as fh:
        fh.write(f"{hx}  {os.path.basename(rel)}\n")


def _edit(rel, fn, sidecar=False):
    """Mutation: load rel, apply fn(obj) IN PLACE (its return value is ignored), save, refresh sidecar."""
    def run(d):
        obj = _load(d, rel)
        fn(obj)
        _save(d, rel, obj)
        if sidecar:
            _sidecar(d, rel)
    return run


def _unit(uid):
    return lambda g: next(u for u in g["units"] if u["id"] == uid)


def _fp(uid):
    return f"units/{uid}/footprint.json"


def _add_change(path, status="A"):
    return lambda fp: fp["changes"].append({"path": path, "status": status, "from_path": None,
                                            "sha256_before": None if status == "A" else "0" * 64,
                                            "sha256_after": "f" * 64})


def _remove_footprint(d):
    os.remove(os.path.join(d, _fp("U02")))
    os.remove(os.path.join(d, _fp("U02") + ".sha256"))


def _bad_sidecar(d):
    with open(os.path.join(d, _fp("U02") + ".sha256"), "w", encoding="utf-8") as fh:
        fh.write(hashlib.sha256(b"").hexdigest() + "  footprint.json\n")


def _sha(d, rel):
    with open(os.path.join(d, rel), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _overlap_frames(d):
    """U01's frame also claims docs/api.md (U03's docs/** covers it): graph + brief mirror stay equal,
    and U01's verify.json is re-bound to the edited brief (I42), so the only finding is the NOTE."""
    old = _sha(d, "units/U01/brief.json")
    for rel, get in (("graph.json", _unit("U01")), ("units/U01/brief.json", lambda b: b)):
        obj = _load(d, rel)
        get(obj)["frame"]["modifies"].append("docs/api.md")
        _save(d, rel, obj)
    vp = os.path.join(d, "units/U01/verify.json")
    with open(vp, encoding="utf-8") as fh:
        text = fh.read()
    with open(vp, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, _sha(d, "units/U01/brief.json")))


def _del(key):
    def f(obj):
        del obj[key]
    return f


# name -> (mutation, what it breaks). U01/U03 ship in wave 1 (frames src/app/**, docs/**);
# U02 informs in wave 2 with an empty footprint and no impact.json.
MUTATIONS = {
    "blast_version_gated_silent": (_edit("fsm-state.json", lambda s: s.update(validator_version="1.14.0")),
                                   "green re-stamped 1.14.0: unjudged, counted as N-I45 arm BLAST-T1"),
    "blast_no_deliverable": (_edit("graph.json", lambda g: _del("deliverable")(_unit("U02")(g))), "I60-1"),
    "blast_ships_no_frame": (_edit("graph.json", lambda g: _del("frame")(_unit("U01")(g))), "I60-2"),
    "blast_bad_pattern": (_edit("graph.json", lambda g: _unit("U01")(g)["frame"]["modifies"].append("../outside/**")),
                          "I60-2"),
    "blast_brief_frame_drift": (_edit("units/U01/brief.json", lambda b: b["frame"]["modifies"].append("src/extra/**")),
                                "I60-2"),
    "blast_output_outside_frame": (_edit("units/U01/brief.json", lambda b: b["outputs"].append("lib/other.py")),
                                   "I60-2"),
    "blast_footprint_missing": (_remove_footprint, "I60-3"),
    "blast_footprint_stale": (_edit(_fp("U02"), lambda f: f.update(iteration=1), sidecar=True), "I60-3"),
    "blast_footprint_sha_mismatch": (_bad_sidecar, "I60-3"),
    "blast_capture_error": (_edit(_fp("U02"), lambda f: f.update(
        capture_error="git diff-tree exited 128: fatal: bad object", changes=[]), sidecar=True), "I60-3"),
    "blast_write_outside_frame": (_edit(_fp("U01"), _add_change("lib/util.py"), sidecar=True), "I60-4"),
    "blast_immutable_touched": (_edit(_fp("U01"), _add_change("src/app/generated/table.py"), sidecar=True), "I60-4"),
    "blast_informs_wrote": (_edit(_fp("U02"), _add_change("src/app/parse.py", "M"), sidecar=True), "I60-5"),
    "blast_mode_none_with_ships": (_edit("fsm-state.json", lambda s: s["blast"].update(mode="none")), "I60-6"),
    "blast_stamp_missing": (_edit("fsm-state.json", _del("blast")), "I60-6"),
    "blast_bad_base_sha": (_edit("fsm-state.json", lambda s: s["blast"].update(base_sha=None)), "I60-6"),
    "blast_wave_overlap": (_edit(_fp("U03"), _add_change("src/app/parse.py", "M"), sidecar=True), "I61-1"),
    "blast_unattributed": (_edit(_fp("U01"), lambda f: f.update(unattributed=["scratch/notes.txt"]), sidecar=True),
                           "I61-2"),
    "blast_frame_overlap_note": (_overlap_frames, "N-I61 (exit 0)"),
    # Crash safety (absent / wrong-typed keys): each must yield FAIL rows, never a traceback.
    "blast_crash_footprint_types": (_edit(_fp("U01"), lambda f: f.update(changes="src/app/parse.py", iteration="2"),
                                          sidecar=True), "I60-3 wrong types"),
    "blast_crash_footprint_keys": (_edit(_fp("U01"), lambda f: [f.pop(k) for k in
                                         ("iteration", "changes", "unattributed", "capture_error")], sidecar=True),
                                   "I60-3/I61-2 absent keys"),
    "blast_crash_frame_type": (_edit("graph.json", lambda g: _unit("U01")(g).update(frame="src/app/**")),
                               "I60-2 frame not an object"),
}


def build(name, dest_root):
    dest = os.path.join(dest_root, name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(GREEN, dest, ignore=shutil.ignore_patterns("__pycache__"))
    MUTATIONS[name][0](dest)
    return dest


def _same_tree(a, b):
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__"])
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    if filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)[1:] != ([], []):
        return False
    return all(_same_tree(os.path.join(a, s), os.path.join(b, s)) for s in cmp.common_dirs)


def main(argv):
    check = "--check" in argv
    names = [a for a in argv if a != "--check"] or sorted(MUTATIONS)
    unknown = [n for n in names if n not in MUTATIONS]
    if unknown:
        print(f"unknown fixture(s): {unknown}", file=sys.stderr)
        return 2
    if not check:
        for n in names:
            build(n, TESTS)
            print(f"wrote {n}  ({MUTATIONS[n][1]})")
        return 0
    drift = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in names:
            if not _same_tree(build(n, tmp), os.path.join(TESTS, n)):
                drift.append(n)
    for n in drift:
        print(f"DRIFT  {n}: committed fixture differs from blast_green + its mutation")
    print(f"checked {len(names)} fixture(s), {len(drift)} drifted")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
