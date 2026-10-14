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


def _vf(uid):
    return f"units/{uid}/verify.json"


def _row(oid, **repl):
    """Audit-row edit on an aggregated verify.json: replace=True swaps the whole row for repl,
    otherwise repl's keys are updated into the existing row of obligation oid."""
    replace = repl.pop("replace", False)

    def f(v):
        r = next(x for x in v["blast_audit"]["rows"] if x["obligation_id"] == oid)
        if replace:
            r.clear()
            r["obligation_id"] = oid
        r.update(repl)
    return f


def _remove_impact(d):
    os.remove(os.path.join(d, "units/U01/impact.json"))
    os.remove(os.path.join(d, "units/U01/impact.json.sha256"))


_IG = "integration.json"


def _ig(fn):
    """integration.json edit; the sidecar is refreshed so the defect is the record, not its binding."""
    return _edit(_IG, fn, sidecar=True)


def _replay(unit, case, **repl):
    def f(i):
        if repl.pop("drop", False):
            i["replay"] = [r for r in i["replay"] if (r["unit_id"], r["case_id"]) != (unit, case)]
        else:
            next(r for r in i["replay"] if (r["unit_id"], r["case_id"]) == (unit, case)).update(repl)
    return f


def _remove_integration(d):
    os.remove(os.path.join(d, _IG))
    os.remove(os.path.join(d, _IG + ".sha256"))


def _census_up(i):
    i["censuses"][0].update(tip=i["censuses"][0]["tip"] + 1, added=1)


_ACCEPT = {"items": ["I64-7:crash-class"],
           "rationale": "the one added crash-class site is a deliberate fixture of the census itself",
           "decision_ref": "DECISIONS.md#D1"}


