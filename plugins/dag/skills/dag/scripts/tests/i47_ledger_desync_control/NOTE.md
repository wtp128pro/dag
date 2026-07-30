# Fixture: i47_ledger_desync_control (GREEN over-fire control for N-I47 — the SIGN-OFF conjunct)

Derived from `i43_inflight_signoff_false` by raising the aggregated verify to `iteration: 2` so it
MATCHES the debrief. The result is the single most common healthy shape in the whole pipeline: phase
`P6_EXECUTE_VERIFY`, `gates.signoff_confirmed: false`, `units/U01` at `status: "verifying"` — a
**non-terminal** label — over a **complete, current, verdict-bearing PASS** verify.

PROVES that N-I47's first antecedent conjunct (`gates.signoff_confirmed is True`, by identity) is
load-bearing. Every mid-loop unit in every run is non-terminal while its verify is current; an
implementation that arms on "non-terminal + current verify" alone would fire on **every healthy
in-flight unit**, turning the advisory into noise. This row's pin is NEGATIVE (`!` prefix on column 3):
the substring `N-I47 ledger desync at sign-off` must be **ABSENT**. A presence-only harness would pass
such a control vacuously, which is exactly why the negative pin exists.

Both this row and its `--quiet` sibling on the positive fixture are needed: together they show the NOTE
is genuinely visible when the antecedent holds and genuinely absent when it does not.

EXPECTED: exit 0 AND stdout does NOT contain `N-I47 ledger desync at sign-off`. (`N-I43 verification
currency (in-flight)` also stops firing here, since the iterations now match — I43 takes its `I43-ok`
arm instead; that is intended and is why this is a distinct fixture rather than an edit of
`i43_inflight_signoff_false`, which stays byte-untouched.)

DOES NOT COVER: the terminal-status boundary (pinned by the negative row on `i46_no_converged_key`,
which carries `signoff_confirmed: true` with `status: "passed"`); a present-but-truthy-non-`True`
sign-off flag (`1`, `"true"`) — an implementation using `bool(...)` still passes this row; an absent
`fsm-state.json` entirely.
