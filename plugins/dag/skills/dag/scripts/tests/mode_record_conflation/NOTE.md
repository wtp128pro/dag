# I51 — conflation reported as compliance, until the record direction was checked

This run declares `run_mode: "manual"`, sets `gates.signoff_confirmed: true` — the **human**
vocabulary — carries a DS-5 **human** dialogue record, **and** carries a `machine-decisions.json`
record for the same gate.

**It passed clean**, and I51's own green line asserted **"channels disjoint"** while both channels
described gate `signoff`, and **`mode='manual'`** — whose own FAIL text reads *"manual means today's
behaviour and ZERO machine closures"* — beside one machine closure sitting on disk.

The cause: every arm keyed on the **flag**, and the records were consulted only *inside*
`if not machine_closed[g]: continue`. The record→flag direction was unchecked entirely, so a machine
decision with no corresponding flag was invisible to the invariant whose whole purpose is to keep the
two channels apart. Three converse arms now close it: exclusivity by record, unflagged record, and
mode consistency over records rather than only over flags.

Note what was catching this before, and what was not: without the DS-5 dialogue the run is caught
*incidentally* by `I35 (surface coverage DS-5)` — a different invariant, for a different reason —
while I51 stays fully green either way. An invariant that relies on a neighbour to cover its own
subject matter is not covering it.
