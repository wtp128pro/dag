GREEN base for the 1.15.0 blast-radius predicates (I60-I64), derived from clock_surfaced_ok and re-stamped 1.15.0.
Wave 1 runs U01 and U03 (both `ships`, disjoint frames); wave 2 runs U02 (`informs`, empty footprint).
Every executed unit carries footprint.json (+ .sha256); each ships unit carries impact.json (+ .sha256) and an
aggregated verify.json blast_audit; integration.json (+ .sha256) is consistent with fsm-state.blast and the footprints.
All hashes are synthetic but internally consistent. Red fixtures are derived from this directory by
blast_mutations/mutate.py, one defect each; regenerate them after editing this fixture.
