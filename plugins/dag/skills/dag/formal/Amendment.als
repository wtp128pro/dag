module Amendment
/*
 * BGA design-time theorem: amending a wave-layered graph by adding units strictly
 * above their dependencies — while never rewiring the frozen old graph — preserves
 * wave layering, and hence acyclicity (WorkGraph.als LayeringImpliesAcyclic).
 * `Old` abstracts the frozen prefix; Unit - Old are amendment-added units.
 * SCOPE / D10 honesty note (comments only): this model proves the ADD-UNITS layering theorem.
 * Its runtime counterpart at the validator is NOT a single check but the composite:
 *   - I17 frozen-content ANCHOR (WP4): every EXECUTED unit's graph entry still matches its
 *     immutable brief.json on title/wave/deps/persona/tags/acceptance_criteria — this is what
 *     mechanically forbids a rewire/re-wave of the frozen prefix (the intent `FrozenOld` abstracts);
 *   - I17 reconciliation (WP1) + the full-graph I3/I3b/I3c re-check per revision.
 * Deliberately NOT modeled here (covered at runtime, not hidden): add_edges into unexecuted OLD
 * units, and the retirement semantics of split_unit / cancel_unit (which remove Old units — the
 * validator discharges those via I17 reconciliation + retirement disjointness, WP1).
 */
sig Unit { depends: set Unit, wave: one Int }
sig Old in Unit {}

pred OldLayered   { all u: Old | u.wave >= 1 and (all d: u.depends & Old | d.wave < u.wave) }
pred FrozenOld    { all u: Old | u.depends in Old }                     // old edges stay within Old (none point at new units); the frozen-prefix INTENT the WP4 I17 content-anchor + I3/I3b re-check discharge at runtime (D10)
pred NewAboveDeps { all u: Unit - Old | u.wave >= 1 and (all d: u.depends | d.wave < u.wave) }

assert AmendPreservesLayering {
  (OldLayered and FrozenOld and NewAboveDeps)
    => (all u: Unit | all d: u.depends | d.wave < u.wave)
}
assert AmendPreservesAcyclic {
  (OldLayered and FrozenOld and NewAboveDeps) => no (^depends & iden)
}
check AmendPreservesLayering for 7 but 5 Int
check AmendPreservesAcyclic  for 7 but 5 Int

// Non-vacuity: a real amendment exists — new units, one consuming an old unit, acyclic.
pred AmendWitness {
  some Old
  some Unit - Old
  some ((Unit - Old).depends & Old)
  OldLayered and FrozenOld and NewAboveDeps
}
run AmendWitness for 6 but 5 Int
