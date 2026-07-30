# Fixture: i47_ledger_desync_note (N-I47 / DoD 6 — the advisory the docs promised and nothing shipped)

Phase `DONE`, all five gates true including `signoff_confirmed: true`; `units/U01` carries a debrief at
`iteration: 2` and a **complete, current, verdict-bearing** `verify.json` (`verdict: "PASS"`,
`iteration: 2`) — so I43 emits its positive `I43-ok` row, I44 emits its positive closure row and I46 is
silent. The single defect is the LEDGER: `fsm-state.units[0].status` is `"executing"`, a **non-terminal**
label, under a claimed sign-off. (Derived from `i43_current_positive` by changing that one label.)

This is the shape of the real archived witness `.wip/2026-07-05_143454_implement-dag-loop-proposals`,
whose `U09` sits at `status: "executing"` at phase `DONE` over a complete, iteration-matched `PASS`
verify. I44 is keyed on ARTIFACTS precisely so that run is **not** newly RED for cosmetic desync
(`validate_run.py:5836-5840`), and both that comment and `references/state-machine.md:605` promised the
stale label "is a **separate** predicate". Until this fixture's predicate landed, that separate
predicate was described in three places and shipped in none.

Pins — two rows in `expectations.tsv`, same fixture:
1. exit **0** with `N-I47 ledger desync at sign-off (units/U01)` present — the row is emitted and the run
   stays GREEN, i.e. the NOTE is **exit-neutral** (a bare `print`, touching neither `rep.problems` nor
   `rep.checked`). A pin on the exit code alone would pass vacuously for a predicate that never fires.
2. the same, with `--quiet` in column 4 — the NOTE is **not** quiet-gated, for the §9-R12 reason already
   applied to the `accepted_incomplete` override NOTE and to N-I45: `SKILL.md` mandates `--quiet`, so a
   quiet-gated advisory would be inert in the only invocation that matters. Without this row an
   implementation that hid the NOTE behind `if not args.quiet` would still pass row 1.

Also pinned by construction: the NOTE never double-charges. None of I44's FAIL arms a-d holds here and
neither does I43-a/-b, so this row is the ONLY thing emitted about `U01`'s ledger label.

DOES NOT COVER: `escalated` / `retired` / `blocked` (deliberately NOT in the non-terminal whitelist —
they are CLOSED outcomes at sign-off); a `DISAGREE` verdict under a stale label (admitted by the
predicate, unfixtured); the multi-unit case; and the terminal-status silence boundary — that one is
pinned by the negative row on `i46_no_converged_key` (`status: "passed"` under the same signoff +
current-verify shape), while `i47_ledger_desync_control` pins the sign-off conjunct.
