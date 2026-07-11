#!/usr/bin/env bash
# run_formal.sh — one-command reproduction of the TLA+/Alloy machine-checks.
#
# The two toolchain jars are BUILD tools, not skill files: they are FETCHED to a cache dir (default
# /tmp), NOT vendored into the repo — the Alloy dist.jar bundles a research-only SAT solver (Lingeling)
# and LGPL SAT4J, so it is deliberately not committed (see formal-models.md + this repo's policy). This
# script fetches them (checksum-verified), compiles the vendored formal/AlloyRun.java driver, and runs:
#   * TLC on formal/Pipeline.cfg (MaxFuel=2, the shipped ceiling)  -> expect 853/408/depth 36, No error
#   * TLC on a TEMP MaxFuel=32 cfg (with --maxfuel32; cfg stays 2) -> expect 2,923/1,608/depth 156
#   * the Alloy driver on WorkGraph.als + Amendment.als (headless) -> expect 8/8 commands as-expected
# Nothing is written into the repo. Exit non-zero if any check fails or a jar checksum mismatches hard.
#
# Usage: run_formal.sh [--maxfuel32] [--cache DIR]
# Env:   JAVA_HOME (optional; else `java`/`javac` on PATH). DAG_FORMAL_CACHE overrides the jar cache dir.
set -eu

CACHE="${DAG_FORMAL_CACHE:-/tmp}"
RUN_MAXFUEL32=0
for arg in "$@"; do
  case "$arg" in
    --maxfuel32) RUN_MAXFUEL32=1 ;;
    --cache) shift; CACHE="${1:-$CACHE}" ;;
    --cache=*) CACHE="${arg#--cache=}" ;;
    -h|--help) echo "usage: run_formal.sh [--maxfuel32] [--cache DIR]"; exit 0 ;;
  esac
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
"$JAVA" -XX:+UseParallelGC -cp "$TLA_JAR" tlc2.TLC -config formal/Pipeline.cfg formal/Pipeline.tla 2>&1 \
  | grep -iE "states generated|distinct states|depth of|No error|Error|violated"
[ "${PIPESTATUS[0]:-1}" -ne 0 ] && rc=1
set -e
rm -rf states 2>/dev/null || true

if [ "$RUN_MAXFUEL32" -eq 1 ]; then
  echo "== TLC — MaxFuel=32 (temp cfg; shipped cfg stays 2) — expect 2,923 / 1,608 / depth 156, No error =="
  TMPCFG="$CACHE/Pipeline_maxfuel32.cfg"
  sed 's/CONSTANT MaxFuel = 2/CONSTANT MaxFuel = 32/' formal/Pipeline.cfg > "$TMPCFG"
  set +e
  "$JAVA" -XX:+UseParallelGC -cp "$TLA_JAR" tlc2.TLC -config "$TMPCFG" formal/Pipeline.tla 2>&1 \
    | grep -iE "states generated|distinct states|depth of|No error|Error|violated"
  [ "${PIPESTATUS[0]:-1}" -ne 0 ] && rc=1
  set -e
  rm -f "$TMPCFG"; rm -rf states 2>/dev/null || true
fi

echo "== Alloy — WorkGraph.als + Amendment.als (headless SAT4J) — expect 8/8 commands as-expected =="
OUT=$(mktemp -d)
"$JAVAC" -cp "$ALLOY_JAR" -d "$OUT" formal/AlloyRun.java
set +e
"$JAVA" -Djava.awt.headless=true -cp "$ALLOY_JAR:$OUT" AlloyRun formal/WorkGraph.als formal/Amendment.als 2>&1 \
  | grep -E "\[OK\]|\[FAIL\]|SUMMARY|=="
arc=${PIPESTATUS[0]:-1}
set -e
rm -rf "$OUT"
[ "$arc" -ne 0 ] && rc=1

echo "== summary =="
if [ "$rc" -eq 0 ]; then echo "RESULT: PASS (TLC + Alloy machine-checks green)"; else echo "RESULT: FAIL"; fi
exit "$rc"
