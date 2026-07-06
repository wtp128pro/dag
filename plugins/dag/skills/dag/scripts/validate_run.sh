#!/usr/bin/env bash
# validate_run.sh — runtime prober + dispatcher for the dag validator.
#
# Enforcement entry point Dag calls from SKILL.md (via Bash) after each
# artifact is written and at each gate. Requires python3 (the sole, full validator —
# stdlib-only, no third-party deps and no Node.js). If python3 is absent it FAILS LOUDLY
# with a clear message and a non-zero exit — it never silently "passes".
#
# Usage:  validate_run.sh <run_dir> [--self-check] [--quiet]
# Exit:   passthrough from the validator · 3 = python3 not available.
set -eu
# N-19: resolve this script's REAL dir, following a symlink to $0 (so `ln -s .../validate_run.sh
# /elsewhere/x.sh && x.sh` still finds validate_run.py beside the real script). CDPATH= and `pwd -P`
# keep it CWD- and symlink-safe.
SOURCE="$0"
while [ -h "$SOURCE" ]; do
  DIR="$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd -P)"
  SOURCE="$(readlink "$SOURCE")"
  case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
HERE="$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd -P)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/validate_run.py" "$@"
else
  echo "ERROR: python3 not found. The dag validator requires python3 (stdlib only;" >&2
  echo "       no Node.js, no pip installs). Install python3 to run validation." >&2
  echo "       Refusing to pass without validation." >&2
  exit 3
fi
