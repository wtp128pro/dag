# Fixture: i44_override_quiet_visible (RED for the gating defect — the override NOTE survives `--quiet`)

A byte-copy of the `i44_override_wellformed` spine (signed off, `units/U01` executed with NO
`verify.json`, plus a WELL-FORMED top-level `accepted_incomplete` naming exactly `["U01"]` with
non-blank `rationale`, a `decision_ref` containing the literal `DECISIONS.md`, and a real
`DECISIONS.md` in the run dir — all six §2.3 downgrade conditions hold). The spine fixture is left
untouched; this row differs from it in ONE respect only: **the harness runs it with `--quiet`**
(expectations.tsv column 4).

PROVES: the un-gating of `_vc_override_note` (§9-R12). Before the fix the helper printed under
`if not args.quiet`, so a fully-overridden run under the invocation `SKILL.md` MANDATES emitted
**593 bytes and ZERO `N-I44` rows** — `Report.ok` is quiet-gated too, and `_i44_fired` is set by any
matched arm before the override branch, so the §2.4 positive assertion could not fire either. The
human ruling requires the override be "available but LOUD: deliberate, grep-visible, per-unit"; this
row is the mechanical pin on the *grep-visible* half. Its GREEN control is
`i44_override_quiet_control`.

EXPECTED: exit **0** AND stdout (under `--quiet`) contains
`N-I44 sign-off closure (accepted-incomplete override) (units/U01)`.

DOES NOT COVER: the over-broad-override companion NOTE (un-gated in the same change; no surplus id
here — see `i44_override_wellformed`'s DOES-NOT-COVER list); the I46 call site of the same helper,
which the un-gating also makes `--quiet`-visible; the malformed-override path (never quiet-gated,
because `rep.fail` is not — `i44_override_malformed`).
