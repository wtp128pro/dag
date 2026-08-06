#!/usr/bin/env python3
"""Shared fixture builder for U29: a minimal 1.13.0-stamped run dir with a case_set
and a case_set_discharge, built from tests/good (which is register-EMPTY)."""
import json, os, shutil, copy

REPO = "/Users/mborodia/Developer/dag"
GOOD = os.path.join(REPO, "plugins/dag/skills/dag/scripts/tests/good")
SCHEMAS = os.path.join(REPO, "plugins/dag/skills/dag/schemas")
assert os.path.isdir(SCHEMAS), SCHEMAS

RRNR = ("The brief carries no dod_refs[] and no non_goal_refs[]; searched clarifications.json "
        "for a register item this unit traces to and found none, so the entry cites no "
        "requirement_ref.")

ENTRIES = [
    {"id": "C1",
     "check": "units/U01/debrief.json:1 the findings count",
     "check_form": "locator",
     "trigger_ref": "10-14 findings",
     "requirement_ref_none_reason": RRNR,
     "required_observations": ["the debrief records between 10 and 14 findings"],
     "forbidden_observations": ["a count quoted from an earlier run"],
     "production_path": False,
     "production_path_none_reason": "A debrief is read by the verifier, never executed."},
    {"id": "C2",
     "check": "units/U01/debrief.json:2 the source dating",
     "check_form": "locator",
     "trigger_ref": "each with >=1 dated primary source",
     "requirement_ref_none_reason": RRNR,
     "required_observations": ["every finding cites at least one dated primary source"],
     "forbidden_observations": ["an undated source counted as dated"],
     "production_path": False,
     "production_path_none_reason": "A debrief is read by the verifier, never executed."},
]

def _row(cid, entry):
    return {"id": cid, "origin": "orchestrator", "outcome": "discharged",
            "evidence": "measured in the fixture run", "evidence_tier": "located",
            "non_vacuity": [{"observation_ref": o,
                             "counterfactual": "mutated the artifact so the observation is absent",
                             "counterfactual_result": "not-run",
                             "reason": "locator-form check; no executable counterfactual exists"}
                            for o in entry["required_observations"] + entry["forbidden_observations"]]}

def build(dest, stamp="1.13.0", extra_on_C1=None):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(GOOD, dest)
    f = json.load(open(os.path.join(dest, "fsm-state.json")))
    f["validator_version"] = stamp
    json.dump(f, open(os.path.join(dest, "fsm-state.json"), "w"), indent=1)

    bp = os.path.join(dest, "units/U01/brief.json")
    b = json.load(open(bp))
    b["case_set"] = copy.deepcopy(ENTRIES)
    json.dump(b, open(bp, "w"), indent=1)

    dp = os.path.join(dest, "units/U01/debrief.json")
    d = json.load(open(dp))
    rows = [_row("C1", ENTRIES[0]), _row("C2", ENTRIES[1])]
    if extra_on_C1:
        rows[0].update(extra_on_C1)
    d["case_set_discharge"] = rows
    json.dump(d, open(dp, "w"), indent=1)
    return dest

# a schema-valid value for each of the ten brief-owned keys, so the ONLY thing wrong with
# the row is that the key is present at all
VALUES = {
    "check": "units/U01/debrief.json:1 the findings count",
    "check_form": "locator",
    "trigger_ref": "10-14 findings",
    "requirement_ref": "some register item",
    "requirement_ref_none_reason": RRNR,
    "required_observations": ["the debrief records between 10 and 14 findings"],
    "forbidden_observations": ["a count quoted from an earlier run"],
    "forbidden_observations_none_reason": "searched the requirement_ref text for clauses",
    "production_path": True,
    "production_path_none_reason": "A debrief is read by the verifier, never executed.",
}
# the four keys some registry text NAMES, vs the six it does not (U29 brief)
NAMED = ("check", "check_form", "trigger_ref", "requirement_ref")
UNNAMED = ("requirement_ref_none_reason", "required_observations", "forbidden_observations",
           "forbidden_observations_none_reason", "production_path", "production_path_none_reason")
