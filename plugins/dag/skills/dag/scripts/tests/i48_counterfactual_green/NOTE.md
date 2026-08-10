# I48 counterfactual family — the ARMED-AND-GREEN control

Stamped `1.13.0`, so I48 **is** armed — and silent, because `C2.non_vacuity` covers both the
governing entry's `required_observations` and its `forbidden_observations`. rc 0, and **no N-I45
note at all**: nothing was suppressed. That absence is what its `expectations.tsv` row pins
negatively (`!N-I45 version-skew visibility`), so this fixture's green can never decay into
`i48_counterfactual_suppressed`'s green without the suite going red.

Delta from `i48_counterfactual_fires`: one extra `non_vacuity` member on the `C2` row (and the
recomputed I42 digests that follow from it).

See `../i48_counterfactual_fires/NOTE.md` for the full three-column table.

## 1.14.0 — the stamp was RAISED to keep the documented property TRUE

At 1.14.0 this fixture is stamped **`1.14.0`** (was `1.13.0`) and carries `run_mode: "manual"`.

The reason is the property above, not convenience. This fixture's negative pin asserts that
**nothing was suppressed**. The 1.14.0 release adds version-gated arms (`I49-T1`, `I50-T1`,
`I51-1`, `I51-2..6`), so at the old stamp that assertion silently became **false** — the fixture
would have kept exiting 0 while printing the very N-I45 line its row forbids. Raising the stamp
restores the property rather than weakening the pin: I48 is still armed (`1.14.0 >= 1.13.0`), so the
fixture's own subject matter is untouched, and `run_mode` is what the newly-armed `I51-1` requires
of any run stamped at or above the shipping version.

Two sibling fixtures took the other, equally honest route: `i45_no_skew_overfire` and
`i48_counterfactual_suppressed` sit **below** the new gate on purpose, so their pinned skew lists
legitimately GREW and were re-pinned to the new exact output. A pin over a growing list is dated the
moment it is written; re-measure it on every release rather than inheriting it.
