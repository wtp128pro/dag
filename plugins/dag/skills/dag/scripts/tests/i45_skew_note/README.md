I41 archive-safety: byte-identical to panel_dissent_unadjudicated except validator_version 1.9.0.
Pins that the T1 gate uses _i27_semver_ge and NOT a raw string compare — '1.9.0' >= '1.11.0' is TRUE
lexicographically and FALSE under semver. 1.10.0 would compare False both ways and leave the bug
unpinned. Exit 0.
