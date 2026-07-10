module Amendment
/*
 * BGA design-time theorem: amending a wave-layered graph by adding units strictly
 * above their dependencies — while never rewiring the frozen old graph (I17) —
 * preserves wave layering, and hence acyclicity (WorkGraph.als LayeringImpliesAcyclic).
 * `Old` abstracts the frozen prefix; Unit - Old are amendment-added units.
 * add_edges into unexecuted OLD units is NOT modeled here (covered at runtime by the
 * full-graph I3 + I3b re-check per revision) — noted honestly, not hidden.
 */
sig Unit { depends: set Unit, wave: one Int }
sig Old in Unit {}

pred OldLayered   { all u: Old | u.wave >= 1 and (all d: u.depends & Old | d.wave < u.wave) }
pred FrozenOld    { all u: Old | u.depends in Old }                     // I17: old edges untouched, none point at new units
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
