#!/usr/bin/env bash
# run_formal.sh — one-command reproduction of the TLA+/Alloy machine-checks.
#
# The two toolchain jars are BUILD tools, not skill files: they are FETCHED to a cache dir (default
# /tmp), NOT vendored into the repo — the Alloy dist.jar bundles a research-only SAT solver (Lingeling)
# and LGPL SAT4J, so it is deliberately not committed (see formal-models.md + this repo's policy). This
# script fetches them (checksum-verified), compiles the vendored formal/AlloyRun.java driver, and runs:
#   * TLC on formal/Pipeline.cfg (MaxFuel=2, the shipped ceiling)  -> expect 853/408/depth 36, No error
#   * TLC on a TEMP MaxFuel=32 cfg (with --maxfuel32; cfg stays 2) -> expect 2923/1608/depth 156
#   * the Alloy driver on WorkGraph.als + Amendment.als (headless) -> expect 8/8 commands as-expected
# Nothing is written into the REPO: TLC's metadir is redirected to the CACHE via -metadir (D3), and the
# Alloy classes compile to a temp dir. Exit non-zero if any check fails or a jar checksum mismatches hard.
#
# WP-F harness integrity: the advertised numbers are now ASSERTED, not merely echoed (D1) — a cfg
# stripped of every INVARIANT/PROPERTY, or an .als stripped of every command, now FAILs instead of
# printing a vacuous PASS. See the `need`/count assertions below and formal/AlloyRun.java's expected-count.
#
# Usage: run_formal.sh [--maxfuel32] [--cache DIR]
# Env:   JAVA_HOME (optional; else `java`/`javac` on PATH). DAG_FORMAL_CACHE overrides the jar cache dir.
set -eu

CACHE="${DAG_FORMAL_CACHE:-/tmp}"
RUN_MAXFUEL32=0
# D2: robust arg parsing (while/case/shift), so `--cache DIR` works in any position and an unknown flag
# is a hard error rather than silently ignored (the old `for arg in "$@"; shift` mis-parsed --cache DIR).
while [ $# -gt 0 ]; do
  case "$1" in
    --maxfuel32) RUN_MAXFUEL32=1 ;;
    --cache)     shift; CACHE="${1:?--cache needs a DIR argument}" ;;
    --cache=*)   CACHE="${1#--cache=}" ;;
    -h|--help)   echo "usage: run_formal.sh [--maxfuel32] [--cache DIR]"; exit 0 ;;
    *)           echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

# Resolve the skill dir (scripts/..) so formal/ paths resolve from any CWD.
SCRIPTS_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
SKILL_DIR=$(CDPATH= cd -- "$SCRIPTS_DIR/.." && pwd -P)
cd "$SKILL_DIR"

JAVA="${JAVA_HOME:+$JAVA_HOME/bin/}java"
JAVAC="${JAVA_HOME:+$JAVA_HOME/bin/}javac"

TLA_JAR="$CACHE/tla2tools.jar"
ALLOY_JAR="$CACHE/alloy.jar"
# Pinned sources. Alloy is an IMMUTABLE release tag -> hard checksum. tla2tools uses the documented
# `latest` URL (a moving target) -> SOFT checksum: a newer TLC 2.x still reproduces the same
# model-determined state counts, so a mismatch WARNs (does not fail) with the last-verified hash.
TLA_URL="https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar"
ALLOY_URL="https://github.com/AlloyTools/org.alloytools.alloy/releases/download/v6.2.0/org.alloytools.alloy.dist.jar"
TLA_SHA_KNOWN="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"   # last-verified 'latest' build
ALLOY_SHA="6b8c1cb5bc93bedfc7c61435c4e1ab6e688a242dc702a394628d9a9801edb78d"       # v6.2.0 (immutable)

sha256() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi; }

fetch() {  # fetch URL DEST
  [ -f "$2" ] || { echo "  fetching $(basename "$2") -> $2"; curl -fsSL -o "$2" "$1"; }
}

# D1: assert a literal substring is present in captured output; FAIL (set rc=1) if absent.
need() {  # need "<haystack>" "<needle>" "<description>"
  case "$1" in
    *"$2"*) : ;;
    *) echo "  FAIL  $3 — expected literal not found: '$2'"; rc=1 ;;
  esac
}

echo "== toolchain (cache: $CACHE) =="
fetch "$TLA_URL"   "$TLA_JAR"
fetch "$ALLOY_URL" "$ALLOY_JAR"

got=$(sha256 "$ALLOY_JAR")
if [ "$got" != "$ALLOY_SHA" ]; then
  echo "  FATAL: alloy.jar checksum $got != pinned $ALLOY_SHA (v6.2.0 is immutable — delete $ALLOY_JAR and re-fetch)" >&2
  exit 2
fi
echo "  OK    alloy.jar v6.2.0 checksum verified"
got=$(sha256 "$TLA_JAR")
if [ "$got" != "$TLA_SHA_KNOWN" ]; then
  echo "  NOTE  tla2tools.jar checksum $got != last-verified $TLA_SHA_KNOWN"
  echo "        ('latest' drifted; any recent TLC 2.x reproduces the same model-determined counts — proceeding)"
