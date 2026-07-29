I42-5, the ABSOLUTE-path arm, in ISOLATION and OFF the transient phase. A single `inputs_reviewed`
element, an absolute path with a recorded digest, at `P7_DISAGREEMENT_GATE`. Integrity is not decidable
from emitted artifacts, so it is an exit-neutral NOTE and the success line counts **0** digested inputs.
Expected exit 0 on `N-I42 (undigestable evidence`.

Why it exists separately from `digest_outofrun_note`: that fixture carries THREE elements, one absolute and
one `..`-escaping, and it sits at `P6_EXECUTE_VERIFY`. Treat the absolute path as run-relative (the
`I42-5-abs` ablation) and it gets re-hashed against `/etc/hosts` — whose bytes do not match the recorded
digest — but at P6 with no `units/<uid>/` prefix the I42-3 run-root fall-back downgrades that to a NOTE,
while the surviving `..` element keeps printing the required `undigestable` NOTE. So the fixture stayed
green and the arm was MASKED by its own sibling element. Isolating the absolute path and moving it off P6
removes both masks: under the same ablation this fixture re-hashes, mismatches, is outside the transient
window and FAILs — and if `/etc/hosts` is absent on the validating machine it FAILs as dangling evidence
(I42-4) instead. Either way exit 1, so the arm is pinned at suite level rather than by a harness override.
