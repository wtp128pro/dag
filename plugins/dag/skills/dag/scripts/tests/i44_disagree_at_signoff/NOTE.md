# Fixture: i44_disagree_at_signoff (spec §2.2 arm **P2-e** — unresolved DISAGREE at sign-off is a NOTE, never a FAIL)

Cloned off the `i44_absent_verify_any_phase` spine (`phase: "P6_EXECUTE_VERIFY"`, all five gates true
including `signoff_confirmed: true`, `fsm.units[U01].status: "verifying"`), then given a fully
schema-valid `units/U01/verify.json` with `verdict: "DISAGREE"`, `iteration: 2` (matching the
debrief, so P1 and arm d both stay silent and the assertion is unambiguous), and a `disagreement`
block carrying `why_unresolvable`.

PROVES arm **e** fires on its own AND that its severity is exit-neutral. §2.2's rationale is
load-bearing: *"A `DISAGREE` verdict is a **complete** verification act that declares
irresolvability; its sanctioned resolution is `LT6 → ESCALATE → Phase 7`, a human gate, not more
verification."* Failing on it would attack AO-5 (*genuine split ⇒ human, not loop*) from the
incentive side by creating pressure on a verifier to avoid `DISAGREE`. So the fixture asserts BOTH
halves on two rows:

- the NOTE is **present**: `N-I44 sign-off closure (unresolved DISAGREE at sign-off) (units/U01)`;
- no FAIL is emitted: `!FAIL  I44 sign-off closure` (the must-NOT-contain pin). Without this second
  row a promotion of arm e to a hard FAIL — which §9-R2 explicitly contemplates as a *future,
  census-gated* change — would slip in without a red row.

Measured, exit 0 on both backends. A third row co-emits and is deliberately **not** asserted here:
`N-I47 ledger desync at sign-off (units/U01)`, a different predicate's advisory NOTE about the stale
`verifying` status label. It belongs to the `i47_*` fixtures.

EXPECTED: exit 0, stdout contains `N-I44 sign-off closure (unresolved DISAGREE at sign-off)
(units/U01)`, and stdout does **not** contain `FAIL  I44 sign-off closure`.

DOES NOT COVER: the §9-R2 census shape (a `DISAGREE` at sign-off with **no** `units/<u>/disagreement.*`
sidecar on disk — this fixture carries the record inside the verify's own `disagreement` block, not as
a separate file, and P2-e reads neither); the `--quiet` posture (§8.6 gates the `N-I44` rows, so this
NOTE is invisible under the mandated orchestrator invocation — the same gap §9-R12 records); a
`DISAGREE` that is *also* superseded (arm d would win, since the `elif` chain reaches d first).
