#!/usr/bin/env python3
"""mirror_check.py [expect_plugin] [expect_catalog] — do all SIX version mirrors agree?

CLAUDE.md names six locations that must move together. This extracts each from its own file and
asserts agreement; with arguments it also asserts the expected values.

  rc 0  all six agree (and match the expectation, if given)
  rc 1  a mirror disagrees
  rc 2  a mirror could not be EXTRACTED — nothing measured, NOT a pass

FALSIFIED BEFORE FREEZING (orchestrator, wave 8): rc 0 on the live tree (1.12.1 / 1.0.16);
rc 1 against a copy with plugin.json bumped alone; rc 1 against the live tree with a wrong
expectation; rc 2 against a copy whose `Current version:` line is deleted.

NOT WIRED into `run_tests.sh` / `expectations.tsv`, deliberately and stated rather than left
implicit: that harness adjudicates `validate_run.py` against frozen run fixtures, whereas this
instrument reads the LIVE repo's release metadata, so wiring it would make the fixture suite's
verdict depend on the working tree's version state. It is a release-engineering instrument to be
run by hand at a bump (`CLAUDE.md`, "Versioning / releases - keep every mirror in sync"). Adds no
pipeline behaviour.
"""
import json, os, re, sys
# Repo root is derived from this file's own location (scripts/ -> dag/ -> skills/ -> dag/ ->
# plugins/ -> repo root), so the instrument is reproducible from any clone; argv[3] overrides it.
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[3] if len(sys.argv) > 3 else os.path.abspath(
    os.path.join(_HERE, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir))
def rd(p): return open(os.path.join(ROOT, p)).read()
found, missing = {}, []
try:
    found["1 plugin.json"] = json.loads(rd("plugins/dag/.claude-plugin/plugin.json"))["version"]
except Exception: missing.append("1 plugin.json")
m = re.search(r"^##\s*\[?v?([0-9]+\.[0-9]+\.[0-9]+)", rd("plugins/dag/CHANGELOG.md"), re.M)
found["2 plugin CHANGELOG"] = m.group(1) if m else missing.append("2 plugin CHANGELOG")
m = re.search(r"Current version:\s*\**([0-9]+\.[0-9]+\.[0-9]+)", rd("plugins/dag/README.md"))
found["3 plugin README"] = m.group(1) if m else missing.append("3 plugin README")
try:
    mk = json.loads(rd(".claude-plugin/marketplace.json"))
    found["4a marketplace top"] = mk["version"]
    found["4b marketplace entry"] = mk["plugins"][0]["version"]
except Exception: missing.append("4 marketplace.json")
_v = None
for _l in rd("README.md").split("\n"):
    if _l.startswith("|") and "dag" in _l:
        _c = [c.strip() for c in _l.split("|")]
        _hit = [c for c in _c if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", c)]
        if _hit:
            _v = _hit[0]; break
if _v: found["5 root README"] = _v
else: missing.append("5 root README")
m = re.search(r"^##\s*\[?v?([0-9]+\.[0-9]+\.[0-9]+)", rd("CHANGELOG.md"), re.M)
found["6 root CHANGELOG"] = m.group(1) if m else missing.append("6 root CHANGELOG")
for k, v in found.items(): print("  %-22s %s" % (k, v))
if missing:
    print("FAIL: could not extract %s — nothing measured" % missing); sys.exit(2)
plug = {found[k] for k in found if "marketplace top" not in k and "root CHANGELOG" not in k}
cat = {found["4a marketplace top"], found["6 root CHANGELOG"]}
bad = []
if len(plug) != 1: bad.append("plugin mirrors disagree: %s" % sorted(plug))
if len(cat) != 1: bad.append("catalog mirrors disagree: %s" % sorted(cat))
if len(sys.argv) > 1 and sys.argv[1] not in plug: bad.append("plugin != expected %s" % sys.argv[1])
if len(sys.argv) > 2 and sys.argv[2] not in cat: bad.append("catalog != expected %s" % sys.argv[2])
for b in bad: print("  MISMATCH", b)
sys.exit(1 if bad else 0)
