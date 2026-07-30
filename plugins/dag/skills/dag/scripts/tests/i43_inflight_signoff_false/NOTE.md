# Fixture: i43_inflight_signoff_false (GREEN — second carve-out variant; SIGNED_OFF is IDENTITY to True)

Identical to `i43_inflight_before_signoff` except `gates.signoff_confirmed` is PRESENT and `false`.

PROVES two things at once:
1. `SIGNED_OFF := gates.get("signoff_confirmed") is True` is an IDENTITY test (§0.2), so a present-
   and-`false` flag does NOT expire the carve-out. An implementation using `"signoff_confirmed" in
   gates` (presence) instead of identity-to-`True` FAILs this row.
2. The `P1-d` NOTE arm actually emits: the pinned substring is the NOTE line itself, so a
   carve-out implemented as `continue` (silently, with no NOTE) fails the row rather than passing it
   — closing R4 (silent-skip domains) on the carve-out branch specifically.

EXPECTED: exit 0 AND stdout contains `N-I43 verification currency (in-flight)` under the
harness's non-`--quiet` invocation.

DOES NOT COVER: truthy-but-not-`True` values (`1`, `"true"`, a non-empty dict) — an implementation
using `bool(...)` still passes this row; the `--quiet` posture of the NOTE (§1.6 P1-G2 does not
require the NOTE to survive `--quiet`, unlike N-I45's §3.3).

