I42-1b, the BELOW-ship-version arm: byte-identical to `digest_shape_mixed` except
`fsm-state.json.validator_version` is `1.10.0`. Spec 3.3 states the closure clause as "mixed
string/object within an armed run => FAIL at >=1.11.0, NOTE below it"; only the FAIL arm was pinned,
and every other digest_* fixture is stamped 1.11.0, so deleting the NOTE branch left all fixtures green.

Expected exit **0** is what pins exit-neutrality (the `panel_withdrawn_note` precedent); the `1.10.0`
stamp is what pins the version arm (the I41-2(b) / `panel_dissent_closure` precedent). The stamp is
load-bearing, not cosmetic. Exit 0 on `N-I42 (partial adoption`.