else
  echo "  OK    tla2tools.jar checksum matches last-verified build"
fi

rc=0

echo "== TLC — Pipeline.cfg (MaxFuel=2) — expect 853 generated / 408 distinct / depth 36, No error =="
set +e
TLC2_OUT=$("$JAVA" -XX:+UseParallelGC -cp "$TLA_JAR" tlc2.TLC \
  -metadir "$CACHE/tlc-states-2" -config formal/Pipeline.cfg formal/Pipeline.tla 2>&1)
tlc2_rc=$?
set -e
# Show the salient lines. D1: use "distinct states found" (not bare "distinct states") so the stray
# "because two distinct states had the same fingerprint:" caveat line no longer splices into the summary.
printf '%s\n' "$TLC2_OUT" \
  | grep -iE "[0-9]+ states generated|distinct states found|The depth of|branches of temporal properties|No error|Error:|violated" \
  | grep -vi "same fingerprint"
[ "$tlc2_rc" -ne 0 ] && rc=1
# D1: ASSERT the model-determined numbers + that temporal properties were actually checked (a cfg with
# no INVARIANT/PROPERTY still prints "No error", so "No error" alone is not sufficient).
need "$TLC2_OUT" "853 states generated"                              "TLC MaxFuel=2 states-generated count"
need "$TLC2_OUT" "408 distinct states found"                         "TLC MaxFuel=2 distinct-states count"
need "$TLC2_OUT" "The depth of the complete state graph search is 36" "TLC MaxFuel=2 search depth"
need "$TLC2_OUT" "branches of temporal properties"                   "TLC MaxFuel=2 temporal-property checking"
need "$TLC2_OUT" "No error has been found"                           "TLC MaxFuel=2 no-error verdict"
rm -rf "$CACHE/tlc-states-2" 2>/dev/null || true

if [ "$RUN_MAXFUEL32" -eq 1 ]; then
  echo "== TLC — MaxFuel=32 (temp cfg; shipped cfg stays 2) — expect 2923 / 1608 / depth 156, No error =="
  TMPCFG="$CACHE/Pipeline_maxfuel32.cfg"
  sed 's/CONSTANT MaxFuel = 2/CONSTANT MaxFuel = 32/' formal/Pipeline.cfg > "$TMPCFG"
  # D1: assert the substitution actually happened (a renamed/removed constant would silently leave MaxFuel=2).
  if ! grep -q "MaxFuel = 32" "$TMPCFG"; then
    echo "  FAIL  --maxfuel32 sed did not produce 'MaxFuel = 32' in the temp cfg (constant renamed?)"; rc=1
  fi
  set +e
  TLC32_OUT=$("$JAVA" -XX:+UseParallelGC -cp "$TLA_JAR" tlc2.TLC \
    -metadir "$CACHE/tlc-states-32" -config "$TMPCFG" formal/Pipeline.tla 2>&1)
  tlc32_rc=$?
  set -e
  printf '%s\n' "$TLC32_OUT" \
    | grep -iE "[0-9]+ states generated|distinct states found|The depth of|branches of temporal properties|No error|Error:|violated" \
    | grep -vi "same fingerprint"
  [ "$tlc32_rc" -ne 0 ] && rc=1
  need "$TLC32_OUT" "2923 states generated"                              "TLC MaxFuel=32 states-generated count"
  need "$TLC32_OUT" "1608 distinct states found"                         "TLC MaxFuel=32 distinct-states count"
  need "$TLC32_OUT" "The depth of the complete state graph search is 156" "TLC MaxFuel=32 search depth"
  need "$TLC32_OUT" "No error has been found"                            "TLC MaxFuel=32 no-error verdict"
  rm -f "$TMPCFG"; rm -rf "$CACHE/tlc-states-32" 2>/dev/null || true
fi

echo "== Alloy — WorkGraph.als + Amendment.als (headless SAT4J) — expect 8/8 commands as-expected =="
OUT=$(mktemp -d)
"$JAVAC" -cp "$ALLOY_JAR" -d "$OUT" formal/AlloyRun.java
set +e
# D1: pass the EXPECTED total command count (8) so a stripped/implicit-Default .als FAILs the count check.
ALLOY_OUT=$("$JAVA" -Djava.awt.headless=true -cp "$ALLOY_JAR:$OUT" AlloyRun 8 formal/WorkGraph.als formal/Amendment.als 2>&1)
arc=$?
set -e
printf '%s\n' "$ALLOY_OUT" | grep -E "\[OK\]|\[FAIL\]|\[WARN\]|SUMMARY|=="
rm -rf "$OUT"
[ "$arc" -ne 0 ] && rc=1
# D1: require the literal 8/8 summary (redundant with the driver's exit code — belt-and-braces).
need "$ALLOY_OUT" "SUMMARY: 8/8 commands as-expected" "Alloy 8/8 commands as-expected"

echo "== summary =="
if [ "$rc" -eq 0 ]; then echo "RESULT: PASS (TLC + Alloy machine-checks green; numbers asserted)"; else echo "RESULT: FAIL"; fi
exit "$rc"
