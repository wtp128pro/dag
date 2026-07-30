# Fixture: i45_skew_note (the N-I45 NOTE MUST APPEAR; spec §3.1/§3.5 P3-R1)

Byte-clone of `panel_dissent_version_silent/` — a run whose `fsm-state.json.validator_version` is
BELOW the `1.11.0` ship of the I41 arms while the NON-version precondition of those arms (an
aggregate `PASS` carrying a dissenting panel member) HOLDS. Its sibling row
`panel_dissent_version_silent  0  <empty>` proves the I41 FAIL is stamp-suppressed; this fixture
proves the SUPPRESSION ITSELF becomes visible.

PROVES: P3 emits its shadow count of stamp-suppressed ARMS. An arm was suppressed by the stamp alone
exactly when its non-version conjunct held while `_i27_semver_ge(stamp, SHIP)` returned `False`, so
`_SKEW` must be non-empty here and the NOTE must name a count `>= 1` with a non-empty arm-id list.
Per §3.5 the exit code must be UNCHANGED from the same fixture with the P3 block removed — that
baseline is `panel_dissent_version_silent`'s own row (exit 0), so the pair also pins P3's
exit-neutrality BY CONSTRUCTION (a bare `print`, touching neither `rep.problems` nor `rep.checked`).

EXPECTED: exit 0 AND stdout contains `N-I45 version-skew visibility`.

DOES NOT COVER: the printed COUNT's correctness (the stem pin cannot check the number, and per L16 a
right number with a wrong mechanism is still a defect); the §3.1(3) upper-bound sentence, which is
NORMATIVE wording, not commentary; §3.3's `--quiet` posture (`run_tests.sh` invokes the validator
without `--quiet`, so a quiet-gated N-I45 still passes this row — an UNCLOSED gap, recorded rather
than papered over); the §3.1(4) dev-time completeness assertion
(`count(_skew_record() == count(_i27_semver_ge() - 1`), which is not a fixture at all.

