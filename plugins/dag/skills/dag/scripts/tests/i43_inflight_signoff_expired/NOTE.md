# Fixture: i43_inflight_signoff_expired (RED — THE DISCRIMINATING WITNESS; spec §1.3/§1.6 P1-R2)

Byte-identical to `i43_inflight_before_signoff` except `gates.signoff_confirmed: true`. Phase
`P6_EXECUTE_VERIFY`, `fsm.units[U01].status: "verifying"`, `debrief.iteration: 2`,
`verify.iteration: 1`.

PROVES: the in-flight carve-out EXPIRES at claimed completion. §1.3: `IN_FLIGHT(u) := WINDOW(u) AND
not SIGNED_OFF`. A verbatim copy of I9's two-conjunct window (`:5594`) and the correct three-conjunct
carve-out differ on EXACTLY this input — `WINDOW` true AND `SIGNED_OFF` true. **A verbatim-I9
implementation downgrades this to a NOTE and exits 0, and `SKILL.md` mandates `--quiet`, which
suppresses NOTEs entirely — so the predicate would be inert on precisely the run class that
motivates it.** Per L11 this is the sub-clause most likely to go unpinned, so it gets its own
directory and its own pinned stem.

EXPECTED: exit 1 AND a FAIL row labelled `I43 verification currency (units/U01)`.

DOES NOT COVER: which arm (P1-a vs P1-b) fired — the shape is SUPERSEDED, so an implementation that
drops P1-b still passes; the detail text's `gates.signoff_confirmed` field (§1.1 requires it be
printed, which the stem pin cannot check); the `executing` status half of `WINDOW`.

