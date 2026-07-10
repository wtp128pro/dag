#!/usr/bin/env bash
# run_fixtures.sh — NEGATIVE-fixture runner for spec_check.py (SC1..SC5).
#
# For each row of expectations.tsv (fixture <TAB> expected-exit <TAB> pinned FAIL
# substring) this assembles a THROWAWAY temp root = a copy of the real skill dir
# with the fixture's overlay/ laid on top, runs `spec_check.py --root TMP --quiet`,
# and asserts (a) the exact pinned FAIL substring is present AND (b) the exit code
# matches. The real tree is NEVER mutated — every mutation lives only in the temp
# root, which is removed after each case. Exit 0 iff every fixture met its pin.
#
# Usage:  bash scripts/tests/spec_check/run_fixtures.sh
# U10 wires this (or the equivalent loop) into scripts/tests/run_tests.sh.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../scripts/tests/spec_check
SKILL_DIR="$(cd "$HERE/../../.." && pwd)"              # .../skills/dag
SPEC_CHECK="$SKILL_DIR/scripts/spec_check.py"
EXPECT="$HERE/expectations.tsv"

pass=0
fail=0

while IFS=$'\t' read -r fixture exp_exit substr; do
  case "$fixture" in ''|'#'*) continue ;; esac
  overlay="$HERE/$fixture/overlay"
  if [ ! -d "$overlay" ]; then
    echo "FAIL  $fixture  — no overlay/ dir"
    fail=$((fail + 1)); continue
  fi
  tmp="$(mktemp -d)"
  cp -a "$SKILL_DIR"/. "$tmp"/            # full copy of the real skill dir
  cp -a "$overlay"/. "$tmp"/             # lay the mutated file(s) on top
  out="$(python3 "$SPEC_CHECK" --root "$tmp" --quiet 2>&1)"; code=$?
  rm -rf "$tmp"

  ok=1
  [ "$code" = "$exp_exit" ] || ok=0
  printf '%s' "$out" | grep -qF -- "$substr" || ok=0

  if [ "$ok" = 1 ]; then
    echo "PASS  $fixture  (exit=$code; pinned: $substr)"
    pass=$((pass + 1))
  else
    echo "FAIL  $fixture  (exit=$code, want $exp_exit; missing pin: $substr)"
    echo "------ spec_check output ------"; printf '%s\n' "$out"; echo "-------------------------------"
    fail=$((fail + 1))
  fi
done < "$EXPECT"

echo
echo "spec_check negative fixtures: $pass passed, $fail failed"
[ "$fail" = 0 ]
