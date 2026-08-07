# I48 counterfactual family — the predicate is shown to FIRE, and the two silences are told apart

Three fixtures, one point: **I48 is not dead code that merely fails to fire**, and **a green run is
not evidence that it works**. The family is the DoD's "deliberately constructed counterfactual run
that DOES carry `case_set`", plus the two controls without which the counterfactual proves nothing.

| fixture | `fsm-state.validator_version` | `C2.non_vacuity` | rc | I48 row |
|---|---|---|---|---|
| `i48_counterfactual_fires` | `1.13.0` | **partial** — covers `required_observations`, omits `forbidden_observations` | **1** | **FIRES** (I48-7 multiset row) |
| `i48_counterfactual_suppressed` | `1.12.1` | partial (artifacts **byte-identical** to `_fires`) | 0 | silent — *suppressed* |
| `i48_counterfactual_green` | `1.13.0` | complete | 0 | silent — *armed and conforming* |

`_fires` and `_suppressed` differ in **exactly one artifact**: `fsm-state.json` (the stamp, and the
cosmetic `run_dir` label). `units/U01/{brief,debrief,verify}.json` are byte-identical between them —
`diff -rq` names only `fsm-state.json`. So the verdict move from FAIL to PASS is attributable to the
version gate and to nothing else.

## Why `_suppressed` and `_green` are BOTH needed

`_I48_SHIP = "1.13.0"` was set deliberately **above** the `1.12.1` stamp this repo carried when
this fixture was written (`validate_run.py`, the VERSION GATE comment); **1.13.0 shipped the
contract**, so the stamp has caught up to the gate. The arm still fires on **zero** archived runs —
every one of them is stamped below `1.13.0` — but it **is** armed for any run scaffolded or
`--restamp`ed at `1.13.0` or above. That is
the archive-safety mechanism — and it is also the trap: **a suppressed arm produces exactly the same
`RESULT: PASS` as a correct run.** Four measurement attempts in the authoring run were voided by
reading a 1.12.1 green as evidence.

The only on-the-wire discriminator is the **N-I45 version-skew NOTE**:

- `_suppressed` (rc 0) prints `suppressed 1 version-gated arm(s) whose other preconditions HELD:
  ['I48-T1']` — the arm was **switched off**; the partly-vacuous C2 row is sitting right there,
  unjudged.
- `_green` (rc 0) prints **no N-I45 note at all** — every gated arm is armed, so the silence is
  earned by the artifact, not bought by the stamp.

Their `expectations.tsv` pins are chosen to enforce precisely that: `_suppressed` pins the skew
string positively, `_green` pins it **negatively** (`!N-I45 version-skew visibility`). A future
change that raised `_green`'s silence to a *suppressed* silence would flip that negative pin red.

## Reproduce

```
cd <repo> && for f in i48_counterfactual_fires i48_counterfactual_suppressed i48_counterfactual_green; do
  python3 plugins/dag/skills/dag/scripts/validate_run.py plugins/dag/skills/dag/scripts/tests/$f \
    --schemas "$PWD/plugins/dag/skills/dag/schemas" --quiet; echo "rc=$?"; done
```

`--schemas` is **not optional** in any harness that copies `validate_run.py` out of the tree: the
copy resolves `schemas/` next to itself, so a stale `$TMPDIR/schemas` snapshot silently supplies the
schemas and can turn a whole fixture family green on one machine only. Measured both ways — see the
authoring unit's debrief (`U10`).

## Base

Cloned from `digest_ok` (the only green fixture that stays clean when the stamp is raised to
`1.13.0`: every other version-gated arm — I27/I35/I38/I39/I41/I42 — is already satisfied there).
`verify.json`'s `inputs_reviewed[].sha256`/`bytes` were recomputed for the edited brief/debrief, so
I42 stays green and the I48 row is the *only* problem in `_fires`.

The `case_set` itself is **conforming**: two entries, one per acceptance criterion, `check_form`
`command`, `evidence_tier` `executable` (at the floor), `requirement_ref_none_reason` on both (the
base brief carries no `dod_refs`/`non_goal_refs`). The firing is caused by the *discharge*, not by a
malformed case set — that is what distinguishes this family from the `case_set_none_reason` fixture.
