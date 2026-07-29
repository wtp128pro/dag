I42-3 PATH-OWNER semantics, the DISCRIMINATOR (invariant-spec §3.3 disambiguation / §3.4 cross-unit corner
row / §10 CR-6). Byte-identical to `digest_mismatch_crossunit_note` except one field: **U01, the unit that
owns the digested path, is `passed`** — terminal, so nothing may legitimately still be rewriting
`units/U01/debrief.json`. The digesting verify belongs to U02, which is still `verifying` at
`P6_EXECUTE_VERIFY`. Expected exit 1 on `digest mismatch`, exactly one FAIL.

This is the only fixture in the tree that separates the two readings of "the owning unit":
  - PATH-owner (correct, and what I42-3 ships): status of **U01** = `passed` ⇒ outside the I9 window ⇒ FAIL.
  - VERIFY-owner (the pre-CR-6 reading, `_st42 = _i42_status.get(uid)`): status of **U02** = `verifying`
    ⇒ inside the window ⇒ wrongly downgraded to a NOTE ⇒ exit **0**.
Restore the verify-owner keying and this fixture turns green while every other `digest_*` fixture stays at
its expectation — the four pre-existing I42-3 fixtures all digest a path in the SAME unit as the verify, so
`_i42_owner(path) == uid` holds for every one of them and none of them can see the difference.
