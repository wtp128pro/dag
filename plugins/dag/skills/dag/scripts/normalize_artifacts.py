#!/usr/bin/env python3
"""normalize_artifacts.py — offline, idempotent, SHAPE-ONLY normalizer for dag
units/<UID>/debrief.json and units/<UID>/verify*.json artifacts.

WHY THIS EXISTS
---------------
Three independent dag-using repos reached the same conclusion: quoting the exact
JSON shape in a subagent's brief is NECESSARY but NOT SUFFICIENT — subagents still
drift on nested key names, container types and enum CASING, systematically, every
wave (dag L2 / L6, music L15 / L25 / L32 / L34, BubbleBrain L8 / L26). The fix all
three converged on is an ORCHESTRATOR-SIDE post-hoc normalization pass, run after a
wave's artifacts land and BEFORE validate_run.py. Until now every project rewrote a
private `.normalize.py` per run. This is that script, shipped once.

CONTRACT (the parts that are not negotiable)
--------------------------------------------
1. SHAPE ONLY. It coerces enum CASING, container TYPES (str->array, dict->array,
   array->str), strips unknown keys from CLOSED nested objects, renames a small set
   of documented key-name synonyms, and fills a missing key only when the value is
   mechanically derivable. It NEVER alters a verdict, a severity, a defect's
   criterion text, evidence text, or any claim. Enum-casing repair ("pass" -> "PASS")
   is deliberately restricted to case-insensitive EXACT matches of a legal enum
   member: it changes the spelling of a value, never which value was meant.
2. OFFLINE. STDLIB ONLY (`argparse`, `copy`, `json`, `re`, `sys`, `pathlib`). It is
   NOT a subset of validate_run.py's imports — `copy` and `pathlib` are not imported
   there — but it is strictly LIGHTER: validate_run.py imports the NON-stdlib
   `jsonschema` (validate_run.py:256), this script imports nothing outside the
   standard library. No network module is imported and no subprocess is spawned.
3. IDEMPOTENT. Every rule's output is a fixed point of that rule, and a file is
   rewritten only when its normalized text differs from the text on disk, so a
   second run over the same input is a byte-identical no-op.
4. NOT WIRED INTO validate_run.py. It is a separate, opt-in orchestrator tool. It
   adds no invariant, no check and no failure mode to the validator.
5. SAFE BY DEFAULT. Dry-run unless --write. Anything it cannot map with confidence
   is left ALONE and surfaced as an ADVISORY rather than guessed at. Anything it
   drops or rewrites is reported verbatim (stdout report + --json summary, and
   drops are echoed to stderr).
6. CONTENT GUARD (structural enforcement of clause 1, not a promise). After every
   run over a document, `content_guard()` re-walks the BEFORE and AFTER documents
   and requires that every LEAF value present before — string, int, float, bool,
   null — is accounted for AT ITS JSON PATH after: it survives verbatim there, or
   was recorded verbatim in a `drop` for that path, or a `change` for that path
   declares a legal enum repair / total type coercion, or a `change` at an ancestor
   path declares a container restructuring that accounts for it inside that subtree.
   A violation is a hard stop: the file is NOT written and the run exits 3. This is
   what makes a rule that quietly eats prose, or one that deletes a value outright,
   LOUD instead of silent.
   Scope, stated plainly: the guard refuses DESTRUCTION. It does not police
   MIS-PLACEMENT — a value moved to the wrong slot inside a subtree whose container
   coercion was declared still satisfies clause 4.
7. PROVENANCE. Every rule label carries a qualified corpus lesson id in
   RULE_PROVENANCE, and every synonym-table entry names the lesson that documents
   it. `--self-test` fails if a rule fires under a label with no provenance.

USAGE
-----
    normalize_artifacts.py RUN_DIR|FILE...          # dry run: report only
    normalize_artifacts.py --write RUN_DIR          # apply
    normalize_artifacts.py --json RUN_DIR           # machine-readable summary
    normalize_artifacts.py --self-test              # embedded contract tests

EXIT CODES
----------
    0  normal (whether or not changes/advisories were found), and also for a
       readable file that is simply not a debrief*/verify* artifact — that is an
       ADVISORY SKIP, not an error.
    2  input error: a path that does not exist, undecodable JSON, a JSON document
       whose top level is not an object, or an unwritable target under --write
       — and, under --self-test, a failing self-test.
    3  CONTENT-GUARD VIOLATION: normalizing would have destroyed a leaf value at its
       json path without recording it. Nothing was written. This is a bug in this
       script. NOTE: exit 3 fires in DRY RUN too, so criterion-1-style wording
       "non-zero only on unreadable input" does not describe this taxonomy.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

VERSION = "1.1.1"

# --------------------------------------------------------------------------
# Vocabularies (MIRRORS of schemas/debrief.schema.json + schemas/verify.schema.json)
#
# D2 (disclosed risk): these are hand-mirrored copies of schema knowledge, and
# `strip_closed()` DELETES under --write, so a closed-key set that silently rots
# out of sync with its schema would start stripping a newly-legitimate key from
# every artifact. The defence is `--self-test`, which loads the two schema files and
# asserts EVERY vocabulary, closed-key set, required-key list and scalar-type entry
# below against them (see schema_mirror_test() / T7a-e), so a schema edit that is not
# mirrored here fails the test rather than deleting data. It is a HAND-RUN command;
# nothing invokes it automatically. The content guard is NOT a second defence here:
# strip_closed() calls rep.drop() unconditionally, so schema rot presents as a
# REPORTED deletion, which the guard is required (clause 6, case 2) to accept.
# --------------------------------------------------------------------------

EVIDENCE_TYPES = [
    "empirical-world-fact", "code-behavior", "api-tool-contract",
    "numeric-quantitative", "causal", "design-judgment", "provenance-quote",
]
# Documented drift -> enum. EVERY entry names the qualified lesson that RECORDS a
# subagent actually emitting it. v1.0.0 shipped 47 synonym entries; 37 of them were
# invented by analogy and traced to no documented drift mode, so they were deleted
# (v1.1.0). Surface is allocated by the corpus, not by the schema's shape.
# Classification of an evidence ROW, never of a claim's content or truth.
EVIDENCE_TYPE_SYNONYMS = {
    # MU-L15, verbatim: "values outside the enum (e.g. 'build'/'test'/'grep'/
    # 'guardrail'/'numeric')" + "a build/test/grep claim is code-behavior".
    "build": "code-behavior", "test": "code-behavior", "grep": "code-behavior",
    "guardrail": "code-behavior", "numeric": "numeric-quantitative",
    # DAG-L6, the dag-side drift list quoted in this unit's brief.
    "executable": "code-behavior", "count": "numeric-quantitative",
    "observation": "empirical-world-fact", "source-cross-check": "provenance-quote",
}
SOURCE_TIERS = ["T-VENDOR", "T-COMM", "T-LOCAL", "T-PARAM"]
RETRIEVAL_RUNGS = ["live-fetch", "vendored-docs", "cached-copy", "parametric-only"]
CONFIDENCE = ["high", "medium", "low"]
VERDICTS = ["PASS", "FAIL", "DISAGREE"]
SEVERITIES = ["blocker", "major", "minor"]
GUARDRAIL_STATUS = ["respected", "violated", "not-applicable"]
PANEL_LENSES = ["correctness", "reproduce", "guardrail"]
OWED_STATUS = ["covered", "covered-downgraded", "uncovered"]
PROBE_KINDS = ["reopen", "chase"]
SOURCE_ORIGINS = ["required_sources", "context_pointer", "owed_note", "coverage_basis"]
SOURCE_OUTCOMES = ["consulted-evidenced", "unreachable-declared", "not-consulted"]
TIERS = ["light", "standard", "full"]
# I41 (1.11.0) panel_adjudication enums. Declared so the BIDIRECTIONAL T7a2 can see them
# mirrored; deliberately NOT added to ALL_VOCAB, because ALL_VOCAB is the content guard's
# allow-list of values this script may WRITE, and no code path repairs these positions.
# Widening the guard's permission surface without a corresponding writer would weaken it.
ADJUDICATION_RESOLUTIONS = ["repoll", "withdrawn", "escalated-p7"]
DISPOSITIONS = ["downgraded-minor", "withdrawn", "overruled-by-repoll", "upheld"]
# case_set contract enums (debrief.case_set_discharge[]). Declared for the same reason
# and on the same terms as the I41 pair above: mirrored so the BIDIRECTIONAL T7a2 can see
# them, and deliberately NOT added to ALL_VOCAB, because ALL_VOCAB is the content guard's
# allow-list of values this script may WRITE and no code path repairs these positions.
# They are also the positions where guessing would be WORST: `outcome` and
# `counterfactual_result` are the vacuity discriminators, so a normalizer that mapped an
# out-of-enum value onto `discharged` or `red` would manufacture the exact certification
# the mechanism exists to withhold. Out-of-enum here must stay a refusal, never a repair.
DISCHARGE_ORIGINS = ["orchestrator", "executor"]
DISCHARGE_OUTCOMES = ["discharged", "violated", "infeasible", "vacuous"]
EVIDENCE_TIERS = ["executable", "located", "asserted"]
COUNTERFACTUAL_RESULTS = ["red", "not-run"]
CHECK_FORMS = ["command", "locator"]

# Closed objects (additionalProperties:false in the schemas). Unknown keys inside
# these are stripped — and the stripped key AND its value are reported verbatim.
CLOSED_EVIDENCE_ROW = {
    "claim", "type", "evidence", "reproducible", "source_tier", "retrieval_rung",
    "accessed", "vendor_silent", "vendor_surface_searched", "covers_owed",
    "source_refs", "extracted_premises", "extracted_premises_none_reason",
}
CLOSED_ASC_ROW = {"criterion", "met", "evidence_ref"}
CLOSED_FOOTPRINT = {"tokens_consumed", "within_budget"}
CLOSED_PREMISE_CHECK = {
    "executor_premise_quoted", "is_load_bearing", "counter_reran_independently", "outcome",
}
CLOSED_GUARDRAIL_ROW = {"non_goal", "status", "note"}
CLOSED_OWED_ROW = {"owed_id", "status", "row_refs", "note"}
CLOSED_PROBE_ROW = {"row_ref", "claim_echo", "kind", "outcome"}
CLOSED_SOURCES_ROW = {"source_id", "origin", "outcome", "note"}
CLOSED_CVC_ROW = {"register_id", "outcome"}

CLOSED_RETRIEVAL_COVERAGE = {
    "tier_at_verification", "owed_check", "retrieval_probes",
    "retrieval_probes_none_reason", "sources_check",
}

# case_set contract closed objects. Mirror declarations on the I41 terms: no call site
# walks into `case_set_discharge` / `case_set_audit` yet, so these six sets are INERT at
# runtime — they exist so T7b/T7c compare them and so a LATER schema edit at these pointers
# fails the self-test rather than rotting silently. (The two sites in this file that ARE
# runtime-live are TOP_LEVEL_DEBRIEF / TOP_LEVEL_VERIFY: measured on an unmirrored tree,
# `case_set_discharge` drew "key is outside debrief.schema.json … it may hold narrative that
# belongs in `result`/`handoff_notes`" — advice to relocate the ONLY home an executor-ADDED
# entry has, i.e. the I41 failure mode reproduced on a new key. Mirrored: 0 advisories.)
# The section-2.1 keys below are legal only on an `origin: "executor"` row; that conditional
# lives in the schema's allOf and is deliberately NOT mirrored here — this set is the
# closed-key UNION, which is what an additionalProperties:false property set is.
CLOSED_DISCHARGE_ROW = {
    "id", "origin", "outcome", "evidence", "evidence_tier", "asserted_reason",
    "non_vacuity", "infeasible_reason", "vacuity_finding", "check", "check_form",
    "trigger_ref", "requirement_ref", "requirement_ref_none_reason",
    "required_observations", "forbidden_observations",
    "forbidden_observations_none_reason", "production_path",
    "production_path_none_reason",
}
CLOSED_NON_VACUITY_ROW = {
    "observation_ref", "counterfactual", "counterfactual_result", "reason",
}
CLOSED_CASE_SET_AUDIT = {
    "commitment_sha256", "commitment_iteration", "commitment_match", "discharge_check",
    "novelty_rate", "vocabulary_containment",
}
CLOSED_DISCHARGE_CHECK = {
    "missing_ids", "extra_ids", "duplicate_ids", "tier_shortfall_ids",
}
CLOSED_NOVELTY_RATE = {"derived", "absent_from_executor_evidence"}
CLOSED_VOCABULARY_CONTAINMENT = {"artifact_only_identifiers"}

# Documented key-name synonyms. Applied ONLY when the canonical key is absent, so no
# real value is ever overwritten. Each entry quotes the lesson that RECORDS it; the
# nine speculative premise_check variants and all seven acceptance_self_check
# variants shipped in v1.0.0 were deleted (no lesson names them).
PREMISE_CHECK_SYNONYMS = {
    # DAG-L2, verbatim: "Never invent synonyms (executor_premise !=
    # executor_premise_quoted)".
    "executor_premise": "executor_premise_quoted",
}
# BB-L26, verbatim: "on any retry (iteration>1) prior_feedback is schema-required to
# carry exactly actionable_changes, do_not_touch AND a non-empty changes_made —
# natural names like 'addressed'/'not_addressed' fail."  Only 'addressed' has an
# unambiguous canonical target; 'not_addressed' is NOT mapped (it is not
# do_not_touch — do_not_touch is the verifier's echo, not the executor's omission)
# and is surfaced as an advisory instead.
PRIOR_FEEDBACK_SYNONYMS = {"addressed": "changes_made"}
PRIOR_FEEDBACK_KEYS = {"actionable_changes", "do_not_touch", "changes_made"}

TOP_LEVEL_DEBRIEF = {
    "unit_id", "persona", "iteration", "result", "evidence_table", "socratic",
    "acceptance_self_check", "assumptions", "residual_risks", "confidence",
    "footprint", "handoff_notes", "prior_feedback", "case_set_discharge",
}
# `panel_adjudication` (I41, 1.11.0) is a LEGITIMATE top-level verify property. Before it
# was mirrored here, `unknown-top-level-key` advised an orchestrator that it "is outside
# verify.schema.json" and to fold it into `audit_notes` — i.e. to destroy an object that
# I41-1 REQUIRES on a PASS with a dissenting panel member. That is the exact schema-rot
# failure mode T7b/T7c exist to catch, and it is why a schemas/*.json edit owes a
# `--self-test` re-run (see CLAUDE.md).
TOP_LEVEL_VERIFY = {
    "unit_id", "verifier_persona", "verdict", "iteration", "executor_reasoning_seen",
    "inputs_reviewed", "audit_notes", "panel", "panel_adjudication", "verify_rounds",
    "converged", "feedback", "defects", "socratic", "premise_check", "disagreement",
    "retrieval_coverage", "guardrail_compliance", "consequential_verbatim_check",
    "case_set_audit",
}

# Required-key lists, mirrored from the schemas' own `required` arrays and asserted
# against them in --self-test. Presence is checked GENERICALLY from this table (v1.0.0
# hand-enumerated 3 of ~70 positions and missed, e.g., verify.defects[].severity).
# Pointer syntax: `$` = document root, `.k` = property, `[]` = array items.
REQUIRED_KEYS = {
    "debrief": {
        "$": ["confidence", "evidence_table", "footprint", "iteration", "persona",
              "result", "socratic", "unit_id"],
        "$.evidence_table[]": ["claim", "evidence", "reproducible", "type"],
        "$.socratic": ["confidence", "counter", "pivot", "premise"],
        "$.acceptance_self_check[]": ["criterion", "met"],
        "$.footprint": ["tokens_consumed", "within_budget"],
        # case_set contract. Mirrored so the bidirectional T7d2 is satisfied and so a
        # LATER schema edit at these pointers fails the self-test. Inert at runtime for the
        # same reason as the I41 entries below (check_required is dispatched from explicit
        # pointers in normalize_debrief), and deliberately so: the CONDITIONAL requirements
        # (non_vacuity iff discharged, the reason fields, the origin-scoped section-2.1
        # keys) live in the schemas' allOf, which no offline predicate here evaluates.
        "$.case_set_discharge[]": ["evidence", "evidence_tier", "id", "origin", "outcome"],
        "$.case_set_discharge[].non_vacuity[]": ["counterfactual", "counterfactual_result",
                                                 "observation_ref"],
    },
    "verify": {
        "$": ["defects", "executor_reasoning_seen", "feedback", "iteration",
              "premise_check", "socratic", "unit_id", "verdict", "verifier_persona"],
        "$.panel[]": ["lens", "verdict"],
        # I41 (1.11.0). Mirrored so the bidirectional T7d2 is satisfied and so a LATER
        # schema edit at these pointers fails the self-test. No call site walks into
        # panel_adjudication yet, so these entries are inert at runtime (check_required is
        # dispatched from explicit pointers in normalize_verify) — they are mirror
        # declarations, not new advisories, and the 371-artifact sweep is unchanged.
        "$.panel[].defects[]": ["criterion", "severity"],
        "$.panel_adjudication.dissent_refs[]": ["defect_index", "lens"],
        "$.panel_adjudication.dispositions[]": ["defect_index", "disposition", "lens"],
        "$.panel_adjudication.repoll[]": ["lens", "post_verdict", "pre_verdict"],
        "$.feedback": ["actionable_changes"],
        "$.defects[]": ["criterion", "severity"],
        "$.socratic": ["confidence", "counter", "pivot", "premise"],
        "$.premise_check": ["counter_reran_independently", "executor_premise_quoted",
                            "is_load_bearing", "outcome"],
        "$.retrieval_coverage": ["owed_check", "retrieval_probes", "sources_check"],
        "$.retrieval_coverage.owed_check[]": ["owed_id", "row_refs", "status"],
        "$.retrieval_coverage.retrieval_probes[]": ["claim_echo", "kind", "outcome",
                                                    "row_ref"],
        "$.retrieval_coverage.sources_check[]": ["origin", "outcome", "source_id"],
        "$.guardrail_compliance[]": ["non_goal", "status"],
        "$.consequential_verbatim_check[]": ["outcome", "register_id"],
        # case_set contract (SPEC section 6.2). Same terms as the debrief entries above:
        # mirror declarations, inert at runtime, no new advisory. `discharge_check`'s four
        # fields are all REQUIRED and are `[]` when empty — an omitted list is not an empty
        # one, which is why the required array carries all four rather than none.
        "$.case_set_audit": ["commitment_iteration", "commitment_match",
                             "commitment_sha256", "discharge_check", "novelty_rate",
                             "vocabulary_containment"],
        "$.case_set_audit.discharge_check": ["duplicate_ids", "extra_ids", "missing_ids",
                                             "tier_shortfall_ids"],
        "$.case_set_audit.novelty_rate": ["absent_from_executor_evidence", "derived"],
        "$.case_set_audit.vocabulary_containment": ["artifact_only_identifiers"],
    },
}

# Schema-typed SCALAR properties, mirrored from the schemas' own `type` keywords and
# asserted against them in --self-test (T7e). A string standing in for a schema-typed
# integer/boolean is a documented drift CLASS (DAG-L6 / MU-L15), and the class is
# repaired here for `reproducible`, `met`, `is_load_bearing`, `executor_reasoning_seen`,
# `tokens_consumed` and `within_budget`. v1.1.0 deleted the rules for the REMAINING
# members of the same class (iteration, verify_rounds, converged) on the strength of a
# byte-identical sweep over an already-clean corpus, so `"iteration": "2"` — a key both
# schemas declare `required` AND `integer` — passed through with 0 changes and 0
# advisories. v1.1.1 restores DETECTION (an advisory) rather than repair: an advisory
# guesses nothing and rewrites nothing, and it is applied to the whole class from this
# table rather than field by field. Same pointer syntax as REQUIRED_KEYS.
SCALAR_TYPES = {
    "debrief": {
        "$": {"iteration": "integer"},
        "$.evidence_table[]": {"reproducible": "boolean", "vendor_silent": "boolean"},
        "$.acceptance_self_check[]": {"met": "boolean"},
        "$.footprint": {"tokens_consumed": "integer", "within_budget": "boolean"},
        # case_set contract — the schema-typed scalars T7f flagged as unmirrored.
        "$.case_set_discharge[]": {"production_path": "boolean"},
    },
    "verify": {
        "$": {"iteration": "integer", "executor_reasoning_seen": "boolean",
              "verify_rounds": "integer", "converged": "boolean"},
        "$.premise_check": {"is_load_bearing": "boolean",
                            "counter_reran_independently": "boolean"},
        "$.retrieval_coverage.retrieval_probes[]": {"row_ref": "integer"},
        "$.consequential_verbatim_check[]": {"register_id": "integer"},
        # I41 (1.11.0) — the three schema-typed scalars T7f flagged as unmirrored. Inert at
        # runtime for the same reason as the REQUIRED_KEYS entries above.
        "$.panel_adjudication.dissent_refs[]": {"defect_index": "integer"},
        "$.panel_adjudication.dispositions[]": {"defect_index": "integer"},
        "$.panel_adjudication.repoll[]": {"tested_defect": "boolean"},
        # case_set contract (SPEC section 6.2). commitment_match:false is a hard FAIL, so a
        # string "false" standing in for the boolean is exactly the drift class this table
        # exists to DETECT (advisory, never repair — a guessed boolean here would flip a
        # FAIL to a PASS).
        "$.case_set_audit": {"commitment_iteration": "integer",
                             "commitment_match": "boolean"},
        "$.case_set_audit.novelty_rate": {"derived": "integer",
                                          "absent_from_executor_evidence": "integer"},
    },
}

# Every rule label -> the qualified corpus lesson that documents the drift mode it
# repairs. --self-test fails if a label fires with no entry here. v1.0.0 shipped 37
# labels; the 13 that could not produce a lesson id (unit-id-shape, iteration-type,
# converged-type, verify-rounds-type, register-id-type, vendor-silent-type, row-shape,
# lens-case, tier-case, owed-status-case, probe-kind-case, origin-case, outcome-case)
# were DELETED in v1.1.0 rather than kept on the strength of "the schema has a field".
RULE_PROVENANCE = {
    "verdict-case": "BB-L8 (verdict MUST be UPPERCASE; 'pass' seen)",
    "severity-case": "BB-L8 (defects[] severity casing) / MU-L32 ('low'/'nit' seen)",
    "guardrail-status-case": "BB-L8 (status 'PASS'/'PARTIAL' instead of respected/…)",
    "attestation-type": "DAG-L6 (nested type drift; executor_reasoning_seen as a string)",
    "container-type": "MU-L15 (object where an array/string is mandated; audit_notes "
                      "as an array) / BB-L8 / BB-L26 (handoff_notes as a string)",
    "evidence-type-enum": "MU-L15 (evidence_table[].type outside the enum)",
    "reproducible-type": "MU-L32 (evidence_table[].reproducible missing/mis-typed)",
    "footprint-types": "MU-L15 (footprint sub-shape) / DAG-L6",
    "confidence-enum": "BB-L26 (top-level confidence is a STRICT 3-value enum)",
    "confidence-enum-prose-stripped": "BB-L26 / MU-L32 (prose in the strict enum)",
    "socratic-confidence-case": "BB-L26 (socratic.confidence conflated with the "
                                "top-level enum) / MU-L32",
    "closed-object-strip": "MU-L15 (footprint.note) / MU-L25 (premise_check.note) / "
                           "BB-L8 (guardrail row with an extra 'evidence' key)",
    "key-synonym": "DAG-L2 (executor_premise != executor_premise_quoted) / "
                   "BB-L26 (prior_feedback natural key names)",
    "premise-check-types": "MU-L25 (premise_check drift) / DAG-L6",
    "asc-met-type": "DAG-L2 (drift concentrates in acceptance_self_check)",
    "asc-row-shape": "DAG-L2 (acceptance_self_check nested-object drift)",
    "missing-required": "DAG-L2 (nested REQUIRED KEY NAMES) / MU-L32 (omits "
                        "newly-required keys) / BB-L8 (defects missing 'criterion')",
    "fill-derivable": "MU-L32 (adds missing debrief.iteration)",
    "source-tier-enum": "MU-L34 (source_tier ladder)",
    "retrieval-rung-enum": "MU-L32 (retrieval_rung free-text instead of the ladder)",
    "i31-source-tier-absent": "MU-L34 (externally-sourced rows omit source_tier)",
    "row-ref-type": "BB-L26 (row_refs indices)",
    "row-ref-base": "BB-L26 (0-based vs 1-based row_refs; two verifiers in one run)",
    "unknown-top-level-key": "BB-L8 (extra top-level keys like reproduction_result)",
    "panel-in-panelist-file": "MU-L25 (a lone panelist's verify_p<N>.json wrongly "
                              "carried a panel[] array)",
    "retrieval-probes-none-reason": "BB-L26 (empty probe list with no "
                                    "retrieval_probes_none_reason)",
    "prior-feedback-shape": "BB-L26 (prior_feedback natural key names on a retry)",
    # v1.1.1 — RESTORED. v1.1.0 deleted these six because no lesson names the individual
    # FIELD; DAG-L6 and MU-L32 document the CLASS ("type/status/severity written as enum
    # synonyms"; "subagents still drift the enum casing"), and provenance is owed at the
    # granularity the corpus records, not at the granularity of the schema's field list.
    # Without them 'Correctness'/'Standard'/'Covered'/'Reopen'/'Context_Pointer'/
    # 'Not-Consulted' passed with 0 changes AND 0 advisories — silent, not merely unfixed.
    "lens-case": "DAG-L6 (enum casing drift) / MU-L32 (panel[].lens casing)",
    "tier-case": "DAG-L6 (enum casing drift) / MU-L32 (tier_at_verification casing)",
    "owed-status-case": "DAG-L6 (status written as an enum synonym) / MU-L32",
    "probe-kind-case": "DAG-L6 (enum casing drift) / MU-L32 (probe kind casing)",
    "origin-case": "DAG-L6 (enum casing drift) / MU-L32 (sources_check origin casing)",
    "outcome-case": "DAG-L6 (enum casing drift) / MU-L32 (sources_check outcome casing)",
    "scalar-type-mismatch": "DAG-L6 (nested type drift) / MU-L15 (a schema-typed scalar "
                            "written as a string) — DETECTION ONLY, repairs nothing",
    "not-an-artifact": "n/a — driver advisory, repairs nothing",
}
# The content guard is deliberately NOT a rule label: it repairs nothing and reports
# through Report.violations, so it can never be confused for a normalization.

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

class Report:
    """Every mutation and every refusal-to-mutate, recorded."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.changes: list[dict] = []     # what was rewritten
        self.drops: list[dict] = []       # what was REMOVED (value kept verbatim here)
        self.advisories: list[dict] = []  # what was left alone on purpose
        self.violations: list[str] = []   # content-guard failures (hard stop)

    def change(self, jsonpath: str, rule: str, before, after) -> None:
        self.changes.append({"path": jsonpath, "rule": rule,
                             "before": before, "after": after})

    def drop(self, jsonpath: str, rule: str, key: str, value) -> None:
        self.drops.append({"path": jsonpath, "rule": rule, "key": key, "value": value})

    def advise(self, jsonpath: str, rule: str, detail: str) -> None:
        self.advisories.append({"path": jsonpath, "rule": rule, "detail": detail})

    def as_dict(self, wrote: bool) -> dict:
        return {"file": self.path, "written": wrote, "changes": self.changes,
                "drops": self.drops, "advisories": self.advisories,
                "guard_violations": self.violations}


