# I48 counterfactual family — the SUPPRESSED control

Artifacts under `units/` are **byte-identical** to `i48_counterfactual_fires`; only `fsm-state.json`
differs (`validator_version` `1.12.1` instead of `1.13.0`, plus the cosmetic `run_dir` label). The
partly-vacuous `C2` discharge row that makes `_fires` FAIL is present here too and goes **unjudged**:
`_I48_SHIP = "1.13.0"` is above this stamp, so the arm never arms. rc 0, `RESULT: PASS`.

This is the archive-safety mechanism, and the trap: **a suppressed arm reads exactly like a correct
run.** The only discriminator on the wire is the N-I45 version-skew NOTE, which this fixture's
`expectations.tsv` row pins verbatim (`… HELD: ['I48-T1']`).

See `../i48_counterfactual_fires/NOTE.md` for the full three-column table.
