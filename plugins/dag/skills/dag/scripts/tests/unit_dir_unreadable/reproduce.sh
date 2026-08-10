#!/usr/bin/env bash
# reproduce.sh — the RED half of the unit_dir_unreadable fixture.
#
# A mode-000 directory CANNOT be committed to git (git records no directory modes at all — only
# the executable bit on blobs), so the committed fixture is the READABLE control and this script
# manufactures the unreadable state at test time, on a THROWAWAY COPY, and restores it. The
# committed tree is never chmod'ed.
#
# Usage: reproduce.sh [--validator PATH]
#   --validator PATH   validate the copy with PATH instead of ../../validate_run.py. Used to drive
#                      the PRE-guard validator (e.g. `git show <sha>:…/validate_run.py > /tmp/vr.py`)
#                      so the red and green sides are DEMONSTRATED to differ rather than asserted.
#
# Asserts, on a units/<id>/ the validator cannot read:
#   1. a FAIL row NAMING the unit id                     (not the silent os.path.exists() drop)
#   2. exactly one RESULT: line                          (the run reaches its summary)
#   3. no Python traceback                               (the crash is gone)
#   4. a non-zero exit                                   (the crash was not traded for silence)
# Exit 0 = all four hold. Exit 1 = one or more failed (print says which). Exit 0 + a loud SKIP line
# when the condition is unreproducible on this host (uid 0, or a filesystem that ignores mode 000).
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
VR="$HERE/../../validate_run.py"
while [ $# -gt 0 ]; do
  case "$1" in
    --validator) VR=$2; shift 2 ;;
    -h|--help) echo "usage: reproduce.sh [--validator PATH]"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t dagunread)
# Restore the mode BEFORE rm -rf: a mode-000 dir cannot be recursed into, so a bare rm -rf would
# leave the temp tree behind.
cleanup() { chmod 755 "$TMP/r/units/U01" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

cp -R "$HERE" "$TMP/r"
rm -f "$TMP/r/reproduce.sh" "$TMP/r/NOTE.md"   # keep the copy a pure run dir
chmod 000 "$TMP/r/units/U01"

# Precondition self-check: PROVE the directory is actually unreadable before claiming the assertions
# below mean anything. Under uid 0 (and on some FUSE/container mounts) mode 000 is not enforced, and
# a fixture that silently validates a READABLE directory is worse than no fixture at all.
if ls "$TMP/r/units/U01" >/dev/null 2>&1; then
  echo "  SKIP  unit_dir_unreadable — mode 000 is not enforced here (uid=$(id -u)); the condition"
  echo "        under test cannot be produced on this host, so NOTHING was verified."
  exit 0
fi

# --schemas is passed explicitly so an ALTERNATE --validator (a `git show` copy in /tmp, which
# would otherwise resolve schemas/ relative to ITSELF and exit 3 before reaching the scan block)
# is exercising the same schemas as the shipped one. Without this the red side "passes" for the
# wrong reason — an invalid control.
OUT=$("${PYTHON:-python3}" "$VR" "$TMP/r" --schemas "$HERE/../../../schemas" 2>&1); RC=$?
N_RESULT=$(printf '%s\n' "$OUT" | grep -c '^RESULT:')
rc_all=0
check() {  # <name> <condition-result 0/1>
  if [ "$2" -eq 0 ]; then echo "  PASS  $1"; else echo "  FAIL  $1"; rc_all=1; fi
}

printf '%s\n' "$OUT" | grep -q 'FAIL  units/U01/ unreadable'; check "FAIL row NAMES the unreadable unit (U01)" $?
[ "$N_RESULT" -eq 1 ]; check "exactly one RESULT: line (summary reached; saw $N_RESULT)" $?
! printf '%s\n' "$OUT" | grep -q 'Traceback (most recent call last)'; check "no Python traceback" $?
[ "$RC" -ne 0 ]; check "non-zero exit (rc=$RC) — LOUD, not silently skipped" $?

if [ "$rc_all" -ne 0 ]; then
  echo "---- validator output (last 12 lines) ----"
  printf '%s\n' "$OUT" | tail -12
fi
exit "$rc_all"