# --------------------------------------------------------------------------
# Primitive coercions (each is its own fixed point)
# --------------------------------------------------------------------------

def to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    return None


def to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("_", "")
        if re.fullmatch(r"-?\d+", s):
            return int(s)
    return None


def enum_case(v, allowed):
    """Case/whitespace-only repair of an enum member. Returns None unless `v` is a
    case-insensitive EXACT match of a legal member — a synonym is never guessed.

    v1.1.0 gated the repair on `s != a`, i.e. on the STRIPPED string differing from the
    member, which made whitespace repair conditional on the CASING also being wrong:
    enum_case('  pass  ') -> 'PASS' but enum_case('  PASS  ') -> None. That is the same
    match-one-string / act-on-another shape as the v1.0.0 socratic bug. The gate belongs
    on the ORIGINAL `v`: padding alone is a real defect, and stripping it off an
    otherwise exact member is not a guess."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    for a in allowed:
        if s.lower() == a.lower() and v != a:
            return a
    return None


def str_array(v):
    """str -> [str]; dict -> ['k: v', ...]. Content preserved verbatim."""
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        out = []
        for k, val in v.items():
            out.append(f"{k}: {val}" if not isinstance(val, str) else f"{k}: {val}")
        return out
    return None


# --------------------------------------------------------------------------
# Generic object helpers
# --------------------------------------------------------------------------

def strip_closed(obj: dict, allowed: set, jp: str, rule: str, rep: Report) -> None:
    for k in [k for k in obj if k not in allowed]:
        rep.drop(jp, rule, k, obj[k])
        del obj[k]


def rename_synonyms(obj: dict, table: dict, jp: str, rule: str, rep: Report) -> None:
    for src, dst in table.items():
        if src in obj and dst not in obj:
            obj[dst] = obj.pop(src)
            rep.change(f"{jp}.{src}", rule, src, dst)


def coerce_enum(obj: dict, key: str, allowed: list, jp: str, rule: str,
                rep: Report) -> None:
    if key not in obj:
        return
    fixed = enum_case(obj[key], allowed)
    if fixed is not None:
        rep.change(f"{jp}.{key}", rule, obj[key], fixed)
        obj[key] = fixed
    elif isinstance(obj[key], str) and obj[key] not in allowed:
        rep.advise(f"{jp}.{key}", rule,
                   f"value {obj[key]!r} is not a member of {allowed} and is not a "
                   f"casing/whitespace variant of one — LEFT UNCHANGED (mapping it "
                   f"would be a guess)")


def coerce_bool(obj: dict, key: str, jp: str, rule: str, rep: Report) -> None:
    if key not in obj or isinstance(obj[key], bool):
        return
    b = to_bool(obj[key])
    if b is None:
        rep.advise(f"{jp}.{key}", rule, f"value {obj[key]!r} is not boolean-coercible — LEFT UNCHANGED")
    else:
        rep.change(f"{jp}.{key}", rule, obj[key], b)
        obj[key] = b


def coerce_int(obj: dict, key: str, jp: str, rule: str, rep: Report) -> None:
    if key not in obj or (isinstance(obj[key], int) and not isinstance(obj[key], bool)):
        return
    i = to_int(obj[key])
    if i is None:
        rep.advise(f"{jp}.{key}", rule, f"value {obj[key]!r} is not integer-coercible — LEFT UNCHANGED")
    else:
        rep.change(f"{jp}.{key}", rule, obj[key], i)
        obj[key] = i


def coerce_str_array(obj: dict, key: str, jp: str, rule: str, rep: Report) -> None:
    if key not in obj or isinstance(obj[key], list):
        return
    arr = str_array(obj[key])
    if arr is None:
        rep.advise(f"{jp}.{key}", rule, f"value of type {type(obj[key]).__name__} is not array-coercible — LEFT UNCHANGED")
    else:
        rep.change(f"{jp}.{key}", rule, obj[key], arr)
        obj[key] = arr


def check_required(obj: dict, kind: str, pointer: str, jp: str, rep: Report) -> None:
    """Generic missing-required advisory, derived from REQUIRED_KEYS (which --self-test
    asserts against the schemas' own `required` arrays). NEVER fills: a required key a
    subagent omitted holds a CLAIM (a verdict, a criterion, an attestation), and
    inventing one is exactly the line this script does not cross."""
    if not isinstance(obj, dict):
        return
    for k in REQUIRED_KEYS.get(kind, {}).get(pointer, []):
        if k not in obj:
            rep.advise(f"{jp}.{k}", "missing-required",
                       f"required by {kind}.schema.json at {pointer} and ABSENT — NOT "
                       f"filled (the value is a claim, not a shape); fix at source")
    _advise_scalar_types(obj, kind, pointer, jp, rep)


def _advise_scalar_types(obj: dict, kind: str, pointer: str, jp: str, rep: Report) -> None:
    """DETECTION-ONLY advisory for the class 'a schema-typed integer/boolean key carries
    a string' (SCALAR_TYPES, asserted against the schemas in --self-test T7e). Where a
    repair rule owns the key it has already run by the time this is reached, so the value
    is no longer a string (repaired) or an advisory already stands at that path (not
    coercible); either way this stays silent and never double-reports. What it catches is
    the REST of the class — iteration / verify_rounds / converged — which v1.1.0 left with
    no rule at all: 0 changes, 0 advisories, on keys both schemas declare required+typed."""
    if not isinstance(obj, dict):
        return
    for k, want in SCALAR_TYPES.get(kind, {}).get(pointer, {}).items():
        if not isinstance(obj.get(k), str):
            continue
        if any(a["path"] == f"{jp}.{k}" for a in rep.advisories):
            continue
        rep.advise(f"{jp}.{k}", "scalar-type-mismatch",
                   f"{obj[k]!r} is a STRING where {kind}.schema.json declares "
                   f"{{'type': {want!r}}} at {pointer}.{k} — LEFT UNCHANGED. Detection "
                   f"only: this script repairs this class where a lesson names the field "
                   f"(reproducible / met / is_load_bearing / executor_reasoning_seen / "
                   f"footprint.*); here it reports and fixes nothing")


def normalize_socratic(doc: dict, rep: Report) -> None:
    """socratic.confidence is pinned by BOTH schemas to ^(high|medium|low)\\b, i.e. the
    enum WORD must lead but a trailing '— <uncertainty>' rationale is legal and must
    survive byte-for-byte.

    v1.0.0 matched `^\\s*(high|medium|low)\\b` against the UNSTRIPPED string and then
    sliced the STRIPPED one with m.end(), eating exactly len(leading whitespace)
    characters of real prose ('   high — caveat' -> 'highthe...'-class corruption).
    Match and slice THE SAME STRING; `m.start()` is always 0 under `^`, so the old
    `- m.start()` correction was a no-op applied to the wrong string."""
    soc = doc.get("socratic")
    if not isinstance(soc, dict):
        return
    c = soc.get("confidence")
    if isinstance(c, str):
        s = c.strip()
        m = re.match(r"^(high|medium|low)\b", s, re.IGNORECASE)
        if m:
            fixed = m.group(1).lower() + s[m.end():]
            if fixed != c:
                rep.change("$.socratic.confidence", "socratic-confidence-case", c, fixed)
                soc["confidence"] = fixed
        else:
            rep.advise("$.socratic.confidence", "socratic-confidence-case",
                       f"{c!r} does not start with high|medium|low — LEFT UNCHANGED "
                       f"(picking a confidence level would be a guess)")


# --------------------------------------------------------------------------
# Content guard (contract clause 6) — structural enforcement of "SHAPE ONLY"
# --------------------------------------------------------------------------

# Every value this script is allowed to WRITE into a string field. A rewritten string
# that is not a member of this set, and not a byte-preserving re-casing of a leading
# member, is a content edit and is refused.
ALL_VOCAB = (EVIDENCE_TYPES + SOURCE_TIERS + RETRIEVAL_RUNGS + CONFIDENCE + VERDICTS
             + SEVERITIES + GUARDRAIL_STATUS + PANEL_LENSES + OWED_STATUS + PROBE_KINDS
             + SOURCE_ORIGINS + SOURCE_OUTCOMES + TIERS)


def walk_leaves(node, path: str = "$", out: list | None = None) -> list:
    """Every LEAF value in a document — str, int, float, bool, null, and empty
    containers — with its json path.

    v1.1.0 walked STRING values only (walk_strings), so an unreported deletion of an
    int, a bool, a list or a null was invisible. That is not a corner: `footprint`, the
    object T6c and the D2 residual risk both use as the worked example, has exactly two
    legitimate properties and BOTH are non-strings (tokens_consumed: int,
    within_budget: bool), so the archetypal schema-rot deletion could not have fired."""
    if out is None:
        out = []
    if isinstance(node, dict) and node:
        for k, v in node.items():
            walk_leaves(v, f"{path}.{k}", out)
    elif isinstance(node, list) and node:
        for i, v in enumerate(node):
            walk_leaves(v, f"{path}[{i}]", out)
    else:
        out.append((path, node))
    return out


def walk_strings(node, path: str = "$") -> list:
    """Every string VALUE in a document, with its json path (the narrow projection of
    walk_leaves used where only prose matters)."""
    return [(p, v) for p, v in walk_leaves(node, path) if isinstance(v, str)]


def _same(a, b) -> bool:
    """Type-strict equality. Plain `==` would let `True` satisfy `1` and vice versa,
    which is exactly the class of silent substitution this guard exists to refuse."""
    return type(a) is type(b) and a == b


def _syn_key(t: str) -> str:
    """THE key normalisation for an EVIDENCE_TYPE_SYNONYMS lookup. Both the repair rule
    and the guard call this, so they cannot diverge: v1.1.0's repair applied
    `.replace(' ', '-')` (it exists to accept DAG-L6's token 'source cross-check' written
    with spaces) while the guard did not, so a repair the shipped rule set legitimately
    made was then declared a content-guard violation — exit 3, nothing written, and every
    unrelated repair in that artifact discarded with it."""
    return t.strip().lower().replace(" ", "-")


def _ancestors(path: str) -> list[str]:
    """Every json path that is a prefix of `path`, longest first:
    '$.a.b[0].c' -> ['$.a.b[0].c', '$.a.b[0]', '$.a.b', '$.a', '$']."""
    out = [path]
    while True:
        cut = max(path.rfind("."), path.rfind("["))
        if cut <= 0:
            break
        path = path[:cut]
        out.append(path)
    return out


def _legal_enum_rewrite(before: str, after: str, dropped: list[str]) -> bool:
    """The ONLY two legal ways a string value may be rewritten."""
    s = before.strip()
    if after in ALL_VOCAB:
        # (a) coercion TO a declared enum member. Any prose the coercion removed must
        #     itself have been recorded verbatim in a drop.
        if s.lower() == after.lower():
            return True
        if s.lower().startswith(after.lower()):
            tail = s[len(after):].strip()
            return not tail or any(tail in d for d in dropped)
        # a declared synonym remap ('grep' -> 'code-behavior'): the whole value was a
        # vocabulary token, not prose. v1.1.0 asked only whether BEFORE was SOME synonym
        # and never whether it maps to AFTER, so ('grep','PASS') and ('count','DISAGREE')
        # were both blessed — the guard would have approved a rewritten VERDICT.
        return EVIDENCE_TYPE_SYNONYMS.get(_syn_key(s)) == after
    # (b) re-casing of a LEADING enum word with a byte-identical tail
    #     ('  High — caveat' -> 'high — caveat').
    for w in ALL_VOCAB:
        if len(s) >= len(w) and s[:len(w)].lower() == w.lower():
            if after[:len(w)] == w and after[len(w):] == s[len(w):]:
                return True
    return False


def _legal_type_coercion(before: str, after) -> bool:
    """A string that became the BOOL or INT it spells is a type repair, not a content
    edit — but only if the declared, total coercions produce exactly that value."""
    if not isinstance(before, str):
        return False
    if isinstance(after, bool):
        return to_bool(before) is after
    if isinstance(after, int):
        return to_int(before) == after
    return False


def _declared_rewrite(value, c: dict, dropped_text: list[str]) -> bool:
    """A change record AT THIS PATH that legally accounts for `value`."""
    if not _same(c["before"], value):
        return False
    if isinstance(value, str) and isinstance(c["after"], str):
        return _legal_enum_rewrite(value, c["after"], dropped_text)
    return _legal_type_coercion(value, c["after"])


def _is_join(c: dict) -> bool:
    """The ONE declared exception to verbatim survival: a container coercion that JOINS
    values into strings ($.audit_notes array->string; a dict->['k: v'] flattening). It is
    gated on a change record FOR THAT PATH, not on a document-wide substring scan."""
    return c["rule"] == "container-type" and (
        isinstance(c["after"], str)
        or (isinstance(c["after"], list) and c["after"]
            and all(isinstance(x, str) for x in c["after"])))


def content_guard(before_doc, after_doc, rep: Report) -> None:
    """Refuse to lose a value. For every LEAF present BEFORE, at its json PATH, require
    one of:

      1. it survives verbatim AT THE SAME PATH (or at the path a declared key-synonym
         rename moved it to);
      2. it was recorded verbatim in a `drop` AT THAT PATH;
      3. a `change` AT THAT PATH declares a legal enum repair or a total type coercion
         that produces exactly the after value;
      4. a `change` at an ANCESTOR path declares a container restructuring, and the value
         is accounted for inside THAT SUBTREE of the after document (verbatim, as a legal
         enum/type repair, or — only for a declared JOIN — as a substring of a joined
         string).

    Anything else is a content edit: recorded as a violation, and the caller must not
    write the file.

    v1.1.0 cleared a before-string with `any(s in t for t in after_all)` — an UNANCHORED
    substring test against every string in the whole after document, with no path key —
    so a value destroyed outright was invisible whenever it occurred as a substring of
    any other value anywhere. Deleting $.verdict = 'PASS' from a real artifact wrote to
    disk with 0 violations because $.audit_notes happened to contain the token 'PASS' in
    a sentence; 7199 of 23388 string values (30.8%) across 371 of 371 real artifacts were
    deletable with the guard silent. The `change` and `drop` lookups matched by VALUE
    alone for the same reason, so one legal re-casing laundered every other occurrence of
    that string in the document.

    RESIDUAL, disclosed: clause 4 is scoped to the subtree of a DECLARED container
    change, but within that subtree it is a search rather than a path match — a rule that
    restructured a container AND moved a value to the wrong slot inside it would pass.
    That is a mis-placement, not a destruction; destruction is what this guard refuses."""
    after_leaves = walk_leaves(after_doc)
    after_map = {p: v for p, v in after_leaves}

    # Declared path remaps: a documented key-name synonym MOVES a subtree wholesale
    # ($.premise_check.executor_premise -> $.premise_check.executor_premise_quoted).
    aliases = [(c["path"], f"{c['path'].rsplit('.', 1)[0]}.{c['after']}")
               for c in rep.changes
               if c["rule"] == "key-synonym" and isinstance(c["after"], str)]

    # Drops, indexed BY PATH (v1.1.0 kept a flat, path-less list of values).
    dropped_at: dict[str, list] = {}
    dropped_text: list[str] = []
    for d in rep.drops:
        for p, v in walk_leaves(d["value"], f"{d['path']}.{d['key']}"):
            dropped_at.setdefault(p, []).append(v)
            if isinstance(v, str):
                dropped_text.append(v)
        if isinstance(d["key"], str):
            dropped_text.append(d["key"])

    changes_at: dict[str, list] = {}
    for c in rep.changes:
        changes_at.setdefault(c["path"], []).append(c)

    def remap(path: str) -> str:
        for old, new in aliases:
            if path == old:
                return new
            if path.startswith(old + ".") or path.startswith(old + "["):
                return new + path[len(old):]
        return path

    for path, value in walk_leaves(before_doc):
        cands = {path, remap(path)}
        if any(p in after_map and _same(after_map[p], value) for p in cands):
            continue                                                        # (1)
        if any(_same(x, value) for p in cands for x in dropped_at.get(p, ())):
            continue                                                        # (2)
        if any(_declared_rewrite(value, c, dropped_text)
               for p in cands for c in changes_at.get(p, ())):
            continue                                                        # (3)
        if _container_rescue(cands, value, changes_at, after_leaves, dropped_text):
            continue                                                        # (4)
        rep.violations.append(
            f"CONTENT-GUARD VIOLATION at {path}: the value {value!r} is present at that "
            f"path BEFORE normalization and is neither present there AFTER, nor recorded "
            f"in a drop at that path, nor a legal enum/type repair declared for that "
            f"path. Refusing to write.")


def _container_rescue(cands, value, changes_at, after_leaves, dropped_text) -> bool:
    """Clause 4: a DECLARED container coercion at an ancestor path restructured this
    leaf. The search is confined to that ancestor's subtree of the AFTER document — never
    to the whole document, which is what made v1.1.0's scan defeatable."""
    for cand in cands:
        for anc in _ancestors(cand):
            recs = changes_at.get(anc)
            if not recs:
                continue
            joined = any(_is_join(c) for c in recs)
            sub = [v for p, v in after_leaves
                   if p == anc or p.startswith(anc + ".") or p.startswith(anc + "[")]
            for leaf in sub:
                if _same(leaf, value):
                    return True
                if isinstance(value, str) and isinstance(leaf, str) \
                        and _legal_enum_rewrite(value, leaf, dropped_text):
                    return True
                if _legal_type_coercion(value, leaf):
                    return True
                if joined and isinstance(leaf, str) and str(value) in leaf:
                    return True
    return False


# --------------------------------------------------------------------------
# debrief.json
# --------------------------------------------------------------------------

def normalize_prior_feedback(doc: dict, rep: Report) -> None:
    """BB-L26, verbatim: 'on any retry (iteration>1) prior_feedback is schema-required
    to carry exactly actionable_changes, do_not_touch AND a non-empty changes_made —
    natural names like "addressed"/"not_addressed" fail.'

    'addressed' is renamed to `changes_made` (only when the canonical key is absent).
    Every other natural name is REPORTED, never guessed at: prior_feedback is
    additionalProperties:true, so an unmapped key is not schema-invalid on its own, and
    the schema's retry clause needs a value this script cannot derive."""
    pf = doc.get("prior_feedback")
    if not isinstance(pf, dict):
        it = doc.get("iteration")
        if isinstance(it, int) and not isinstance(it, bool) and it >= 2:
            rep.advise("$.prior_feedback", "prior-feedback-shape",
                       "iteration>=2 but there is no prior_feedback block; "
                       "debrief.schema.json's retry clause requires one carrying "
                       "actionable_changes + do_not_touch + a NON-EMPTY changes_made "
                       "(BB-L26). NOT filled — the echo is the executor's attestation")
        return
    rename_synonyms(pf, PRIOR_FEEDBACK_SYNONYMS, "$.prior_feedback", "key-synonym", rep)
    for k in ("actionable_changes", "do_not_touch", "changes_made"):
        coerce_str_array(pf, k, "$.prior_feedback", "container-type", rep)
    for k in [k for k in pf if k not in PRIOR_FEEDBACK_KEYS]:
        rep.advise(f"$.prior_feedback.{k}", "prior-feedback-shape",
                   f"{k!r} is a natural key name, not one of "
                   f"actionable_changes/do_not_touch/changes_made (BB-L26) — LEFT IN "
                   f"PLACE; mapping it would guess which canonical list it belongs to")
    for k in ("changes_made", "do_not_touch"):
        if k not in pf:
            rep.advise(f"$.prior_feedback.{k}", "prior-feedback-shape",
                       f"absent; debrief.schema.json requires it on any retry "
                       f"(iteration>=2){', and non-empty (AO-6)' if k == 'changes_made' else ''} "
                       f"— NOT filled (BB-L26)")
        elif k == "changes_made" and pf.get(k) == []:
            rep.advise("$.prior_feedback.changes_made", "prior-feedback-shape",
                       "present but EMPTY; the schema requires >=1 concrete change on a "
                       "retry (AO-6) — NOT filled (BB-L26)")


def normalize_debrief(doc: dict, rep: Report) -> dict:
    # iteration: mechanically derivable ONLY for a first attempt (no prior_feedback).
    if "iteration" not in doc and "prior_feedback" not in doc:
        doc["iteration"] = 1
        rep.change("$.iteration", "fill-derivable", None, 1)

    # top-level confidence: strict enum; prose suffix is dropped (reported verbatim).
    c = doc.get("confidence")
    if isinstance(c, str) and c not in CONFIDENCE:
        fixed = enum_case(c, CONFIDENCE)
        if fixed:
            rep.change("$.confidence", "confidence-enum", c, fixed)
            doc["confidence"] = fixed
        else:
            m = re.match(r"^\s*(high|medium|low)\b", c, re.IGNORECASE)
            if m:
                lvl = m.group(1).lower()
                removed = c[m.end():]
                rep.change("$.confidence", "confidence-enum-prose-stripped", c, lvl)
                # contract clause 5: the drop records the span ACTUALLY removed, byte for
                # byte (v1.1.0 recorded a .strip()ed copy, so the tail's own leading
                # whitespace was silently absent from the report), and no drop is emitted
                # when nothing but padding went — a whitespace-only value never reaches
                # here now that enum_case() repairs it.
                if removed.strip():
                    rep.drop("$.confidence", "confidence-enum-prose-stripped",
                             "<prose after enum word>", removed)
                doc["confidence"] = lvl
            else:
                rep.advise("$.confidence", "confidence-enum",
                           f"{c!r} carries no leading high|medium|low — LEFT UNCHANGED")

    for k in ("assumptions", "residual_risks", "handoff_notes"):
        coerce_str_array(doc, k, "$", "container-type", rep)

    fp = doc.get("footprint")
    if isinstance(fp, dict):
        strip_closed(fp, CLOSED_FOOTPRINT, "$.footprint", "closed-object-strip", rep)
        coerce_int(fp, "tokens_consumed", "$.footprint", "footprint-types", rep)
        coerce_bool(fp, "within_budget", "$.footprint", "footprint-types", rep)
        # within_budget is a REPORT, never recomputed here.

    et = doc.get("evidence_table")
    if isinstance(et, dict):  # {"row1": {...}} -> [...]
        rows = list(et.values())
        if all(isinstance(r, dict) for r in rows):
            # `before` is the ORIGINAL dict, not the literal 'object': the mapping keys
            # (D1, row1, …) are discarded by the coercion, so contract clause 5 requires
            # them to appear verbatim in the report and in --json.
            rep.change("$.evidence_table", "container-type", et, rows)
            rep.drop("$.evidence_table", "container-type", "<mapping keys>",
                     list(et.keys()))
            doc["evidence_table"] = et = rows
    if isinstance(et, list):
        for i, row in enumerate(et):
            if not isinstance(row, dict):
                continue
            jp = f"$.evidence_table[{i}]"
            t = row.get("type")
            if isinstance(t, str) and t not in EVIDENCE_TYPES:
                fixed = enum_case(t, EVIDENCE_TYPES) or EVIDENCE_TYPE_SYNONYMS.get(
                    _syn_key(t))
                if fixed:
                    rep.change(f"{jp}.type", "evidence-type-enum", t, fixed)
                    row["type"] = fixed
                else:
                    rep.advise(f"{jp}.type", "evidence-type-enum",
                               f"{t!r} is not a known synonym of any evidence type — LEFT UNCHANGED")
            coerce_bool(row, "reproducible", jp, "reproducible-type", rep)
            coerce_enum(row, "source_tier", SOURCE_TIERS, jp, "source-tier-enum", rep)
            coerce_enum(row, "retrieval_rung", RETRIEVAL_RUNGS, jp, "retrieval-rung-enum", rep)
            check_required(row, "debrief", "$.evidence_table[]", jp, rep)
            for k in ("covers_owed", "source_refs", "extracted_premises"):
                coerce_str_array(row, k, jp, "container-type", rep)
            if row.get("type") in ("api-tool-contract", "empirical-world-fact",
                                   "provenance-quote") and "source_tier" not in row:
                rep.advise(f"{jp}.source_tier", "i31-source-tier-absent",
                           f"an externally-sourced row (type={row.get('type')!r}) carries no "
                           f"source_tier; validate_run.py I31 wants one. NOT filled — the tier "
                           f"is a provenance CLAIM, not a shape (music L34)")
            strip_closed(row, CLOSED_EVIDENCE_ROW, jp, "closed-object-strip", rep)

    asc = doc.get("acceptance_self_check")
    if isinstance(asc, dict):
        rows, ok = [], True
        for k, v in asc.items():
            b = to_bool(v)
            if b is None:
                ok = False
                break
            rows.append({"criterion": k, "met": b})
        if ok:
            rep.change("$.acceptance_self_check", "container-type", asc, rows)
            # each per-key value coercion is recorded in its own right: the container
            # row alone would leave a string->bool repair unattributed (and the content
            # guard, correctly, would not accept it).
            for k, v in asc.items():
                if isinstance(v, str):
                    rep.change(f"$.acceptance_self_check.{k}", "asc-met-type", v,
                               to_bool(v))
            doc["acceptance_self_check"] = asc = rows
        else:
            rep.advise("$.acceptance_self_check", "container-type",
                       "object whose values are not booleans — LEFT UNCHANGED "
                       "(inventing a met value would be a guess)")
    if isinstance(asc, list):
        for i, row in enumerate(asc):
            jp = f"$.acceptance_self_check[{i}]"
            if isinstance(row, str):
                rep.advise(jp, "asc-row-shape",
                           f"row is a bare string ({row[:60]!r}...) — LEFT UNCHANGED; a `met` "
                           f"value cannot be derived without asserting a result (dag L2)")
                continue
            if not isinstance(row, dict):
                continue
            coerce_bool(row, "met", jp, "asc-met-type", rep)
            strip_closed(row, CLOSED_ASC_ROW, jp, "closed-object-strip", rep)
            check_required(row, "debrief", "$.acceptance_self_check[]", jp, rep)

    normalize_socratic(doc, rep)
    check_required(doc.get("socratic"), "debrief", "$.socratic", "$.socratic", rep)
    check_required(doc.get("footprint"), "debrief", "$.footprint", "$.footprint", rep)

    normalize_prior_feedback(doc, rep)

    check_required(doc, "debrief", "$", "$", rep)
    for k in [k for k in doc if k not in TOP_LEVEL_DEBRIEF]:
        rep.advise(f"$.{k}", "unknown-top-level-key",
                   f"key is outside debrief.schema.json (additionalProperties:false) — LEFT "
                   f"IN PLACE. It may hold narrative that belongs in `result`/`handoff_notes`; "
                   f"relocating it is an orchestrator judgement, not a mechanical coercion")
    return doc


# --------------------------------------------------------------------------
# verify.json
# --------------------------------------------------------------------------

def normalize_verify(doc: dict, rep: Report, sibling_debrief: Path | None = None,
                     basename: str = "verify.json") -> dict:
    # verdict: CASING ONLY. "pass" -> "PASS" is a spelling repair of an exact enum
    # member; anything else is left alone — a verdict is never re-decided here.
    coerce_enum(doc, "verdict", VERDICTS, "$", "verdict-case", rep)

    # executor_reasoning_seen is an ATTESTATION: only a string->bool coercion.
    coerce_bool(doc, "executor_reasoning_seen", "$", "attestation-type", rep)
    if doc.get("executor_reasoning_seen") is True:
        rep.advise("$.executor_reasoning_seen", "attestation-type",
                   "attested TRUE (schema requires false) — LEFT UNCHANGED; flipping an "
                   "independence attestation would falsify it")

    coerce_str_array(doc, "inputs_reviewed", "$", "container-type", rep)

    an = doc.get("audit_notes")
    if isinstance(an, list) and all(isinstance(x, str) for x in an):
        joined = "\n\n".join(an)
        rep.change("$.audit_notes", "container-type", an, joined)
        doc["audit_notes"] = joined
    elif an is not None and not isinstance(an, str):
        rep.advise("$.audit_notes", "container-type",
                   f"value of type {type(an).__name__} is not string-coercible without "
                   f"inventing structure — LEFT UNCHANGED")

    fb = doc.get("feedback")
    if isinstance(fb, dict):
        for k in ("actionable_changes", "do_not_touch"):
            coerce_str_array(fb, k, "$.feedback", "container-type", rep)
        if "actionable_changes" not in fb and doc.get("verdict") != "FAIL":
            fb["actionable_changes"] = []
            rep.change("$.feedback.actionable_changes", "fill-derivable", None, [])
        elif "actionable_changes" not in fb:
            rep.advise("$.feedback.actionable_changes", "missing-required",
                       "absent on a FAIL, where the schema requires a NON-EMPTY list — NOT "
                       "filled; the content is the verifier's, not the normalizer's")

    defects = doc.get("defects")
    if isinstance(defects, dict):
        rows = list(defects.values())
        if all(isinstance(r, dict) for r in rows):
            # `before` is the ORIGINAL dict: the mapping keys (D1, D2, …) are discarded
            # by the coercion and clause 5 requires them reported verbatim.
            rep.change("$.defects", "container-type", defects, rows)
            rep.drop("$.defects", "container-type", "<mapping keys>",
                     list(defects.keys()))
            doc["defects"] = defects = rows
    if isinstance(defects, list):
        for i, d in enumerate(defects):
            if not isinstance(d, dict):
                continue
            jp = f"$.defects[{i}]"
            # severity: CASING ONLY. A synonym ('low'/'nit'/'critical') changes what a
            # PASS means (I6), so it is surfaced, never remapped.
            coerce_enum(d, "severity", SEVERITIES, jp, "severity-case", rep)
            # `criterion` / `severity` text itself is never touched; absence is reported
            # generically from REQUIRED_KEYS (v1.0.0 checked `criterion` and missed its
            # sibling `severity` in the same object).
            check_required(d, "verify", "$.defects[]", jp, rep)

    for i, p in enumerate(doc.get("panel") or []):
        if isinstance(p, dict):
            jp = f"$.panel[{i}]"
            coerce_enum(p, "verdict", VERDICTS, jp, "verdict-case", rep)
            coerce_enum(p, "lens", PANEL_LENSES, jp, "lens-case", rep)
            check_required(p, "verify", "$.panel[]", jp, rep)
    # MU-L25, verbatim: "a panelist verify_p<N>.json must NOT include panel[] (only the
    # AGGREGATE verify.json carries panel[])". Reported, never deleted: panel[] holds
    # panelist verdicts and summaries, i.e. findings, and a lone panelist that recorded
    # a panel may have recorded the WHOLE panel there.
    if re.match(r"^verify_p\w*\.json$", basename) and "panel" in doc:
        rep.advise("$.panel", "panel-in-panelist-file",
                   f"{basename} is a single PANELIST's file, which must not carry panel[] "
                   f"(only the aggregate verify.json does — MU-L25; the schema's minItems:3 "
                   f"makes a 1-element panel invalid) — LEFT IN PLACE; deleting it would "
                   f"destroy panelist verdicts")

    pc = doc.get("premise_check")
    if isinstance(pc, dict):
        rename_synonyms(pc, PREMISE_CHECK_SYNONYMS, "$.premise_check", "key-synonym", rep)
        coerce_bool(pc, "is_load_bearing", "$.premise_check", "premise-check-types", rep)
        coerce_bool(pc, "counter_reran_independently", "$.premise_check",
                    "premise-check-types", rep)
        strip_closed(pc, CLOSED_PREMISE_CHECK, "$.premise_check", "closed-object-strip", rep)
        check_required(pc, "verify", "$.premise_check", "$.premise_check", rep)

    gc = doc.get("guardrail_compliance")
    if isinstance(gc, list):
        for i, row in enumerate(gc):
            if not isinstance(row, dict):
                continue
            jp = f"$.guardrail_compliance[{i}]"
            coerce_enum(row, "status", GUARDRAIL_STATUS, jp, "guardrail-status-case", rep)
            strip_closed(row, CLOSED_GUARDRAIL_ROW, jp, "closed-object-strip", rep)
            check_required(row, "verify", "$.guardrail_compliance[]", jp, rep)
            # `non_goal` must be VERBATIM from clarifications.json — never rewritten here.

    rc = doc.get("retrieval_coverage")
    if isinstance(rc, dict):
        coerce_enum(rc, "tier_at_verification", TIERS, "$.retrieval_coverage",
                    "tier-case", rep)
        for i, row in enumerate(rc.get("owed_check") or []):
            if not isinstance(row, dict):
                continue
            jp = f"$.retrieval_coverage.owed_check[{i}]"
            coerce_enum(row, "status", OWED_STATUS, jp, "owed-status-case", rep)
            rr = row.get("row_refs")
            if isinstance(rr, (int, str)) and not isinstance(rr, bool):
                iv = to_int(rr)
                if iv is not None:
                    rep.change(f"{jp}.row_refs", "container-type", rr, [iv])
                    row["row_refs"] = [iv]
            if isinstance(row.get("row_refs"), list):
                fixed = [to_int(x) if not isinstance(x, bool) else None for x in row["row_refs"]]
                if all(x is not None for x in fixed) and fixed != row["row_refs"]:
                    rep.change(f"{jp}.row_refs", "row-ref-type", row["row_refs"], fixed)
                    row["row_refs"] = fixed
            strip_closed(row, CLOSED_OWED_ROW, jp, "closed-object-strip", rep)
            check_required(row, "verify", "$.retrieval_coverage.owed_check[]", jp, rep)
        for i, row in enumerate(rc.get("retrieval_probes") or []):
            if not isinstance(row, dict):
                continue
            jp = f"$.retrieval_coverage.retrieval_probes[{i}]"
            coerce_enum(row, "kind", PROBE_KINDS, jp, "probe-kind-case", rep)
            strip_closed(row, CLOSED_PROBE_ROW, jp, "closed-object-strip", rep)
            check_required(row, "verify", "$.retrieval_coverage.retrieval_probes[]",
                           jp, rep)
        for i, row in enumerate(rc.get("sources_check") or []):
            if not isinstance(row, dict):
                continue
            jp = f"$.retrieval_coverage.sources_check[{i}]"
            coerce_enum(row, "origin", SOURCE_ORIGINS, jp, "origin-case", rep)
            coerce_enum(row, "outcome", SOURCE_OUTCOMES, jp, "outcome-case", rep)
            strip_closed(row, CLOSED_SOURCES_ROW, jp, "closed-object-strip", rep)
            check_required(row, "verify", "$.retrieval_coverage.sources_check[]", jp, rep)
        strip_closed(rc, CLOSED_RETRIEVAL_COVERAGE, "$.retrieval_coverage",
                     "closed-object-strip", rep)
        check_required(rc, "verify", "$.retrieval_coverage", "$.retrieval_coverage", rep)
        # BB-L26, verbatim: "If the DT-K2 required probe set is genuinely empty,
        # retrieval_probes_none_reason is REQUIRED — a blank probe list is
        # indistinguishable from a skipped one." The reason is a verifier CLAIM about
        # why no probe was owed, so it is reported, never invented.
        if isinstance(rc.get("retrieval_probes"), list) and not rc["retrieval_probes"] \
                and not rc.get("retrieval_probes_none_reason"):
            rep.advise("$.retrieval_coverage.retrieval_probes_none_reason",
                       "retrieval-probes-none-reason",
                       "retrieval_probes is EMPTY and no retrieval_probes_none_reason is "
                       "given, so a genuinely-empty probe set is indistinguishable from a "
                       "skipped one (BB-L26) — NOT filled; the reason is the verifier's")
        _advise_row_ref_base(rc, sibling_debrief, rep)

    for i, row in enumerate(doc.get("consequential_verbatim_check") or []):
        if isinstance(row, dict):
            jp = f"$.consequential_verbatim_check[{i}]"
            strip_closed(row, CLOSED_CVC_ROW, jp, "closed-object-strip", rep)
            check_required(row, "verify", "$.consequential_verbatim_check[]", jp, rep)

    normalize_socratic(doc, rep)
    check_required(doc.get("socratic"), "verify", "$.socratic", "$.socratic", rep)
    check_required(doc, "verify", "$", "$", rep)

    for k in [k for k in doc if k not in TOP_LEVEL_VERIFY]:
        rep.advise(f"$.{k}", "unknown-top-level-key",
                   f"key is outside verify.schema.json (additionalProperties:false) — LEFT IN "
                   f"PLACE. Fold reproduction narrative into `audit_notes` (a STRING) by hand "
                   f"(BubbleBrain L8); deleting it here would destroy the verifier's finding")
    return doc


def _advise_row_ref_base(rc: dict, sibling_debrief: Path | None, rep: Report) -> None:
    """BubbleBrain L26: row_refs are 0-BASED indices into the debrief evidence_table;
    two independent verifiers in one run used 1-based ones. Detectable only against the
    sibling debrief, and NEVER auto-shifted (it would rewrite a coverage claim)."""
    if not sibling_debrief or not sibling_debrief.is_file():
        return
    try:
        n = len(json.loads(sibling_debrief.read_text(encoding="utf-8")).get("evidence_table") or [])
    except Exception:
        return
    if not n:
        return
    refs = []
    for row in rc.get("owed_check") or []:
        if isinstance(row, dict) and isinstance(row.get("row_refs"), list):
            refs += [x for x in row["row_refs"] if isinstance(x, int)]
    for row in rc.get("retrieval_probes") or []:
        if isinstance(row, dict) and isinstance(row.get("row_ref"), int):
            refs.append(row["row_ref"])
    if refs and min(refs) >= 1 and max(refs) >= n:
        rep.advise("$.retrieval_coverage", "row-ref-base",
                   f"row refs {sorted(set(refs))} against an evidence_table of {n} rows: "
                   f"max ref >= row count and no 0 present — looks 1-BASED (BubbleBrain L26). "
                   f"NOT shifted: re-indexing would rewrite a coverage claim")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def kind_of(path: Path) -> str | None:
    n = path.name
    if n.startswith("debrief") and n.endswith(".json"):
        return "debrief"
    if n.startswith("verify") and n.endswith(".json"):
        return "verify"
    return None


def collect(paths: list[str], errors: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.rglob("*.json")):
                if kind_of(f) and "units" in f.parts:
                    out.append(f)
        elif path.is_file():
            out.append(path)
        else:
            errors.append(f"unreadable input: {p} does not exist")
    return out


def normalize_file(path: Path, write: bool, errors: list[str]) -> tuple[dict, bool] | None:
    """Exit-code discipline (v1.1.0): only a genuine INPUT ERROR lands in `errors`
    (exit 2). A readable, well-formed JSON file that simply is not a dag artifact is an
    ADVISORY SKIP (exit 0) — v1.0.0 mislabelled it 'unreadable input'."""
    kind = kind_of(path)
    if kind is None:
        rep = Report(str(path))
        rep.advise("$", "not-an-artifact",
                   "basename is not debrief*.json / verify*.json — SKIPPED, nothing read "
                   "or written (this is not an error)")
        return rep.as_dict(False), False
    try:
        original_text = path.read_text(encoding="utf-8")
        doc = json.loads(original_text)
    except OSError as e:
        errors.append(f"unreadable input: {path}: {e}")
        return None
    except json.JSONDecodeError as e:
        errors.append(f"unreadable input: {path}: not valid JSON ({e})")
        return None
    if not isinstance(doc, dict):
        errors.append(f"malformed artifact: {path}: top level is "
                      f"{type(doc).__name__}, not an object")
        return None

    rep = Report(str(path))
    before = copy.deepcopy(doc)
    if kind == "debrief":
        normalize_debrief(doc, rep)
    else:
        normalize_verify(doc, rep, sibling_debrief=path.parent / "debrief.json",
                         basename=path.name)

    # Contract clause 6: nothing is written if a string value went missing.
    content_guard(before, doc, rep)

    wrote = False
    if rep.violations:
        return rep.as_dict(False), False
    if doc != before:
        new_text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if write and new_text != original_text:
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError as e:
                errors.append(f"unwritable target: {path}: cannot write ({e})")
                return None
            wrote = True
    return rep.as_dict(wrote), wrote


def short(v, n: int = 90) -> str:
    """Text-report elision ONLY. --json carries every before/after value in full."""
    s = repr(v)
    return s if len(s) <= n else s[:n] + f"...<+{len(s) - n} chars, full value in --json>"


def render(results: list[dict], write: bool) -> str:
    lines = [f"normalize_artifacts.py {VERSION} — {'WRITE' if write else 'DRY RUN'} "
             f"— {len(results)} artifact(s)"]
    tc = td = ta = tv = 0
    for r in results:
        tc += len(r["changes"]); td += len(r["drops"]); ta += len(r["advisories"])
        tv += len(r.get("guard_violations") or [])
        if not (r["changes"] or r["drops"] or r["advisories"]
                or r.get("guard_violations")):
            # NOT "already schema-shaped" (the v1.0.0 wording): this script never
            # validates an artifact against a schema — it imports no validator and
            # calls none — so it cannot assert conformance, and must not print an
            # assertion it has no way to substantiate over a file that may still fail
            # the real schema. All it knows is that no rule fired.
            lines.append(f"  OK        {r['file']} — no normalization rule fired")
            continue
        lines.append(f"  {'WROTE' if r['written'] else 'WOULD-FIX' if r['changes'] or r['drops'] else 'CLEAN '}    {r['file']}")
        for v in r.get("guard_violations") or []:
            lines.append(f"      GUARD    {v}")
        for c in r["changes"]:
            lines.append(f"      CHANGE   {c['path']} [{c['rule']}] {short(c['before'])} -> {short(c['after'])}")
        for d in r["drops"]:
            lines.append(f"      DROP     {d['path']} [{d['rule']}] removed key {d['key']!r} "
                         f"with value {short(d['value'])}")
        for a in r["advisories"]:
            lines.append(f"      ADVISORY {a['path']} [{a['rule']}] {a['detail']}")
    lines.append(f"  totals: {tc} change(s), {td} drop(s), {ta} advisory(ies), "
                 f"{tv} content-guard violation(s)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="normalize_artifacts.py",
        description="Offline, idempotent, SHAPE-ONLY normalizer for dag debrief.json / "
                    "verify*.json artifacts. Never alters a verdict, a criterion, "
                    "evidence text or any claim.")
    ap.add_argument("paths", nargs="*", help="run dir(s) and/or artifact file(s)")
    ap.add_argument("--write", action="store_true",
                    help="apply the normalization (default: dry run, report only)")
    ap.add_argument("--json", action="store_true", help="emit the summary as JSON")
    ap.add_argument("--self-test", action="store_true",
                    help="run the embedded contract tests and exit")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.paths:
        ap.error("no paths given (or use --self-test)")

    errors: list[str] = []
    files = collect(args.paths, errors)
    results = []
    for f in files:
        r = normalize_file(f, args.write, errors)
        if r:
            results.append(r[0])

    if args.json:
        print(json.dumps({"version": VERSION, "mode": "write" if args.write else "dry-run",
                          "artifacts": results, "errors": errors},
                         indent=2, ensure_ascii=False))
    else:
        print(render(results, args.write))
    violations = 0
    for r in results:
        for d in r["drops"]:
            print(f"DROPPED {r['file']} {d['path']} {d['key']!r} = {d['value']!r}",
                  file=sys.stderr)
        for v in r.get("guard_violations") or []:
            violations += 1
            print(f"GUARD {r['file']} {v}", file=sys.stderr)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    if violations:
        return 3
    return 2 if errors else 0


# --------------------------------------------------------------------------
# Embedded contract tests (offline, no fixtures on disk)
# --------------------------------------------------------------------------

def self_test() -> int:
    failures = []

    def check(name, cond, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{'' if cond else ' :: ' + detail}")
        if not cond:
            failures.append(name)

    # --- T1: content pass-through on a heavily drifted verify.json -----------
    CRIT = "3. It is exercised on at least one REAL drifted artifact, with the before and after quoted verbatim"
    EVID = "$ git rev-parse HEAD -> 2dee92a ... (verbatim, must survive untouched)"
    drifted_verify = {
        "unit_id": "u1", "verifier_persona": "Adversarial Verifier", "verdict": "pass",
        "iteration": "2", "executor_reasoning_seen": "false",
        "audit_notes": ["line one", "line two"],
        "inputs_reviewed": "brief.md",
        "feedback": {"actionable_changes": "tighten the proof"},
        "defects": [{"severity": "Minor", "criterion": CRIT, "minimal_repro": EVID},
                    {"severity": "low", "criterion": CRIT}],
        "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                     "confidence": "High — one residual"},
        "premise_check": {"executor_premise": "the load-bearing claim",
                          "is_load_bearing": "true",
                          "counter_reran_independently": "yes",
                          "outcome": "held", "note": "extra key"},
        "guardrail_compliance": [{"non_goal": "Do NOT add a fourth human gate",
                                  "status": "Respected", "evidence": "grep"}],
        "reproduction_result": "narrative that must NOT be deleted",
    }
    rep = Report("mem://verify")
    out = normalize_verify(copy.deepcopy(drifted_verify), rep)
    check("T1a verdict casing repaired, value unchanged", out["verdict"] == "PASS",
          repr(out["verdict"]))
    check("T1b defect criterion text byte-identical",
          [d["criterion"] for d in out["defects"]] == [CRIT, CRIT])
    check("T1c evidence/minimal_repro text byte-identical",
          out["defects"][0]["minimal_repro"] == EVID)
    check("T1d severity synonym NOT remapped (advisory instead)",
          out["defects"][1]["severity"] == "low"
          and any(a["rule"] == "severity-case" for a in rep.advisories))
    check("T1e premise_check key synonym renamed, value preserved",
          out["premise_check"].get("executor_premise_quoted") == "the load-bearing claim")
    check("T1f closed-object extra key stripped AND reported verbatim",
          "note" not in out["premise_check"]
          and any(d["key"] == "note" and d["value"] == "extra key" for d in rep.drops))
    check("T1g audit_notes array -> string, content joined not lost",
          out["audit_notes"] == "line one\n\nline two")
    check("T1h unknown TOP-LEVEL key left in place (never destroyed)",
          out.get("reproduction_result") == "narrative that must NOT be deleted")
    check("T1i attestation string -> bool", out["executor_reasoning_seen"] is False)
    check("T1j feedback string -> array", out["feedback"]["actionable_changes"] == ["tighten the proof"])
    check("T1k guardrail status casing repaired",
          out["guardrail_compliance"][0]["status"] == "respected")

    # --- T2: content pass-through on a drifted debrief.json ------------------
    CLAIM = "The normalizer changed 0 verdicts across 134 real artifacts"
    EV = "$ python3 -c '...' -> 0 diffs; verbatim evidence string with unicode: — ✓"
    drifted_debrief = {
        "unit_id": "U03", "persona": "Implementer / Executor",
        "result": "narrative", "confidence": "high — with one caveat",
        "evidence_table": [{"claim": CLAIM, "type": "grep", "evidence": EV,
                            "reproducible": "true", "covers_owed": "OWED-1",
                            "note": "stray"}],
        "socratic": {"premise": "p", "counter": "c", "pivot": "v", "confidence": "medium"},
        "acceptance_self_check": {"criterion one": "yes", "criterion two": False},
        "handoff_notes": "single note",
        "footprint": {"tokens_consumed": "28,500", "within_budget": "false",
                      "note": "overrun"},
    }
    rep2 = Report("mem://debrief")
    out2 = normalize_debrief(copy.deepcopy(drifted_debrief), rep2)
    check("T2a claim text byte-identical", out2["evidence_table"][0]["claim"] == CLAIM)
    check("T2b evidence text byte-identical (incl. unicode)",
          out2["evidence_table"][0]["evidence"] == EV)
    check("T2c evidence type synonym 'grep' -> code-behavior",
          out2["evidence_table"][0]["type"] == "code-behavior")
    check("T2d reproducible string -> bool", out2["evidence_table"][0]["reproducible"] is True)
    check("T2e covers_owed string -> array", out2["evidence_table"][0]["covers_owed"] == ["OWED-1"])
    check("T2f confidence prose stripped to enum + prose reported",
          out2["confidence"] == "high"
          and any("with one caveat" in str(d["value"]) for d in rep2.drops))
    check("T2g acceptance_self_check dict -> array of {criterion, met}",
          out2["acceptance_self_check"] == [{"criterion": "criterion one", "met": True},
                                            {"criterion": "criterion two", "met": False}])
    check("T2h handoff_notes string -> array", out2["handoff_notes"] == ["single note"])
    check("T2i footprint types coerced, stray key dropped + reported",
          out2["footprint"] == {"tokens_consumed": 28500, "within_budget": False}
          and any(d["key"] == "note" for d in rep2.drops))
    check("T2j within_budget NOT recomputed (false preserved)",
          out2["footprint"]["within_budget"] is False)
    check("T2k missing iteration filled with 1 (first attempt, derivable)",
          out2["iteration"] == 1)

    # --- T3: idempotence (in-memory fixed point) ----------------------------
    once_v = json.dumps(out, sort_keys=True)
    twice_v = json.dumps(normalize_verify(copy.deepcopy(out), Report("x")), sort_keys=True)
    once_d = json.dumps(out2, sort_keys=True)
    twice_d = json.dumps(normalize_debrief(copy.deepcopy(out2), Report("x")), sort_keys=True)
    check("T3a verify normalization is a fixed point", once_v == twice_v)
    check("T3b debrief normalization is a fixed point", once_d == twice_d)

    # --- T4: an already-clean artifact is untouched ---------------------------
    clean = {"unit_id": "U01", "persona": "p", "iteration": 1, "result": "r",
             "evidence_table": [{"claim": "c", "type": "code-behavior",
                                 "evidence": "e", "reproducible": True}],
             "socratic": {"premise": "p", "counter": "c", "pivot": "v", "confidence": "high"},
             "confidence": "high", "footprint": {"tokens_consumed": 1, "within_budget": True}}
    r4 = Report("x")
    check("T4 clean debrief unchanged",
          normalize_debrief(copy.deepcopy(clean), r4) == clean and not r4.changes and not r4.drops)

    # --- T5: WHITESPACE-PADDED enum values (the class v1.0.0 shipped broken) ---
    # Every one of the 25 v1.0.0 fixtures fed an ALREADY-LEFT-TRIMMED string, which is
    # exactly why 25/25 PASSed against a rule that ate len(leading whitespace)
    # characters of prose. Neither the corpus sweep nor the round trip could cover it
    # (the corpus holds 0 enum-ish strings with leading/trailing whitespace, and the
    # round-trip drift script's `c[0].upper() + c[1:]` cannot produce one by
    # construction), so the self-test is the ONLY place this class can live.
    PADDED = [
        ("   high — the sweep only covers macOS", "high — the sweep only covers macOS"),
        ("\tHigh — one residual, disclosed", "high — one residual, disclosed"),
        ("\n high", "high"),
        ("  MEDIUM — two of five probes were parametric",
         "medium — two of five probes were parametric"),
        ("low  ", "low"),
        # the four v1.0.0 already handled correctly must not regress
        ("high — for the two corrected figures", "high — for the two corrected figures"),
        ("High — one residual", "high — one residual"),
        ("medium", "medium"),
        ("Low", "low"),
    ]
    ok5 = ok5b = ok5c = True
    for raw, want in PADDED:
        d = {"socratic": {"premise": "p", "counter": "c", "pivot": "v",
                          "confidence": raw}}
        r = Report("x")
        normalize_socratic(d, r)
        got = d["socratic"]["confidence"]
        if got != want:
            ok5 = False
            check(f"T5 padded enum {raw!r} -> {want!r}", False, f"got {got!r}")
        # the PROSE TAIL must be byte-identical to the original's stripped tail
        tail_in = re.sub(r"^(high|medium|low)", "", raw.strip(), flags=re.I)
        tail_out = re.sub(r"^(high|medium|low)", "", got, flags=re.I)
        if tail_in != tail_out:
            ok5b = False
            check(f"T5 prose tail byte-identical for {raw!r}", False,
                  f"{tail_in!r} != {tail_out!r}")
        # and the repaired value must satisfy the schemas' own pattern
        if not re.match(r"^(high|medium|low)\b", got):
            ok5c = False
            check(f"T5 repaired value matches ^(high|medium|low)\\b for {raw!r}", False, got)
        # and be a fixed point
        r2 = Report("x")
        normalize_socratic(d, r2)
        if d["socratic"]["confidence"] != got:
            ok5 = False
    check(f"T5a whitespace-padded socratic.confidence repaired on all {len(PADDED)} probes", ok5)
    check("T5b every repaired value's prose tail is BYTE-IDENTICAL (0 characters lost)", ok5b)
    check("T5c every repaired value matches the schemas' ^(high|medium|low)\\b pattern", ok5c)

    # --- T5d-f: the SAME class at EVERY OTHER enum position (v1.1.0 closed it at one) --
    # T5a-c never call enum_case(); they exercise normalize_socratic() only. That is why
    # 49/49 PASSed while enum_case('  PASS  ') returned None and 42 of 190 padded probes
    # went unrepaired across seven fields. Per BB-L48 a test earns its keep by being able
    # to fail: every assertion below is red against v1.1.0 (see normalizer-proof.md §10).

    # (d) the function itself, directly, over every vocabulary it is ever handed.
    VOCABS = [("EVIDENCE_TYPES", EVIDENCE_TYPES), ("SOURCE_TIERS", SOURCE_TIERS),
              ("RETRIEVAL_RUNGS", RETRIEVAL_RUNGS), ("CONFIDENCE", CONFIDENCE),
              ("VERDICTS", VERDICTS), ("SEVERITIES", SEVERITIES),
              ("GUARDRAIL_STATUS", GUARDRAIL_STATUS), ("PANEL_LENSES", PANEL_LENSES),
              ("OWED_STATUS", OWED_STATUS), ("PROBE_KINDS", PROBE_KINDS),
              ("SOURCE_ORIGINS", SOURCE_ORIGINS), ("SOURCE_OUTCOMES", SOURCE_OUTCOMES),
              ("TIERS", TIERS)]
    PADS = [lambda s: "  " + s + "  ", lambda s: "\t" + s, lambda s: "\n " + s,
            lambda s: " " + s, lambda s: s + "  \n"]
    def _miscase(s):
        return s.upper() if s.islower() else s.lower()
    bad5d, n5d = [], 0
    for vname, vocab in VOCABS:
        for member in vocab:
            for pad in PADS:
                for raw in (pad(member), pad(_miscase(member)), _miscase(member)):
                    n5d += 1
                    if enum_case(raw, vocab) != member:
                        bad5d.append(f"{vname}: enum_case({raw!r}) -> "
                                     f"{enum_case(raw, vocab)!r}, want {member!r}")
            # and an EXACT member must still be a no-op (no spurious change)
            n5d += 1
            if enum_case(member, vocab) is not None:
                bad5d.append(f"{vname}: enum_case({member!r}) is not None")
    check(f"T5d enum_case() repairs padding AND casing on all {n5d} probes across "
          f"{len(VOCABS)} vocabularies (v1.1.0's `s != a` refused padding-only drift)",
          not bad5d, "; ".join(bad5d[:6]))

    # (e) the same class at EVERY enum-bearing field, end to end, with the guard silent.
    def build_verify(f):
        return {"unit_id": "U01", "verifier_persona": "p", "verdict": f("PASS"),
                "iteration": 1, "executor_reasoning_seen": False,
                "feedback": {"actionable_changes": ["x"]},
                "defects": [{"severity": f("minor"), "criterion": "c"}],
                "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                             "confidence": f("high")},
                "premise_check": {"executor_premise_quoted": "q", "is_load_bearing": True,
                                  "counter_reran_independently": True, "outcome": "o"},
                "panel": [{"lens": f("correctness"), "verdict": f("FAIL")},
                          {"lens": f("reproduce"), "verdict": f("DISAGREE")},
                          {"lens": f("guardrail"), "verdict": f("PASS")}],
                "guardrail_compliance": [{"non_goal": "n", "status": f("respected")}],
                "retrieval_coverage": {
                    "tier_at_verification": f("standard"),
                    "owed_check": [{"owed_id": "O1", "status": f("covered"),
                                    "row_refs": [0]}],
                    "retrieval_probes": [{"row_ref": 0, "claim_echo": "e",
                                          "kind": f("reopen"), "outcome": "o"}],
                    "sources_check": [{"source_id": "S1", "origin": f("context_pointer"),
                                       "outcome": f("not-consulted")}]}}

    def build_debrief(f):
        return {"unit_id": "U01", "persona": "p", "iteration": 1, "result": "r",
                "confidence": f("high"),
                "evidence_table": [{"claim": "c", "evidence": "e", "reproducible": True,
                                    "type": f("code-behavior"),
                                    "source_tier": f("T-LOCAL"),
                                    "retrieval_rung": f("cached-copy")}],
                "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                             "confidence": f("high")},
                "footprint": {"tokens_consumed": 1, "within_budget": True}}

    V_SITES = [
        ("$.verdict", lambda d: d["verdict"], "PASS"),
        ("$.defects[0].severity", lambda d: d["defects"][0]["severity"], "minor"),
        ("$.socratic.confidence", lambda d: d["socratic"]["confidence"], "high"),
        ("$.panel[0].lens", lambda d: d["panel"][0]["lens"], "correctness"),
        ("$.panel[0].verdict", lambda d: d["panel"][0]["verdict"], "FAIL"),
        ("$.panel[1].lens", lambda d: d["panel"][1]["lens"], "reproduce"),
        ("$.panel[2].lens", lambda d: d["panel"][2]["lens"], "guardrail"),
        ("$.guardrail_compliance[0].status",
         lambda d: d["guardrail_compliance"][0]["status"], "respected"),
        ("$.retrieval_coverage.tier_at_verification",
         lambda d: d["retrieval_coverage"]["tier_at_verification"], "standard"),
        ("$.retrieval_coverage.owed_check[0].status",
         lambda d: d["retrieval_coverage"]["owed_check"][0]["status"], "covered"),
        ("$.retrieval_coverage.retrieval_probes[0].kind",
         lambda d: d["retrieval_coverage"]["retrieval_probes"][0]["kind"], "reopen"),
        ("$.retrieval_coverage.sources_check[0].origin",
         lambda d: d["retrieval_coverage"]["sources_check"][0]["origin"],
         "context_pointer"),
        ("$.retrieval_coverage.sources_check[0].outcome",
         lambda d: d["retrieval_coverage"]["sources_check"][0]["outcome"],
         "not-consulted"),
    ]
    D_SITES = [
        ("$.confidence", lambda d: d["confidence"], "high"),
        ("$.socratic.confidence", lambda d: d["socratic"]["confidence"], "high"),
        ("$.evidence_table[0].type", lambda d: d["evidence_table"][0]["type"],
         "code-behavior"),
        ("$.evidence_table[0].source_tier",
         lambda d: d["evidence_table"][0]["source_tier"], "T-LOCAL"),
        ("$.evidence_table[0].retrieval_rung",
         lambda d: d["evidence_table"][0]["retrieval_rung"], "cached-copy"),
    ]
    MUTATORS = [("padded", lambda s: "  " + s + "  "), ("tab", lambda s: "\t" + s),
                ("newline", lambda s: "\n " + s), ("mis-cased", _miscase),
                ("padded+mis-cased", lambda s: "  " + _miscase(s) + "  ")]
    bad5e, bad5g, n5e = [], [], 0
    for mname, mut in MUTATORS:
        for build, sites, norm in ((build_verify, V_SITES, normalize_verify),
                                   (build_debrief, D_SITES, normalize_debrief)):
            src = build(mut)
            r = Report("x")
            got = norm(copy.deepcopy(src), r)
            content_guard(src, got, r)
            if r.violations:
                bad5g.append(f"{mname}: {r.violations[0]}")
            for jp, read, member in sites:
                n5e += 1
                if read(got) != member:
                    bad5e.append(f"{mname} {jp}: {read(got)!r} != {member!r}")
            # nothing may be SILENT: every drifted site owes a change record
            for jp, read, member in sites:
                if not any(c["path"] == jp for c in r.changes):
                    bad5e.append(f"{mname} {jp}: 0 change records — SILENT")
    check(f"T5e every enum-bearing field repairs padding/casing to the exact member "
          f"({n5e} field probes, {len(V_SITES) + len(D_SITES)} positions x "
          f"{len(MUTATORS)} mutations) and none is silent", not bad5e,
          "; ".join(bad5e[:6]))
    check("T5f the content guard stays SILENT on every one of those repairs", not bad5g,
          "; ".join(bad5g[:3]))

    # (f) the six positions the 37->28 trim orphaned: a BARE mis-cased value there used
    #     to yield 0 changes AND 0 advisories — silent, not merely unfixed.
    r5g = Report("x")
    normalize_verify(build_verify(_miscase), r5g)
    fired5 = {c["rule"] for c in r5g.changes}
    want5 = {"lens-case", "tier-case", "owed-status-case", "probe-kind-case",
             "origin-case", "outcome-case"}
    check("T5g the six enum positions the trim orphaned (lens / tier_at_verification / "
          "owed status / probe kind / sources origin+outcome) fire again",
          want5 <= fired5, str(sorted(want5 - fired5)))

    # --- T6: the content guard actually fires on a prose-eating rule ----------
    # Reproduce the v1.0.0 bug in isolation and require the guard to catch it, so the
    # guard itself is tested rather than merely present.
    LOST = "   high — the sweep only covers macOS"
    b6 = {"socratic": {"premise": "p", "counter": "c", "pivot": "v", "confidence": LOST}}
    a6 = copy.deepcopy(b6)
    r6 = Report("x")
    m6 = re.match(r"^\s*(high|medium|low)\b", LOST, re.IGNORECASE)          # v1.0.0 code
    bug = m6.group(1).lower() + LOST.strip()[m6.end() - m6.start():]        # v1.0.0 code
    a6["socratic"]["confidence"] = bug
    r6.change("$.socratic.confidence", "socratic-confidence-case", LOST, bug)
    content_guard(b6, a6, r6)
    check("T6a content guard FIRES on the v1.0.0 prose-eating socratic rule",
          len(r6.violations) == 1, f"bug output {bug!r}, violations {r6.violations}")
    r6b = Report("x")
    content_guard(b6, b6, r6b)
    check("T6b content guard is SILENT on an untouched document", not r6b.violations)
    b6c = {"footprint": {"tokens_consumed": 1, "within_budget": True,
                         "newly_legitimate_key": "a value a rotted closed-key set would eat"}}
    a6c = {"footprint": {"tokens_consumed": 1, "within_budget": True}}
    r6c = Report("x")
    content_guard(b6c, a6c, r6c)
    check("T6c content guard FIRES on an UNREPORTED closed-object deletion (the D2 "
          "schema-rot failure mode)", len(r6c.violations) == 1)
    r6d = Report("x")
    r6d.drop("$.footprint", "closed-object-strip", "newly_legitimate_key",
             "a value a rotted closed-key set would eat")
    content_guard(b6c, a6c, r6d)
    check("T6d content guard is SILENT when the same deletion IS reported verbatim",
          not r6d.violations)
    r6e = Report("x")
    normalize_debrief(copy.deepcopy(drifted_debrief), r6e)
    content_guard(drifted_debrief, normalize_debrief(copy.deepcopy(drifted_debrief),
                                                    Report("x")), r6e)
    check("T6e content guard is SILENT over the whole T2 drifted debrief",
          not r6e.violations, str(r6e.violations))
    r6f = Report("x")
    out6f = normalize_verify(copy.deepcopy(drifted_verify), r6f)
    content_guard(drifted_verify, out6f, r6f)
    check("T6f content guard is SILENT over the whole T1 drifted verify",
          not r6f.violations, str(r6f.violations))

    # --- T6g-k: the guard's PATH KEY, its leaf walk, and its rewrite predicate --------
    # v1.1.0 cleared a before-string with `any(s in t for t in after_all)`: an unanchored
    # substring test over EVERY string in the after document, with no path. Each check
    # below is red against that code (normalizer-proof.md §10).

    # (g) a value destroyed outright, whose token happens to occur inside another value.
    b6g = {"verdict": "PASS", "audit_notes": "the panel returned PASS after a re-poll",
           "defects": []}
    a6g = {"audit_notes": "the panel returned PASS after a re-poll", "defects": []}
    r6g = Report("x")
    content_guard(b6g, a6g, r6g)
    check("T6g content guard FIRES when $.verdict is deleted and the token 'PASS' "
          "survives only as a SUBSTRING of $.audit_notes",
          len(r6g.violations) == 1 and "$.verdict" in r6g.violations[0],
          str(r6g.violations))

    # (h) non-string leaves: int, bool, list, null, and an empty container.
    bad6h = []
    # (value, violations owed) — one per lost LEAF, stated literally so the assertion
    # does not depend on the walk it is testing.
    for v, want in ((41000, 1), (True, 1), (False, 1), ([1, 2, 3], 3), (None, 1),
                    (3.5, 1), ({}, 1), ([], 1), ({"a": 1, "b": [2, 3]}, 3)):
        r = Report("x")
        content_guard({"footprint": {"tokens_consumed": 1, "within_budget": True,
                                     "new_key": v}},
                      {"footprint": {"tokens_consumed": 1, "within_budget": True}}, r)
        if len(r.violations) != want:
            bad6h.append(f"{v!r} -> {len(r.violations)} violation(s), want {want}")
    check("T6h content guard FIRES on an unreported closed-object deletion of a "
          "NON-STRING value (footprint's own two legitimate keys are an int and a bool)",
          not bad6h, "; ".join(bad6h))
    # and a bool must not be laundered by an int of the same truth value
    r6h2 = Report("x")
    content_guard({"footprint": {"within_budget": True}},
                  {"footprint": {"within_budget": 1}}, r6h2)
    check("T6h2 type-strict: True replaced by 1 at the same path is a violation",
          len(r6h2.violations) == 1, str(r6h2.violations))

    # (i) one legal record must not launder a different path carrying the same string.
    DUP = "High — one residual"
    r6i = Report("x")
    r6i.change("$.a", "socratic-confidence-case", DUP, "high — one residual")
    content_guard({"a": DUP, "b": DUP},
                  {"a": "high — one residual", "b": "TOTALLY DIFFERENT TEXT"}, r6i)
    check("T6i a change recorded at $.a does NOT excuse the same string vanishing "
          "at $.b", len(r6i.violations) == 1 and "$.b" in r6i.violations[0],
          str(r6i.violations))
    r6i2 = Report("x")
    r6i2.drop("$", "closed-object-strip", "a", DUP)
    content_guard({"a": DUP, "b": DUP}, {"c": "unrelated"}, r6i2)
    check("T6i2 a drop recorded at $.a does NOT excuse the same string vanishing at $.b",
          len(r6i2.violations) == 1 and "$.b" in r6i2.violations[0],
          str(r6i2.violations))

    # (j) the rewrite predicate must check that the synonym maps to AFTER.
    check("T6j _legal_enum_rewrite refuses ('grep','PASS') and ('count','DISAGREE') "
          "while accepting ('grep','code-behavior')",
          _legal_enum_rewrite("grep", "PASS", []) is False
          and _legal_enum_rewrite("grep", "blocker", []) is False
          and _legal_enum_rewrite("count", "DISAGREE", []) is False
          and _legal_enum_rewrite("grep", "code-behavior", []) is True,
          f"{_legal_enum_rewrite('grep', 'PASS', [])}/"
          f"{_legal_enum_rewrite('grep', 'code-behavior', [])}")
    r6j = Report("x")
    r6j.change("$.verdict", "verdict-case", "grep", "PASS")
    content_guard({"verdict": "grep"}, {"verdict": "PASS"}, r6j)
    check("T6j2 document level: 'grep' -> 'PASS' at $.verdict is a VIOLATION even with a "
          "matching change record", len(r6j.violations) == 1, str(r6j.violations))

    # (k) the guard and the repair must use the SAME synonym key normalisation. v1.1.0's
    #     repair applied .replace(' ', '-') and the guard did not, so DAG-L6's
    #     'source cross-check' written with spaces was repaired and then refused at
    #     exit 3, discarding every other repair in the file.
    bad6k = []
    for spaced in ("source cross-check", "Source Cross-Check", "  source cross-check  "):
        src6k = {"unit_id": "U01", "persona": "p", "iteration": 1, "result": "r",
                 "confidence": "high",
                 "evidence_table": [{"claim": "c", "type": spaced, "evidence": "e",
                                     "reproducible": True},
                                    {"claim": "c2", "type": "grep", "evidence": "e2",
                                     "reproducible": True}],
                 "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                              "confidence": "high"},
                 "footprint": {"tokens_consumed": 1, "within_budget": True,
                               "note": "stray"}}
        r = Report("x")
        got6k = normalize_debrief(copy.deepcopy(src6k), r)
        content_guard(src6k, got6k, r)
        if r.violations or got6k["evidence_table"][0]["type"] != "provenance-quote" \
                or got6k["evidence_table"][1]["type"] != "code-behavior" \
                or "note" in got6k["footprint"]:
            bad6k.append(f"{spaced!r}: violations={r.violations} "
                         f"types={[x['type'] for x in got6k['evidence_table']]}")
    check("T6k a spaced DAG-L6 synonym ('source cross-check') is repaired with 0 guard "
          "violations, and the file's unrelated repairs survive", not bad6k,
          "; ".join(bad6k))

    # --- T7: the hardcoded schema mirror is asserted against schemas/*.json ---
    for name, ok, detail in schema_mirror_test():
        check(name, ok, detail)

    # --- T8: every rule label carries a qualified lesson id -------------------
    # v1.1.0 built `fired` from the T1/T2 fixtures only, so it covered 16 of 28 labels
    # and a new rule on any of the other 12 paths passed green with no provenance.
    # v1.1.1 reads the labels out of the MODULE ITSELF and asserts BOTH directions.
    labels = _rule_labels_in_code()
    check(f"T8a every one of the {len(labels)} rule labels in the module has a "
          f"RULE_PROVENANCE lesson id",
          labels <= set(RULE_PROVENANCE), str(sorted(labels - set(RULE_PROVENANCE))))
    check("T8b RULE_PROVENANCE has no orphan entry (a label no code path can emit)",
          set(RULE_PROVENANCE) <= labels, str(sorted(set(RULE_PROVENANCE) - labels)))
    fired = {c["rule"] for r in (rep, rep2, r6e, r6f) for c in r.changes}
    fired |= {d["rule"] for r in (rep, rep2, r6e, r6f) for d in r.drops}
    fired |= {a["rule"] for r in (rep, rep2, r6e, r6f) for a in r.advisories}
    check("T8c every rule label that fired in T1/T2 has a lesson id",
          fired <= set(RULE_PROVENANCE), str(sorted(fired - set(RULE_PROVENANCE))))

    # --- T9: the three drift modes v1.0.0 documented but did not implement ----
    r9 = Report("x")
    panelist = {"unit_id": "U01", "verifier_persona": "p", "verdict": "PASS",
                "iteration": 1, "executor_reasoning_seen": False,
                "feedback": {"actionable_changes": []}, "defects": [],
                "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                             "confidence": "high"},
                "premise_check": {"executor_premise_quoted": "q", "is_load_bearing": True,
                                  "counter_reran_independently": True, "outcome": "held"},
                "panel": [{"lens": "correctness", "verdict": "PASS"}],
                "retrieval_coverage": {"owed_check": [], "retrieval_probes": [],
                                       "sources_check": []}}
    out9 = normalize_verify(copy.deepcopy(panelist), r9, basename="verify_p2.json")
    check("T9a MU-L25 panel[] in a panelist verify_p*.json is reported",
          any(a["rule"] == "panel-in-panelist-file" for a in r9.advisories))
    check("T9b MU-L25 panel[] is NOT deleted (it holds panelist verdicts)",
          out9["panel"] == panelist["panel"])
    check("T9c BB-L26 empty retrieval_probes with no *_none_reason is reported",
          any(a["rule"] == "retrieval-probes-none-reason" for a in r9.advisories))
    r9d = Report("x")
    retry = {"unit_id": "U01", "persona": "p", "iteration": 2, "result": "r",
             "evidence_table": [{"claim": "c", "type": "code-behavior", "evidence": "e",
                                 "reproducible": True}],
             "socratic": {"premise": "p", "counter": "c", "pivot": "v",
                          "confidence": "high"},
             "confidence": "high", "footprint": {"tokens_consumed": 1,
                                                 "within_budget": True},
             "prior_feedback": {"actionable_changes": ["fix the index bug"],
                                "addressed": ["fixed the index bug"],
                                "not_addressed": ["deferred the trim"]}}
    out9d = normalize_debrief(copy.deepcopy(retry), r9d)
    check("T9d BB-L26 prior_feedback natural key 'addressed' -> changes_made, value kept",
          out9d["prior_feedback"].get("changes_made") == ["fixed the index bug"])
    check("T9e BB-L26 'not_addressed' is NOT guessed at — reported, left in place",
          out9d["prior_feedback"].get("not_addressed") == ["deferred the trim"]
          and any(a["rule"] == "prior-feedback-shape" and "not_addressed" in a["path"]
                  for a in r9d.advisories))
    check("T9f BB-L26 missing do_not_touch on a retry is reported, never invented",
          "do_not_touch" not in out9d["prior_feedback"]
          and any("do_not_touch" in a["path"] for a in r9d.advisories))
    # v1.1.1: this used a FRESH Report, so the guard saw none of the run's own change or
    # drop records and could only ever have passed by the document-wide substring scan.
    # Guard with the SAME report the normalization filled, exactly as normalize_file does.
    r9g = Report("x")
    out9g = normalize_debrief(copy.deepcopy(retry), r9g)
    content_guard(retry, out9g, r9g)
    check("T9g the prior_feedback repair loses no string", not r9g.violations,
          str(r9g.violations))

    # --- T10: verify.defects[].severity absence is reported (v1.0.0 missed it) --
    r10 = Report("x")
    normalize_verify({"defects": [{"criterion": "1. some criterion"}]}, r10)
    check("T10a missing defects[].severity is reported (its sibling `criterion` was "
          "checked in v1.0.0 and `severity` was not)",
          any(a["path"] == "$.defects[0].severity" and a["rule"] == "missing-required"
              for a in r10.advisories))
    r10b = Report("x")
    normalize_verify({"defects": [{"severity": "minor"}]}, r10b)
    check("T10b missing defects[].criterion is still reported",
          any(a["path"] == "$.defects[0].criterion" and a["rule"] == "missing-required"
              for a in r10b.advisories))

    # --- T11: dict -> array coercion reports the discarded mapping keys -------
    r11 = Report("x")
    normalize_verify({"defects": {"D1": {"severity": "minor", "criterion": "c1"},
                                  "D2": {"severity": "minor", "criterion": "c2"}}}, r11)
    check("T11 dict->array records the ORIGINAL mapping keys (D1/D2), not the literal "
          "string 'object'",
          any(d["key"] == "<mapping keys>" and d["value"] == ["D1", "D2"]
              for d in r11.drops)
          and any(c["path"] == "$.defects" and isinstance(c["before"], dict)
                  for c in r11.changes))

    # --- T12: schema-typed scalars carrying a string are DETECTED again --------------
    # v1.1.0 deleted iteration-type / verify-rounds-type / converged-type and justified
    # it with a byte-identical sweep over an already-clean corpus — the incidence
    # argument. The unit's own T1 fixture falsifies it: drifted_verify carries
    # "iteration": "2", a key BOTH schemas declare `required` AND `integer`, and v1.1.0
    # returned it unchanged with zero advisories. Detection, not repair: an advisory
    # rewrites nothing and guesses nothing.
    check("T12a the T1 fixture's \"iteration\": \"2\" is now REPORTED (v1.1.0: 0 changes, "
          "0 advisories on a required+integer key)",
          any(a["path"] == "$.iteration" and a["rule"] == "scalar-type-mismatch"
              for a in rep.advisories),
          str([a["path"] for a in rep.advisories]))
    check("T12b and it is still not REPAIRED (the value is unchanged)",
          out["iteration"] == "2", repr(out["iteration"]))
    r12 = Report("x")
    normalize_verify({"iteration": "2", "verify_rounds": "3", "converged": "true",
                      "defects": [], "socratic": {}}, r12)
    got12 = {a["path"] for a in r12.advisories if a["rule"] == "scalar-type-mismatch"}
    check("T12c verify_rounds and converged, the other two rules the trim deleted, are "
          "reported too",
          got12 == {"$.iteration", "$.verify_rounds", "$.converged"}, str(sorted(got12)))
    r12d = Report("x")
    normalize_debrief({"iteration": "4", "prior_feedback": {}}, r12d)
    check("T12d the same class is reported on the debrief side",
          any(a["path"] == "$.iteration" and a["rule"] == "scalar-type-mismatch"
              for a in r12d.advisories))
    # no DOUBLE reporting where a repair rule already owns the key
    r12e = Report("x")
    normalize_debrief({"footprint": {"tokens_consumed": "not a number",
                                     "within_budget": True}}, r12e)
    check("T12e a key a repair rule already owns is reported ONCE, by that rule",
          len([a for a in r12e.advisories
               if a["path"] == "$.footprint.tokens_consumed"]) == 1,
          str([a["rule"] for a in r12e.advisories
               if a["path"] == "$.footprint.tokens_consumed"]))
    r12f = Report("x")
    normalize_debrief({"footprint": {"tokens_consumed": "28,500",
                                     "within_budget": "false"}}, r12f)
    check("T12f a key a repair rule REPAIRED gets no advisory at all",
          not any(a["rule"] == "scalar-type-mismatch" for a in r12f.advisories),
          str([a["path"] for a in r12f.advisories
               if a["rule"] == "scalar-type-mismatch"]))

    print(f"\nself-test: {len(failures)} failure(s)")
    return 0 if not failures else 2


# --------------------------------------------------------------------------
# D2 — the schema mirror, asserted against schemas/*.json
# --------------------------------------------------------------------------

def _rule_labels_in_code() -> set:
    """Every rule label LITERAL the module can emit, read out of its own source. `ast` is
    stdlib and imported here rather than at module scope so the shipped import surface
    stays argparse/copy/json/re/sys/pathlib."""
    import ast
    # callee -> index of the `rule` parameter in its positional signature
    SLOT = {"change": 1, "drop": 1, "advise": 1, "strip_closed": 3,
            "rename_synonyms": 3, "coerce_enum": 4, "coerce_bool": 3, "coerce_int": 3,
            "coerce_str_array": 3}
    tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        i = SLOT.get(name)
        if i is None or len(node.args) <= i:
            continue
        arg = node.args[i]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.add(arg.value)
    return out


def _schema_index(node, kind: str, pointer: str, req: dict, closed: dict,
                  enums: dict, scalars: dict | None = None) -> None:
    """Walk a JSON Schema and index required-key lists, additionalProperties:false
    property sets, enums and declared scalar types by json pointer (`$`, `$.k`, `$[]`)."""
    if not isinstance(node, dict):
        return
    if "required" in node:
        req[pointer] = sorted(node["required"])
    if node.get("additionalProperties") is False and "properties" in node:
        closed[pointer] = set(node["properties"])
    if "enum" in node:
        enums[pointer] = list(node["enum"])
    if scalars is not None and node.get("type") in ("integer", "boolean"):
        parent, _, key = pointer.rpartition(".")
        if parent and not key.endswith("]"):
            scalars.setdefault(parent, {})[key] = node["type"]
    for k, v in (node.get("properties") or {}).items():
        _schema_index(v, kind, f"{pointer}.{k}", req, closed, enums, scalars)
    if "items" in node:
        _schema_index(node["items"], kind, f"{pointer}[]", req, closed, enums, scalars)


def schema_mirror_test() -> list[tuple[str, bool, str]]:
    """D2: the vocabularies, closed-key sets and required-key lists above are HAND
    MIRRORS of schemas/*.json, and strip_closed() DELETES under --write. Assert every
    one of them against the schema files, so a schema edit that is not mirrored here
    fails this test instead of silently stripping a newly-legitimate key from every
    artifact in a run."""
    out: list[tuple[str, bool, str]] = []
    sdir = Path(__file__).resolve().parents[1] / "schemas"
    idx: dict[str, tuple[dict, dict, dict, dict]] = {}
    for kind in ("debrief", "verify"):
        f = sdir / f"{kind}.schema.json"
        try:
            schema = json.loads(f.read_text(encoding="utf-8"))
        except OSError as e:
            out.append((f"T7 {kind}.schema.json readable", False, str(e)))
            return out
        req, closed, enums, scalars = {}, {}, {}, {}
        _schema_index(schema, kind, "$", req, closed, enums, scalars)
        idx[kind] = (req, closed, enums, scalars)

    # (a) every hardcoded vocabulary == the schema's enum at its declared pointer
    vocabs = [
        ("debrief", "$.evidence_table[].type", EVIDENCE_TYPES, "EVIDENCE_TYPES"),
        ("debrief", "$.evidence_table[].source_tier", SOURCE_TIERS, "SOURCE_TIERS"),
        ("debrief", "$.evidence_table[].retrieval_rung", RETRIEVAL_RUNGS, "RETRIEVAL_RUNGS"),
        ("debrief", "$.confidence", CONFIDENCE, "CONFIDENCE"),
        ("verify", "$.verdict", VERDICTS, "VERDICTS"),
        ("verify", "$.defects[].severity", SEVERITIES, "SEVERITIES"),
        ("verify", "$.guardrail_compliance[].status", GUARDRAIL_STATUS, "GUARDRAIL_STATUS"),
        ("verify", "$.panel[].lens", PANEL_LENSES, "PANEL_LENSES"),
        ("verify", "$.panel[].verdict", VERDICTS, "VERDICTS (panel)"),
        ("verify", "$.retrieval_coverage.owed_check[].status", OWED_STATUS, "OWED_STATUS"),
        ("verify", "$.retrieval_coverage.retrieval_probes[].kind", PROBE_KINDS, "PROBE_KINDS"),
        ("verify", "$.retrieval_coverage.sources_check[].origin", SOURCE_ORIGINS, "SOURCE_ORIGINS"),
        ("verify", "$.retrieval_coverage.sources_check[].outcome", SOURCE_OUTCOMES, "SOURCE_OUTCOMES"),
        ("verify", "$.retrieval_coverage.tier_at_verification", TIERS, "TIERS"),
        # I41 (1.11.0). Added when a sibling edit to verify.schema.json left 8 of 22 enum
        # pointers undeclared: T7a only walked THIS table, so the new pointers were silently
        # unmirrored (a `dispositions[].lens: "Guardrail"` row normalized to 0 changes and 0
        # advisories). T7a2 below closes that direction.
        ("verify", "$.panel[].defects[].severity", SEVERITIES, "SEVERITIES (panel member)"),
        ("verify", "$.panel_adjudication.resolution", ADJUDICATION_RESOLUTIONS,
         "ADJUDICATION_RESOLUTIONS"),
        ("verify", "$.panel_adjudication.dissent_refs[].lens", PANEL_LENSES,
         "PANEL_LENSES (dissent_refs)"),
        ("verify", "$.panel_adjudication.dispositions[].lens", PANEL_LENSES,
         "PANEL_LENSES (dispositions)"),
        ("verify", "$.panel_adjudication.dispositions[].disposition", DISPOSITIONS,
         "DISPOSITIONS"),
        ("verify", "$.panel_adjudication.repoll[].lens", PANEL_LENSES,
         "PANEL_LENSES (repoll)"),
        ("verify", "$.panel_adjudication.repoll[].pre_verdict", VERDICTS,
         "VERDICTS (repoll pre)"),
        ("verify", "$.panel_adjudication.repoll[].post_verdict", VERDICTS,
         "VERDICTS (repoll post)"),
        # case_set contract (SPEC section 3.1/3.2). Declaring the pointer is what forces
        # T7a to then compare the members, so these five lines are what make the enums
        # checked in BOTH directions rather than merely present.
        ("debrief", "$.case_set_discharge[].origin", DISCHARGE_ORIGINS,
         "DISCHARGE_ORIGINS"),
        ("debrief", "$.case_set_discharge[].outcome", DISCHARGE_OUTCOMES,
         "DISCHARGE_OUTCOMES"),
        ("debrief", "$.case_set_discharge[].evidence_tier", EVIDENCE_TIERS,
         "EVIDENCE_TIERS"),
        ("debrief", "$.case_set_discharge[].check_form", CHECK_FORMS, "CHECK_FORMS"),
        ("debrief", "$.case_set_discharge[].non_vacuity[].counterfactual_result",
         COUNTERFACTUAL_RESULTS, "COUNTERFACTUAL_RESULTS"),
    ]
    bad = [f"{n}@{k}{p}: {idx[k][2].get(p)} != {v}"
           for k, p, v, n in vocabs if idx[k][2].get(p) != v]
    out.append((f"T7a all {len(vocabs)} hardcoded vocabularies match the schemas' enums",
                not bad, "; ".join(bad)))
    # The REVERSE direction, the one that lets the mirror rot silently: T7a above iterates
    # the HARDCODED table, so a newly added schema enum it does not name is simply not
    # checked. Assert the other way too, exactly as T7c does for closed objects and T7f for
    # SCALAR_TYPES. Declaring the pointer is what forces T7a to then compare its members.
    declared = {(k, p) for k, p, _, _ in vocabs}
    missing = [f"{k}{p}" for k in idx for p in idx[k][2] if (k, p) not in declared]
    out.append(("T7a2 every enum in either schema has a declared vocabulary mirror here",
                not missing, str(missing)))

    # (b) every closed-key set == the schema's property set where
    #     additionalProperties:false, AND no closed object in either schema is missing
    #     a declared mirror (that is the direction that would let strip_closed() rot)
    closed_map = {
        ("debrief", "$"): ("TOP_LEVEL_DEBRIEF", TOP_LEVEL_DEBRIEF),
        ("debrief", "$.evidence_table[]"): ("CLOSED_EVIDENCE_ROW", CLOSED_EVIDENCE_ROW),
        ("debrief", "$.acceptance_self_check[]"): ("CLOSED_ASC_ROW", CLOSED_ASC_ROW),
        ("debrief", "$.footprint"): ("CLOSED_FOOTPRINT", CLOSED_FOOTPRINT),
        ("verify", "$"): ("TOP_LEVEL_VERIFY", TOP_LEVEL_VERIFY),
        ("verify", "$.premise_check"): ("CLOSED_PREMISE_CHECK", CLOSED_PREMISE_CHECK),
        ("verify", "$.retrieval_coverage"): ("CLOSED_RETRIEVAL_COVERAGE",
                                             CLOSED_RETRIEVAL_COVERAGE),
        ("verify", "$.retrieval_coverage.owed_check[]"): ("CLOSED_OWED_ROW", CLOSED_OWED_ROW),
        ("verify", "$.retrieval_coverage.retrieval_probes[]"): ("CLOSED_PROBE_ROW", CLOSED_PROBE_ROW),
        ("verify", "$.retrieval_coverage.sources_check[]"): ("CLOSED_SOURCES_ROW", CLOSED_SOURCES_ROW),
        ("verify", "$.guardrail_compliance[]"): ("CLOSED_GUARDRAIL_ROW", CLOSED_GUARDRAIL_ROW),
        ("verify", "$.consequential_verbatim_check[]"): ("CLOSED_CVC_ROW", CLOSED_CVC_ROW),
        # case_set contract. This is the direction that would let strip_closed() DELETE a
        # legitimate discharge field under --write (L15's silent-rot mode); T7c asserts the
        # other direction, that no closed object in either schema lacks a mirror here.
        ("debrief", "$.case_set_discharge[]"): ("CLOSED_DISCHARGE_ROW",
                                                CLOSED_DISCHARGE_ROW),
        ("debrief", "$.case_set_discharge[].non_vacuity[]"): ("CLOSED_NON_VACUITY_ROW",
                                                              CLOSED_NON_VACUITY_ROW),
        ("verify", "$.case_set_audit"): ("CLOSED_CASE_SET_AUDIT", CLOSED_CASE_SET_AUDIT),
        ("verify", "$.case_set_audit.discharge_check"): ("CLOSED_DISCHARGE_CHECK",
                                                         CLOSED_DISCHARGE_CHECK),
        ("verify", "$.case_set_audit.novelty_rate"): ("CLOSED_NOVELTY_RATE",
                                                      CLOSED_NOVELTY_RATE),
        ("verify", "$.case_set_audit.vocabulary_containment"): (
            "CLOSED_VOCABULARY_CONTAINMENT", CLOSED_VOCABULARY_CONTAINMENT),
    }
    bad = [f"{n}@{k}{p}: mirror {sorted(v)} != schema {sorted(idx[k][1].get(p) or [])}"
           for (k, p), (n, v) in closed_map.items() if idx[k][1].get(p) != v]
    out.append((f"T7b all {len(closed_map)} closed-key sets match the schemas' "
                f"additionalProperties:false property sets", not bad, "; ".join(bad)))
    missing = [f"{k}{p}" for k in idx for p in idx[k][1] if (k, p) not in closed_map]
    out.append(("T7c every additionalProperties:false object in either schema has a "
                "declared mirror here", not missing, str(missing)))

    # (c) every REQUIRED_KEYS list == the schema's own `required` array
    bad = [f"{k}{p}: {v} != {idx[k][0].get(p)}"
           for k, tbl in REQUIRED_KEYS.items() for p, v in tbl.items()
           if idx[k][0].get(p) != v]
    n_req = sum(len(t) for t in REQUIRED_KEYS.values())
    out.append((f"T7d all {n_req} required-key lists match the schemas' `required` arrays",
                not bad, "; ".join(bad)))
    # Same reverse direction for REQUIRED_KEYS: T7d walks the table, so a `required` array
    # added to either schema at an undeclared pointer was unchecked and unmirrored.
    missing = [f"{k}{p}" for k in idx for p in idx[k][0] if p not in REQUIRED_KEYS.get(k, {})]
    out.append(("T7d2 every `required` array in either schema has a declared mirror here",
                not missing, str(missing)))

    # (d) SCALAR_TYPES is the mirror the scalar-type-mismatch advisory reads. Assert it
    #     in BOTH directions: no entry that the schema does not declare, and no
    #     schema-declared integer/boolean property missing from the table — the second
    #     direction is the one that would let the class quietly reopen again.
    bad = [f"{k}{p}.{key}: mirror {want!r} != schema {idx[k][3].get(p, {}).get(key)!r}"
           for k, tbl in SCALAR_TYPES.items() for p, props in tbl.items()
           for key, want in props.items() if idx[k][3].get(p, {}).get(key) != want]
    n_sc = sum(len(props) for t in SCALAR_TYPES.values() for props in t.values())
    out.append((f"T7e all {n_sc} SCALAR_TYPES entries match the schemas' declared "
                f"integer/boolean types", not bad, "; ".join(bad)))
    missing = [f"{k}{p}.{key}" for k in idx for p, props in idx[k][3].items()
               for key in props if SCALAR_TYPES.get(k, {}).get(p, {}).get(key) is None]
    out.append(("T7f every integer/boolean property in either schema is mirrored in "
                "SCALAR_TYPES", not missing, str(missing)))
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
