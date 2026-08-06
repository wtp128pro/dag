#!/usr/bin/env python3
"""u29_baseline_check.py — make U29's C2 ("'still green' is a COMPARISON") MECHANICAL.

A locator check into an executor-authored artifact is satisfiable by construction; what
this instrument buys is that the check can still return a DIFFERENT ANSWER — remove any
one of the four things the comparison needs and it goes red, naming which one.

Four predicates over units/U29/debrief.json:

  P1  the baseline is CITED to where it is recorded (RESUME.md line ref), not asserted
  P2  the PRE-change side is present with its figures  (RESULT: PASS, PASS 8/NOTE 1/FAIL 0)
  P3  the POST-change side is present with its figures, executed now
  P4  the pre-change side is INDEPENDENTLY re-measured at the run's base commit f547aef,
      so the cited baseline is corroborated rather than trusted

  rc 0  all four hold          rc 1  one or more missing (each named)
"""
import json, re, sys, os

# PORTABILITY (U17/C5). This instrument used to DEFAULT to an absolute path inside one
# particular checkout, under the gitignored working-run tree. That default was worse than
# unhelpful: run from a clone it read the ORIGINAL repository and reported on a file the
# clone did not contain, so it could return a green that said nothing about the tree it
# was invoked in. There is no correct default here — the subject is a run artifact, the
# working-run tree is gitignored, and no clone contains one. So the path is REQUIRED, and
# its absence is UNMEASURED (rc 2), never a pass. The other u29_* fixtures need a repo
# root and derive it from __file__; this one needs no root at all, only its argument.
if len(sys.argv) < 2:
    print("RESULT: UNMEASURED (no debrief path given)")
    print("  usage: u29_baseline_check.py <path-to-units/U29/debrief.json>")
    sys.exit(2)
path = sys.argv[1]
if not os.path.exists(path):
    print("RESULT: UNMEASURED (no such debrief: %s)" % path)
    sys.exit(2)
blob = open(path).read()

P = [
    ("P1 baseline CITED to its record",   r"RESUME\.md:6[12]"),
    ("P2 PRE-change side + figures",      r"pre-change[^\n]{0,400}?PASS 8|PASS 8[^\n]{0,400}?pre-change"),
    ("P3 POST-change side + figures",     r"post-change[^\n]{0,400}?PASS 8|PASS 8[^\n]{0,400}?post-change"),
    ("P4 pre-change RE-MEASURED at base", r"f547aef"),
]
bad = []
for name, rx in P:
    hit = re.search(rx, blob, re.S | re.I)
    print("  %-38s %s" % (name, "[ok ]" if hit else "[RED]"))
    if not hit:
        bad.append(name)
print("RESULT: %s" % ("PASS" if not bad else "FAIL (%s)" % "; ".join(bad)))
sys.exit(0 if not bad else 1)
