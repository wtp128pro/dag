#!/usr/bin/env bash
# run_tests.sh — executable, HOME-isolated fixture harness for the dag validator.
#
# Runs validate_run.py against every scripts/tests/ fixture listed in tests/expectations.tsv,
# on each available validator backend, and exercises schemas/manifest.schema.json against its
# instance pair (manifest_examples, N-09). Exits non-zero if ANY fixture's exit code or pinned
# FAIL-line substring does not match. This is the CI (the repo has no other); it is test
# infrastructure only — PRESERVES (no enforcement change). Closes IMP-16 (fixture verdicts
# formerly depended on the operator's real $HOME) by stubbing HOME to a temp dir.
#
# Usage: run_tests.sh [--real-home]
#   --real-home   do NOT isolate $HOME (use the real ~/.claude/dag/ — for manually exercising
#                 the G1/G2 global-store paths; see tests/LIMITATIONS.md).
# Env:
#   DAG_TEST_VENV   path to a venv whose bin/python has `jsonschema` installed; if set (or if the
#                   system python3 imports jsonschema), the sweep also runs the jsonschema backend.
#                   The runner NEVER pip-installs anything.
# Backend matrix (G7): the fixture sweep runs UNCONDITIONALLY on both backends — the normal backend
# (jsonschema if importable) AND a forced pass with DAG_FORCE_MINI=1 (the stdlib mini-validator), so
# the fallback is exercised even on hosts (CI) where jsonschema is installed and would otherwise hide
# it. spec_check + its negative fixtures run ONCE on the normal backend (their pins assume jsonschema).
set -eu

REAL_HOME=0
for arg in "$@"; do
  case "$arg" in
    --real-home) REAL_HOME=1 ;;
    -h|--help) echo "usage: run_tests.sh [--real-home]"; exit 0 ;;
    *) echo "unknown arg: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# Resolve this script's dir (symlink- and CWD-safe), so the runner works from any CWD.
SCRIPTS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TESTS_DIR="$SCRIPTS_DIR/tests"
EXP="$TESTS_DIR/expectations.tsv"
VR="$SCRIPTS_DIR/validate_run.py"
TAB=$(printf '\t')

if [ ! -f "$EXP" ]; then echo "FATAL: expectations.tsv not found at $EXP" >&2; exit 2; fi

# HOME isolation (IMP-16): make ~/.claude/dag/{learnings,tags.json} deterministically absent.
if [ "$REAL_HOME" -eq 0 ]; then
  DAG_TMP_HOME=$(mktemp -d 2>/dev/null || mktemp -d -t dagtests)
  export HOME="$DAG_TMP_HOME"
  trap 'rm -rf "$DAG_TMP_HOME"' EXIT INT TERM
  echo "HOME isolated -> $HOME"
else
  echo "HOME: real ($HOME)  [--real-home: G1/G2 global-store paths may be exercised]"
fi

fail_total=0

# Step 0: schema self-check (14 schemas well-formed).
echo "== self-check =="
if bash "$SCRIPTS_DIR/validate_run.sh" --self-check >/dev/null 2>&1; then
  echo "  PASS  schema self-check (14 schemas)"
else
  echo "  FAIL  schema self-check"
  fail_total=$((fail_total + 1))
fi

# Build the interpreter list (backend matrix). Always the system python3; plus a jsonschema-capable
# interpreter if DAG_TEST_VENV points at one. make_validator() prefers jsonschema when importable,
# so the two interpreters may resolve to the two distinct backends (reported per run below).
INTERPRETERS="python3"
if [ -n "${DAG_TEST_VENV:-}" ] && [ -x "$DAG_TEST_VENV/bin/python" ]; then
  INTERPRETERS="$INTERPRETERS $DAG_TEST_VENV/bin/python"
fi

backends_seen=""

