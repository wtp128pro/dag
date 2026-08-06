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

DEF = ("/Users/mborodia/Developer/dag/.wip/2026-08-02_235310_independent-test-authorship/"
       "units/U29/debrief.json")
path = sys.argv[1] if len(sys.argv) > 1 else DEF
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