def _override(*integration_edits):
    """A well-formed blast_accepted naming ONLY census 'crash-class' (fsm-state.json + DECISIONS.md), plus the
    integration.json edits that raise the findings. Necessarily multi-file: an override, the decision it cites
    and the finding it names live in three artifacts, so these are not single-defect derivations."""
    def run(d):
        for fn in integration_edits:
            _ig(fn)(d)
        _edit("fsm-state.json", lambda s: s.update(blast_accepted=json.loads(json.dumps(_ACCEPT))))(d)
        with open(os.path.join(d, "DECISIONS.md"), "w", encoding="utf-8") as fh:
            fh.write("# Decisions\n\n## D1 — accept the crash-class census increase\n\n"
                     "The census itself is under test; the one added site is intended. Accepted per item.\n")
    return run


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
    # I62 — impact obligations settled. U01 (ships) has O1/O2 exercised and O3 a coupling owned_by
    # U03; U03 (ships) has O1 unaffected. A verify.json edit needs no sidecar (nothing hashes it);
    # an impact.json edit refreshes impact.json.sha256 so the defect is the binding, not the sidecar.
    "blast_impact_missing": (_remove_impact, "I62-1"),
    "blast_impact_unbound": (_edit("units/U01/impact.json", lambda i: i.update(footprint_sha256="0" * 64),
                                   sidecar=True), "I62-1"),
    "blast_audit_missing": (_edit(_vf("U01"), _del("blast_audit")), "I62-2"),
    "blast_audit_partial": (_edit(_vf("U01"), lambda v: v["blast_audit"].update(
        rows=[r for r in v["blast_audit"]["rows"] if r["obligation_id"] != "O2"])), "I62-2"),
    "blast_exercised_no_red": (_edit(_vf("U01"), _row("O1", red_input="  ")), "I62-3"),
    "blast_owned_by_dangling": (_edit(_vf("U01"), _row("O3", owner_unit="U99")), "I62-4"),
    "blast_unaffected_no_rationale": (_edit(_vf("U03"), _row("O1", rationale="  ")), "I62-5"),
    "blast_broken_on_pass": (_edit(_vf("U01"), _row("O2", replace=True, disposition="broken",
                                                    rationale="parse() now rejects the empty string the test feeds it")),
                             "I62-6"),
    "blast_coupling_unaffected": (_edit(_vf("U01"), _row("O3", replace=True, disposition="unaffected",
                                                         rationale="the guide quotes the old heading only")),
                                  "I62-7"),
    # Crash safety (absent / wrong-typed keys): each must yield FAIL rows, never a traceback.
    "blast_crash_footprint_types": (_edit(_fp("U01"), lambda f: f.update(changes="src/app/parse.py", iteration="2"),
                                          sidecar=True), "I60-3 wrong types"),
    "blast_crash_footprint_keys": (_edit(_fp("U01"), lambda f: [f.pop(k) for k in
                                         ("iteration", "changes", "unattributed", "capture_error")], sidecar=True),
                                   "I60-3/I61-2 absent keys"),
    "blast_crash_frame_type": (_edit("graph.json", lambda g: _unit("U01")(g).update(frame="src/app/**")),
                               "I60-2 frame not an object"),
    "blast_crash_impact_types": (_edit("units/U01/impact.json", lambda i: [i.update(obligations="O1", iteration="2"),
                                                                           i.pop("footprint_sha256")], sidecar=True),
                                 "I62-1 wrong types + absent footprint_sha256"),
    "blast_crash_audit_types": (_edit(_vf("U01"), lambda v: [v["blast_audit"].pop("impact_sha256"), v["blast_audit"].update(
        rows=["O1", {"disposition": "exercised"}, {"obligation_id": "O2", "disposition": "exercised", "check": 5,
                                                  "exit_code": "0", "red_input": None},
              {"obligation_id": "O3", "disposition": "owned_by", "owner_unit": ["U03"]}])]),
                                "I62-2..4 non-object rows, absent keys, wrong-typed fields"),
    # I63 — end re-run (integration.json replay / union_changes), I64 — integration record and blast config.
    # blast_green carries a COMPLETE run-dir blast-config.json (all keys: one regression command matching its
    # differential row, a must_not_increase census, a test surface), so no fixture leans on the no-config arm.
    "blast_replay_missing": (_ig(_replay("U01", "C1", drop=True)), "I63-1"),
    "blast_replay_red": (_ig(_replay("U01", "C1", exit_code=1)), "I63-1"),
    "blast_post_verify_mutation": (_ig(lambda i: next(c for c in i["union_changes"] if c["path"] == "src/app/parse.py")
                                       .update(sha256_tip="e" * 64)), "I63-2"),
    "blast_integration_missing": (_remove_integration, "I64-1"),
    "blast_integration_start_mismatch": (_ig(lambda i: i.update(base_sha="1" * 40)), "I64-1"),
    "blast_identical_control": (_ig(lambda i: i.update(tip_tree_digest=i["base_tree_digest"])), "I64-2"),
    "blast_unowned_write": (_ig(lambda i: i.update(unowned_writes=["lib/stray.py"])), "I64-3"),
    "blast_shared_path_uncovered": (_ig(lambda i: i.update(multi_writer_paths=[
        {"path": "src/app/parse.py", "units": ["U01", "U04"]}])), "I64-4"),
    "blast_delta_unexplained": (_ig(lambda i: i["differential"][0].update(
        intended_change_ref="parse() was rewritten")), "I64-5"),
    "blast_weakening_unlisted": (_ig(lambda i: i.update(test_weakening=[
        {"kind": "test-file-deleted", "detail": "T2: tests/test_one.py test file deleted",
         "intended_change_ref": None}])), "I64-6"),
    "blast_census_increase": (_ig(_census_up), "I64-7"),
    "blast_override_malformed": (_edit("fsm-state.json", lambda s: s.update(blast_accepted=dict(
        _ACCEPT, decision_ref="NOTES.md#D1"))), "I64-8 (5) decision_ref names no DECISIONS.md"),
    "blast_override_wellformed": (_override(_census_up), "N-I64 (exit 0): the named census finding downgraded"),
    "blast_override_partial": (_override(_census_up, lambda i: i.update(unowned_writes=["lib/stray.py"])),
                               "I64-3 still FAILs: the override names only the census"),
    # No blast config anywhere (blast_green minus blast-config.json; its workspace_root does not exist, so no
    # <workspace>/.dag/blast.json either): the fallback arm stays covered now that blast_green carries a config.
    "blast_no_config_control": (lambda d: os.remove(os.path.join(d, "blast-config.json")),
                                "no config, non-empty differential, census added 0, no errors (exit 0 today)"),
    "blast_no_config_errors": (lambda d: [os.remove(os.path.join(d, "blast-config.json")), _ig(lambda i: i.update(
        errors=["regression command 'tests/test_parse.py::test_trailing_newline' timed out after 120s"]))(d)],
                               "I64-5 no config and a non-empty errors[] (not acceptable)"),
    "blast_crash_integration_types": (_ig(lambda i: [i.update(replay="U01/C1", union_changes={"path": "src/app/parse.py"},
                                                              multi_writer_paths=["src/app/parse.py"], test_weakening=[None],
                                                              censuses=[5, {"id": "crash-class", "added": "1"}],
                                                              differential={"regression_id": "x"}, errors="timeout"),
                                                     i.pop("unowned_writes"), i.pop("tip_tree_digest")]),
                                      "I63/I64 wrong types + absent unowned_writes/tip_tree_digest"),
    "blast_crash_override_types": (_edit("fsm-state.json", lambda s: s.update(blast_accepted={
        "items": "I64-7:crash-class", "rationale": 5, "decision_ref": None})), "I64-8 wrong types"),
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