# Sweep the fixture matrix on each interpreter AND, unconditionally, a second time with
# DAG_FORCE_MINI=1 (G7): the stdlib fallback validator is otherwise HIDDEN wherever jsonschema is
# installed (i.e. exactly where CI runs), so force it so both backends are exercised on every host.
# make_validator() picks the backend; this only selects which one. spec_check + spec_check negative
# fixtures below run ONCE (not forced-mini) — their pinned substrings assume the jsonschema backend.
for PY in $INTERPRETERS; do
  for FORCE_MINI in 0 1; do
    if [ "$FORCE_MINI" -eq 1 ]; then FORCE_ENV="DAG_FORCE_MINI=1"; else FORCE_ENV=""; fi
    # Sweep every expectations.tsv row with this interpreter + backend mode.
    backend=""
    n_pass=0
    n_fail=0
    while IFS="$TAB" read -r path exp sub || [ -n "$path" ]; do
      case "$path" in ''|'#'*) continue ;; esac
      set +e
      out=$(env $FORCE_ENV "$PY" "$VR" "$TESTS_DIR/$path" </dev/null 2>&1)
      rc=$?
      set -e
      if [ -z "$backend" ]; then
        backend=$(printf '%s\n' "$out" | head -1 | sed 's/^validate_run.py — backend: //')
        echo "== sweep ($PY${FORCE_ENV:+ +$FORCE_ENV}) — backend: $backend =="
      fi
      ok=1
      reason=""
      if [ "$rc" -ne "$exp" ]; then ok=0; reason="exit $rc != expected $exp"; fi
      if [ -n "$sub" ]; then
        case "$out" in
          *"$sub"*) : ;;
          *) ok=0; reason="${reason:+$reason; }missing pinned FAIL substring: $sub" ;;
        esac
      fi
      # WP-A regression guard (B1/B3): the validator must NEVER abort with a Python traceback — a crash
      # silently disables every downstream invariant. Any traceback in a fixture's output is a hard
      # regression regardless of the expected exit code (a schema-valid-but-malformed artifact must FAIL
      # cleanly, not crash).
      case "$out" in
        *"Traceback (most recent call last)"*)
          ok=0; reason="${reason:+$reason; }validator emitted a Python TRACEBACK (crash)" ;;
      esac
      if [ "$ok" -eq 1 ]; then
        n_pass=$((n_pass + 1))
      else
        n_fail=$((n_fail + 1))
        echo "  FAIL  $path — $reason"
      fi
    done < "$EXP"
    echo "  -> $PY${FORCE_ENV:+ +$FORCE_ENV} [$backend]: $n_pass passed, $n_fail failed"
    fail_total=$((fail_total + n_fail))
    case "$backends_seen" in *"$backend"*) : ;; *) backends_seen="${backends_seen:+$backends_seen, }$backend" ;; esac
  done
done

# manifest_examples (N-09): schemas/manifest.schema.json is not auto-run against a run dir, so
# check its instance pair directly. Reuse make_validator() (no jsonschema required — falls back
# to the built-in mini validator).
echo "== manifest_examples (schema-instance pair) =="
set +e
mout=$(python3 - "$SCRIPTS_DIR" <<'PY'
import json, os, sys
sd = sys.argv[1]
sys.path.insert(0, sd)
import validate_run as V
validate, _ = V.make_validator()
schema = json.load(open(os.path.join(sd, "..", "schemas", "manifest.schema.json")))
rc = 0
cases = (("tests/manifest_examples/valid.json", True),
         ("tests/manifest_examples/invalid_missing_grain.json", False))
for rel, expected_valid in cases:
    errs = validate(json.load(open(os.path.join(sd, rel))), schema)
    is_valid = not errs
    mark = "PASS" if is_valid == expected_valid else "FAIL"
    print("  %s  manifest %s valid=%s (expected %s)"
          % (mark, os.path.basename(rel), is_valid, expected_valid))
    if is_valid != expected_valid:
        rc = 1
sys.exit(rc)
PY
)
mrc=$?
set -e
printf '%s\n' "$mout"
if [ "$mrc" -ne 0 ]; then fail_total=$((fail_total + 1)); fi

# spec_check (dev-time prose<->spec<->code drift checker, U05-U07: SC1-SC7). Static check,
# run ONCE (not per-backend, like manifest_examples). A non-zero exit folds into fail_total,
# so any drift FAILs this harness. spec_check lives HERE only — never in validate_run.py's
# run path (it never reads spec/). PRESERVES (test infrastructure only, no enforcement change).
echo "== spec_check (clean run on real tree) =="
set +e; scout=$(python3 "$SCRIPTS_DIR/spec_check.py" 2>&1); scrc=$?; set -e
printf '%s\n' "$scout"
if [ "$scrc" -ne 0 ]; then fail_total=$((fail_total + 1)); fi

# spec_check negative fixtures (U09): each overlay mutant must FAIL its pinned SC check on a
# throwaway temp-root copy (the real tree is never written). The runner self-locates and
# consumes scripts/tests/spec_check/expectations.tsv; a non-zero exit folds into fail_total.
echo "== spec_check negative fixtures =="
set +e; sfout=$(bash "$SCRIPTS_DIR/tests/spec_check/run_fixtures.sh" 2>&1); sfrc=$?; set -e
printf '%s\n' "$sfout"
if [ "$sfrc" -ne 0 ]; then fail_total=$((fail_total + 1)); fi

echo "== summary =="
echo "backends exercised: ${backends_seen:-none}"
if [ "$fail_total" -eq 0 ]; then
  echo "RESULT: PASS (all fixtures + manifest pair + self-check green)"
  exit 0
else
  echo "RESULT: FAIL ($fail_total mismatch(es))"
  exit 1
fi
