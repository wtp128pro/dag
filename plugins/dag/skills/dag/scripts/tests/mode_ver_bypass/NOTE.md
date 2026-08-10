# I51 — the hole in the REVISES, and the fixture that keeps it shut

A run at **DONE** with **no human sign-off and no machine record at all**: stamped `1.13.0`,
`gates.signoff_machine_closed: true`, `gates.signoff_confirmed` absent, `machine-decisions.json`
DELETED.

**This exited 0 with ZERO `I51` rows.** The satisfaction widening (`<g>_confirmed OR
<g>_machine_closed`) was unversioned, while every arm that gives `<g>_machine_closed` meaning —
I51-2 exclusivity, I51-3 backing, I51-4 critical, I51-5 mode, I51-6 disjointness — is gated at
1.14.0. Below that stamp the flag was load-bearing and unpoliced, and the validator printed
*"closed by the MACHINE channel, not by a human"* having verified nothing.

**It is not an adversarial-only path.** `init_run.sh --restamp` is opt-in and unenforced, so any run
scaffolded before the bump and continued after it keeps the old stamp while the 1.14.0 `SKILL.md`
instructs the orchestrator to set exactly this key.

The widening is now gated on the same predicate as its guards, so the flag is never load-bearing
where its guards are asleep. Archive-safe by construction: no pre-1.14.0 run sets the key — verified,
all 22 archived runs unchanged. Its green twin is `mode_machine_ok`, the same directory at 1.14.0
with the record present.
