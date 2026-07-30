# Fixture: i46_no_converged_key (GREEN over-fire control — the ADOPTION boundary; spec §4.1/§4.4 P4-G2)

Phase `DONE`, all five gates true including `signoff_confirmed: true`; `units/U01/verify.json`
`verdict: "PASS"` with **NO `converged` key at all**, but `verify_rounds: 3` present.

PROVES two separable things:
1. An ABSENT `converged` never arms P4. A falsiness-based implementation
   (`if not v.get("converged")`) treats the missing key as `False` and FAILs this fixture — which is
   exactly the point. This is what keeps P4 archive-silent except on runs that POSITIVELY wrote the
   field.
2. P4 must not key on `verify_rounds`. `verify_rounds: 3` is the round CAP reached; §4.1 says P4 does
   NOT read `verify_rounds` as a condition (requiring the cap would narrow the predicate on
   unmeasured grounds) and may name it only in a FAIL's detail. An implementation that arms on
   `verify_rounds == 3` fires here.
It also pins the zero-adoption emission rule of §4.2: with no `converged` anywhere, P4 emits
**nothing** — not even its positive assertion (the I19/I20 zero-adoption precedent).

Pinned substring is `RESULT: PASS`.

DOES NOT COVER: `converged` present as `0`, `""` or `null` — §4.1 says none of these arm P4, and no
fixture ships them (they are schema-invalid as booleans, so they would be dropped upstream anyway,
which is itself an untested assumption).

