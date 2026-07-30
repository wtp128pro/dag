# Fixture: i44_unusable_verify (RED — spec §2.2 arm **P2-b**, one of §0.7's nine mandatory sub-clause witnesses)

Cloned off the `i44_absent_verify_any_phase` spine (`phase: "P6_EXECUTE_VERIFY"`, all five gates true
including `signoff_confirmed`, `fsm.units[U01].status: "verifying"`), then given a
`units/U01/verify.json` that is **present on disk but unusable**: it declares `unit_id: "U99"` while
living in directory `U01`.

That is the D21 mismatch, so per §0.2 the file is **not** inserted into `unit_docs` and `AGG(U01)` is
`None` while `VPRESENT(U01)` is `True` — which is precisely the state that separates arm **b** from
arm **a**.

PROVES arm b fires *on its own*: §0.7 bullet 2 requires "a case that **fails when that sub-clause
alone is violated**", and iteration 1 shipped no witness for P2-b at all (only arms a and d, plus the
two override arms). This closes one of the three missing witnesses.

WHICH LAYER REJECTS IT FIRST — recorded, because it is the trap this fixture had to avoid. Three rows
co-emit here, in this order:

```
FAIL  units/U01/verify.json unit_id mismatch: artifact declares unit_id 'U99' but lives in directory 'U01'
FAIL  I9 missing verification (units/U01): verify.json present but INVALID — no usable verdict
FAIL  I44 sign-off closure (units/U01): UNUSABLE verification (not JSON / not schema-valid / unit_id mismatch) … (arm b; …)
```

The first is the pre-existing D21 check and the second is I9's; both would supply `exit 1` on their
own. That is exactly why this fixture pins the **I44 label stem AND arm b's own detail wording** on
two rows rather than the exit code: a row pinning only `exit == 1` here would be satisfied by
someone else's FAIL, which §0.7 bullet 1 declares inadmissible.

EXPECTED: exit 1, and stdout contains BOTH `I44 sign-off closure (units/U01)` and
`UNUSABLE verification (not JSON / not schema-valid / unit_id mismatch)`. Identical on both backends
(jsonschema Draft202012Validator and `DAG_FORCE_MINI=1`).

DOES NOT COVER: the *other* two ways `AGG(u)` becomes `None` — unparseable JSON, and a doc that is
valid JSON with a matching `unit_id` but fails `verify.schema.json` on some other property (that
second shape is exercised by the sibling `i44_verdictless_verify`); the `--quiet` posture; the
per-unit `accepted_incomplete` downgrade of an arm-b FAIL (only arm a's downgrade is exercised, by
`i44_override_wellformed`).
