module WorkGraph
/*
 * Design-time STRUCTURAL model of the dag work-graph (proof layer on top
 * of the runtime validator, scripts/validate_run.py).
 *
 * Mirrors:
 *   - schemas/graph.schema.json  : units, dependency edges, waves, V_tag
 *                                  -> PROPERTY 3  DAG acyclicity (validator I3).
 *   - schemas/verify.schema.json : verifier independence, executor_reasoning_seen
 *                                  == false (const) -> PROPERTY 4 (validator I1/I1b).
 *
 * Edge semantics: `d in u.depends`  <=>  graph edge {from = d, to = u}
 * ("u consumes d"), i.e. d must be produced before u.
 *
 * TOOL-STATUS: the TLA+ companion (Pipeline.tla) is machine-checked by TLC, and this
 * Alloy model is machine-checked by Alloy 6 (Kodkod / bundled SAT4J, headless): all four
 * `check`s report NO counterexample and `run WitnessGraph` finds an instance. DAG acyclicity
 * also holds structurally via the wave-layering fact (WaveLayered) — see the
 * LayeringImpliesAcyclic theorem below. (Reproduce: open in the Alloy Analyzer and Execute All,
 * or drive the Alloy Java API with the default SAT4J solver. The `for 7 but 5 Int` scope on the
 * first two checks bounds `Persona`/`Verifier`, which `Unit.executor` makes reachable.)
 */

sig Persona {}                      // an executor/verifier identity (maker or checker)

sig Unit {
  depends : set Unit,               // this unit's dependencies (edges into it)
  wave    : one Int,                // topological layer index (schema: waves start at 1)
  executor: one Persona             // the persona that PRODUCED this unit (the maker)
}

sig Verifier {
  persona      : one Persona,       // the checker's identity
  checked      : set Unit,          // units this verifier adjudicated
  reasoningSeen: set Unit           // units whose executor chain-of-thought it read (I1: empty)
}

// ---- structural facts (the invariants the schema/validator impose) ----

// You can only conceivably have seen the reasoning of a unit you actually checked.
fact SeenSubsetChecked { all v : Verifier | v.reasoningSeen in v.checked }

// I1 / verify.schema executor_reasoning_seen : {const: false}. Independence is a
// STRUCTURAL invariant here, not a mere runtime flag: no verifier reads any
// executor's reasoning (the relation is forced empty).
fact Independence { no reasoningSeen }

// I1b (maker != checker): a unit's verifier is never that unit's own executor.
fact MakerNotChecker { all v : Verifier, u : v.checked | v.persona != u.executor }

// ---- predicates used as hypotheses ----

// A wave assignment is a valid topological LAYERING iff every dependency lands in a
// strictly earlier wave than its dependent (schema `waves` + validator I3).
pred WaveLayering { all u : Unit | all d : u.depends | d.wave < u.wave }
pred PositiveWaves { all u : Unit | u.wave >= 1 }

// STRUCTURAL FACT — the Phase-4 wave-assignment discipline (each unit gets a wave
// strictly above its dependencies) that the decomposition produces and the validator's
// fail-closed I3 relies on. Without this, `depends` is an UNCONSTRAINED `set Unit`, so a
// self-loop (u in u.depends) is a valid instance and the standalone `Acyclic` assert
// below would have a COUNTEREXAMPLE. With it, acyclicity is EARNED from the layering
// (LayeringImpliesAcyclic), not asserted by fiat — the check reports no counterexample.
fact WaveLayered { WaveLayering and PositiveWaves }

// ================= PROPERTY 3 : DAG ACYCLICITY (STRUCTURAL) =================
// The dependency relation is acyclic: no unit reaches itself via >=1 edges.
assert Acyclic { no (^depends & iden) }

// Theorem: a valid topological wave-layering is SUFFICIENT for acyclicity — this
// is exactly what the validator's wave check buys (I3). If a check finds no
// counterexample in scope, the implication holds up to that scope.
assert LayeringImpliesAcyclic {
  (WaveLayering and PositiveWaves) => no (^depends & iden)
}

// ============ PROPERTY 4 : VERIFIER INDEPENDENCE (STRUCTURAL) ============
// No verifier ever saw the executor reasoning of any unit it checked, and it is
// never the unit's own maker. (Given the facts above, these are structurally
// imposed invariants shown CONSISTENT by the WitnessGraph run below, not derived
// theorems — see formal-models.md ADMIT.)
assert VerifierBlind        { no reasoningSeen }
assert DistinctMakerChecker { all v : Verifier, u : v.checked | v.persona != u.executor }

// ---- checks (bounded verification; scopes chosen well above the property arity) ----
check Acyclic                for 7 but 5 Int
check LayeringImpliesAcyclic for 7 but 5 Int
check VerifierBlind          for 7 Unit, 5 Verifier, 5 Persona, 5 Int
check DistinctMakerChecker   for 7 Unit, 5 Verifier, 5 Persona, 5 Int

// Non-vacuity: an INDEPENDENT, acyclic, multi-unit, actually-verified instance
// EXISTS (guards against an over-constrained model that satisfies everything
// vacuously). Expect: instance found.
pred WitnessGraph {
  some depends            // at least one real dependency edge
  some Verifier.checked   // at least one verification actually happens
  no (^depends & iden)    // and it is acyclic
}
run WitnessGraph for exactly 4 Unit, exactly 2 Verifier, exactly 3 Persona, 5 Int
