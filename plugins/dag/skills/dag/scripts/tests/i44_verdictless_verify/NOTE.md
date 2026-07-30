# Fixture: i44_verdictless_verify (spec §2.2 arm **P2-c** — witnessed as UNREACHABLE, not merely unbuilt)

Cloned off the `i44_absent_verify_any_phase` spine, then given a `units/U01/verify.json` that is
byte-for-byte a valid aggregated verify **with the `verdict` key deleted** — the literal shape §2.2
arm **c** is written against (`elif "verdict" not in AGG(u)`).

FINDING: **arm c is unreachable through `unit_docs`, and this fixture is the mechanical proof.**
`verify.schema.json`'s `required` list is
`['unit_id','verifier_persona','verdict','iteration','executor_reasoning_seen','feedback','defects','socratic','premise_check']`
— `verdict` is **required**. So a verdict-less verify is schema-INVALID, is therefore never inserted
into `unit_docs` (§0.2: `AGG(u)` is `None` when parse *or* schema *or* `unit_id` failed), and the
`elif` chain settles on arm **b** before arm **c** is ever evaluated. Measured, both backends:

```
FAIL  units/U01/verify.json: $: 'verdict' is a required property         # jsonschema backend
FAIL  units/U01/verify.json: $: missing required property 'verdict'      # DAG_FORCE_MINI backend
FAIL  I44 sign-off closure (units/U01): UNUSABLE verification (…) … (arm b; …)
```

(The two backends word the schema error differently, which is why this fixture pins **neither** of
those strings — it pins the I44 label stem and `(arm b;`.)

WHY THE FIXTURE SHIPS ANYWAY, rather than being filed as prose. The `(arm b;` pin asserts the
**shadowing** itself. Arm c is dead code *given the current schema*, not dead code by construction —
if a future change made `verdict` optional (or if a degraded no-schema mode admitted the doc), arm c
would become reachable and this row would go RED, which is exactly the signal that P2-c has acquired
a domain and now needs a witness of its own. Filing it as prose would leave that transition silent.

This discharges P2-c under the §1.6 P1-G3 standard — an *infeasibility argument*, measured rather
than asserted — which is the standard iteration 1 applied to P1-G3 and failed to apply here.

EXPECTED: exit 1, and stdout contains BOTH `I44 sign-off closure (units/U01)` and `(arm b;`.

DOES NOT COVER: a hypothetical no-schema degraded mode in which the doc is admitted and arm c fires
for real (unreachable from `run_tests.sh`, which always loads a backend); the `--quiet` posture; a
`verdict` present but not in the schema enum (also a schema failure, hence also arm b).
