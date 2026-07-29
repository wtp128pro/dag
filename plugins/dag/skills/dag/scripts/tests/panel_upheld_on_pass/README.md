I41-3, the `upheld`-on-PASS arm. A panel member records a `major`, the adjudication names it with a
disposition of `upheld` and a non-blank rationale — and the top-level verdict is still PASS. `upheld`
is deliberately NOT in `_I41_EXCUSED`: an upheld major contradicts the verdict it rides on, which is
the exact laundering I41-3 exists to surface (spec 2.4, "A `disposition` of `upheld` on a PASS => FAIL").

Isolation: I41-1 (adjudication present), I41-2 (the dissenter carries its defect), I41-4a (enum +
rationale), I41-4b (the disposition resolves), I41-4c/d/e (no re-poll), I41-5 (no downgrade) and I41-6
(not an escalation) are all satisfied. The `N-I41 (dissent withdrawn without re-poll)` NOTE also fires
and is exit-neutral by construction. Without the `upheld`-excluded semantics — i.e. with "upheld" added
to `_I41_EXCUSED` — this fixture goes GREEN, which is what it pins. Exit 1 on `unexplained major`.
