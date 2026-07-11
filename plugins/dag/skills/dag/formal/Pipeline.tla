------------------------------- MODULE Pipeline -------------------------------
(*****************************************************************************)
(* Design-time formal model of the dag pipeline (proof layer that     *)
(* sits ON TOP of the runtime validator, scripts/validate_run.py).            *)
(*                                                                            *)
(* Source of truth mirrored here:                                             *)
(*   - references/state-machine.md  : phase/gate FSM, guards G-*, invariants  *)
(*                                    I1-I19 (incl. I1b/I3b/I3c/I17/I18/I19    *)
(*                                    + I-dod); TLC checks the structural/      *)
(*                                    temporal subset (gate ordering, loop      *)
(*                                    bound, variant, fuel quiescence).         *)
(*   - references/self-learning-loops.md : the executor<->verifier bounded     *)
(*                                    loop (U05 states Q, table 1.3, variant). *)
(*                                                                            *)
(* Two machines are composed over one variable tuple `vars`:                  *)
(*   (A) PHASE machine  -> SAFETY   property GateOrdering                      *)
(*   (B) LOOP  machine  -> LIVENESS property Termination (variant 2-retries)   *)
(* They are linked at exactly ONE point: the loop reaching DONE satisfies the  *)
(* P6 "all units passed" gate (transition T9 of state-machine.md).            *)
(*                                                                            *)
(* TOOL-STATUS: this spec IS TLC-checkable and was MACHINE-CHECKED (TLC 2.19,   *)
(* JDK 25 via `/usr/libexec/java_home`): TLC explored the full state space      *)
(* (408 distinct states, queue empty) with no error, so every INVARIANT (incl.  *)
(* FuelBound) and BOTH the Termination and Quiesce PROPERTIES hold; the          *)
(* hand-proofs carry the same results. The                                       *)
(* reproducible transcript + the one-command check plan are in                  *)
(* references/formal-models.md. (Do NOT re-assert "no JRE/TLC present": false.)  *)
(*****************************************************************************)
EXTENDS Naturals

CONSTANT MaxRetries          \* schema ceiling = 2 (fsm-state.schema.json loop.retries.maximum)
ASSUME MaxRetries \in Nat /\ MaxRetries >= 1

CONSTANT MaxFuel             \* Bounded Graph Amendments: fuel ceiling (fsm-state.schema expansion,
                             \* schema max 32; the model checks a small value, cfg MaxFuel = 2).
ASSUME MaxFuel \in Nat

(* ------------------------- (A) PHASE machine domain ---------------------- *)
SpinePhases == {"P0","P1","P2","P3","P4","P5","P6","P8"}   \* the linear happy path
AllPhases   == SpinePhases \cup {"P7","DONE"}              \* P7 = as-needed excursion

(* Happy-path successor (T1,T2,T3,T5,T6,T8,T9,T12). Note P6 -> P8 (skips P7). *)
Succ(p) == CASE p = "P0" -> "P1"
             [] p = "P1" -> "P2"
             [] p = "P2" -> "P3"
             [] p = "P3" -> "P4"
             [] p = "P4" -> "P5"
             [] p = "P5" -> "P6"
             [] p = "P6" -> "P8"
             [] p = "P8" -> "DONE"

(* ------------------------- (B) LOOP machine domain ----------------------- *)
LoopStates == {"EXECUTE","VERIFY","ADJUDICATE","RETRY","ESCALATE","DONE"}
Verdicts   == {"NONE","PASS","FAIL","DISAGREE"}

VARIABLES
  phase,     \* current pipeline phase                                  (A)
  gate,      \* [SpinePhases -> BOOLEAN] exit-gate flags, MONOTONE       (A)
  lstate,    \* loop substate                                           (B)
  retries,   \* loop retry counter, 0..MaxRetries                       (B)
  verdict,   \* last verifier verdict                                   (B)
  fuel       \* Bounded Graph Amendments budget, 0..MaxFuel, MONOTONE-DECREASING (C)

vars == <<phase, gate, lstate, retries, verdict, fuel>>

(* The well-founded variant of the U05 termination proof: V = MaxRetries - retries. *)
V == MaxRetries - retries

TypeOK ==
  /\ phase   \in AllPhases
  /\ gate    \in [SpinePhases -> BOOLEAN]
  /\ lstate  \in LoopStates
  /\ retries \in 0..MaxRetries
  /\ verdict \in Verdicts
  /\ fuel    \in 0..MaxFuel

Init ==
  /\ phase   = "P0"
  /\ gate    = [p \in SpinePhases |-> FALSE]
  /\ lstate  = "EXECUTE"
  /\ retries = 0
  /\ verdict = "NONE"
  /\ fuel    = MaxFuel

-------------------------------------------------------------------------------
(* (A) PHASE machine actions. UNFAIR by design: human / as-needed gates may     *)
(* stall forever (T4 blocking on open ambiguity, T7 re-split, an unresolved P7).*)
(* => NO top-level liveness is claimed; the phase machine is checked for SAFETY  *)
(* only. This is the honest boundary: a human gate has no termination guarantee. *)

(* Complete phase p's exit gate (its work + any human confirmation done).       *)
(* P6's gate is NOT settable here; it is established ONLY by the loop (LinkP6).  *)
Complete(p) ==
  /\ phase = p
  /\ p /= "P6"
  /\ gate[p] = FALSE
  /\ gate' = [gate EXCEPT ![p] = TRUE]
  /\ UNCHANGED <<phase, lstate, retries, verdict, fuel>>

(* T9 link: the loop finishing (DONE) satisfies the P6 "all units passed" gate.  *)
(* Models a single representative unit; the multi-unit gate is the conjunction   *)
(* over units, which is uniform in this argument (see formal-models.md).         *)
LinkP6 ==  \* spec: T9
  /\ phase = "P6"
  /\ lstate = "DONE"
  /\ gate["P6"] = FALSE
  /\ gate' = [gate EXCEPT !["P6"] = TRUE]
  /\ UNCHANGED <<phase, lstate, retries, verdict, fuel>>

(* Advance along the happy-path spine, guarded by the source phase's exit gate.  *)
Advance(p) ==  \* spec: T1 T2 T3 T5 T6 T8 T12 (parametric; Complete(p) sets the exit gate this advances past)
  /\ phase = p
  /\ p \in SpinePhases
  /\ gate[p] = TRUE
  /\ phase' = Succ(p)
  /\ UNCHANGED <<gate, lstate, retries, verdict, fuel>>

(* T10: an ESCALATE opens the as-needed Phase-7 gate (P6 -> P7), from EITHER origin: *)
(* a DISAGREE (LT6) OR a retries-exhausted FAIL (LT5: verdict=FAIL at retries=Max).  *)
(* Both are `lstate = "ESCALATE"`; the guard admits both verdicts, matching the prose *)
(* (state-machine.md §1a: BOTH ESCALATE origins route to P7). BRK-11 fix — previously  *)
(* the guard was `verdict = "DISAGREE"` only, so a FAIL-origin ESCALATE stuttered in P6 *)
(* forever and could never reach P7 (the probe P7OnlyViaDisagree held; now it fails).  *)
ToEscalate ==  \* spec: T10
  /\ phase = "P6"
  /\ lstate = "ESCALATE"
  /\ verdict \in {"DISAGREE", "FAIL"}
  /\ phase' = "P7"
  /\ UNCHANGED <<gate, lstate, retries, verdict, fuel>>

(* T11: the user resolves the disagreement; control returns to P6 (never forward,*)
(* so the excursion can never bypass a downstream gate).                         *)
Resolve ==  \* spec: T11
  /\ phase = "P7"
  /\ phase' = "P6"
  /\ UNCHANGED <<gate, lstate, retries, verdict, fuel>>

\* spec-unmodeled: T4 T7 — intentionally unmodeled self-loops (unfair stutter): T4 (P2 blocking on
\* open ambiguity) and T7 (P4 re-split) are UNFAIR self-loops with no modeling action. (D12: retagged
\* from `\* spec:` so SC7 reports them as intentionally-unmodeled rather than counting a comment as a
\* modeled action.)
PhaseNext ==
  \/ \E p \in SpinePhases : Complete(p)
  \/ LinkP6
  \/ \E p \in SpinePhases : Advance(p)
  \/ ToEscalate
  \/ Resolve

-------------------------------------------------------------------------------
(* (B) LOOP machine actions (self-learning-loops.md §1.3 / state-machine.md §2a, LT1-LT7). *)
(* FAIR: the automated executor / verifier subagents always eventually act       *)
(* (WF below). That fairness + the variant is exactly what yields termination.   *)

LExecute ==   \* spec: LT1
  /\ lstate = "EXECUTE"
  /\ lstate' = "VERIFY"
  /\ UNCHANGED <<phase, gate, retries, verdict, fuel>>

LVerify ==    \* spec: LT2 : an independent verifier emits SOME verdict (nondet.)
  /\ lstate = "VERIFY"
  /\ \E v \in {"PASS","FAIL","DISAGREE"} : verdict' = v
  /\ lstate' = "ADJUDICATE"
  /\ UNCHANGED <<phase, gate, retries, fuel>>

LPass ==      \* spec: LT3
  /\ lstate = "ADJUDICATE"
  /\ verdict = "PASS"
  /\ lstate' = "DONE"
  /\ UNCHANGED <<phase, gate, retries, verdict, fuel>>

LRetryBranch ==  \* spec: LT4 : FAIL with budget remaining (V > 0)
  /\ lstate = "ADJUDICATE"
  /\ verdict = "FAIL"
  /\ retries < MaxRetries
  /\ lstate' = "RETRY"
  /\ UNCHANGED <<phase, gate, retries, verdict, fuel>>

LEscFail ==   \* spec: LT5 : FAIL with budget exhausted (V = 0)
  /\ lstate = "ADJUDICATE"
  /\ verdict = "FAIL"
  /\ retries = MaxRetries
  /\ lstate' = "ESCALATE"
  /\ UNCHANGED <<phase, gate, retries, verdict, fuel>>

LEscDisagree ==  \* spec: LT6
  /\ lstate = "ADJUDICATE"
  /\ verdict = "DISAGREE"
  /\ lstate' = "ESCALATE"
  /\ UNCHANGED <<phase, gate, retries, verdict, fuel>>

LRetry ==     \* spec: LT7 : the SOLE back-edge; increments the counter => V strictly decreases
  /\ lstate = "RETRY"
  /\ retries' = retries + 1
  /\ verdict' = "NONE"
  /\ lstate' = "EXECUTE"
  /\ UNCHANGED <<phase, gate, fuel>>

LoopNext ==
  \/ LExecute \/ LVerify \/ LPass
  \/ LRetryBranch \/ LEscFail \/ LEscDisagree \/ LRetry

(* The loop terminals DONE / ESCALATE are ABSORBING by design. An explicit       *)
(* stutter keeps the composed behavior infinite so TLC needs no -deadlock flag;  *)
(* reaching a terminal (incl. a retries-exhausted "blocked" ESCALATE) is         *)
(* intended, not a stuck state.                                                  *)
LoopTerminal == lstate \in {"DONE","ESCALATE"}
TermStutter  == LoopTerminal /\ UNCHANGED vars

-------------------------------------------------------------------------------
(* (C) BOUNDED GRAPH AMENDMENTS. A bounded amendment re-arms the representative-unit loop  *)
(* for a newly added/split unit — modelling "graph grows during P6". Guarded on            *)
(* gate["P6"] = FALSE: once every unit passed and the P6 exit gate flipped (LinkP6), the    *)
(* amendment window is CLOSED (amendments are a P6-internal step, before "all units passed").*)
(* Effects re-arm the loop (lstate' = EXECUTE, retries' = 0, verdict' = NONE) and spend one  *)
(* unit of fuel (fuel' = fuel - 1) — fuel is the well-founded, floor-bounded variant of the  *)
(* pipeline-level bound, structurally identical to `retries`. UNFAIR by design (as-needed,   *)
(* like the human gates) — NO weak-fairness on Amend; termination rests on fuel strictly      *)
(* decreasing, not on Amend being forced. An ESCALATE-origin amendment (a P7 resolution that  *)
(* amends) folds into the out-of-scope `Resolve` simplification (b) — see formal-models.md.   *)
\* spec-unmodeled: Amend — F2: `Amend` is the one FSM-bearing action with no T*/LT* id in
\* spec/fsm.json (BGA is node-internal to P6, not a modeled pipeline transition). This marker is
\* informational (SC7 finds no T/LT id here, so it neither adds nor requires coverage).
Amend ==
  /\ phase = "P6"
  /\ gate["P6"] = FALSE
  /\ lstate = "DONE"
  /\ fuel > 0
  /\ fuel'    = fuel - 1
  /\ lstate'  = "EXECUTE"
  /\ retries' = 0
  /\ verdict' = "NONE"
  /\ UNCHANGED <<phase, gate>>

-------------------------------------------------------------------------------
Next == PhaseNext \/ LoopNext \/ Amend \/ TermStutter

(* Only the LOOP is fair. The phase gates are deliberately UNFAIR (human / as-    *)
(* needed), so we assert SAFETY (never liveness) about the phase machine.        *)
Spec == Init /\ [][Next]_vars /\ WF_vars(LoopNext)

-------------------------------------------------------------------------------
(* =============== PROPERTY 1 : GATE ORDERING (SAFETY) =============== *)
(* The pipeline can never be at a phase whose predecessors' exit gates have not   *)
(* all been satisfied. Two named specializations the brief calls out:            *)
(*   - no P3 (Cartography) before gate["P2"] (clarifications resolved, I8);       *)
(*   - no P8 (Synthesis)   before gate["P6"] (every unit PASS, I10).             *)
GateOrdering ==
  /\ (phase \in {"P1","P2","P3","P4","P5","P6","P7","P8","DONE"}) => gate["P0"]
  /\ (phase \in {"P2","P3","P4","P5","P6","P7","P8","DONE"})      => gate["P1"]
  /\ (phase \in {"P3","P4","P5","P6","P7","P8","DONE"})           => gate["P2"]
  /\ (phase \in {"P4","P5","P6","P7","P8","DONE"})                => gate["P3"]
  /\ (phase \in {"P5","P6","P7","P8","DONE"})                     => gate["P4"]
  /\ (phase \in {"P6","P7","P8","DONE"})                          => gate["P5"]
  /\ (phase \in {"P8","DONE"})                                    => gate["P6"]
  /\ (phase = "DONE")                                             => gate["P8"]

(* ---- auxiliary SAFETY invariants (support the two headline proofs) ---- *)
LoopBound       == retries <= MaxRetries              \* I4 loop bound
VariantOK       == V >= 0 /\ V <= MaxRetries          \* well-founded + floor-bounded
BackEdgeGuarded == (lstate = "RETRY") => (V > 0)      \* back-edge disabled at the floor
FuelBound       == fuel >= 0 /\ fuel <= MaxFuel       \* I18 mirror: fuel floor-bounded, schema-capped

(* =============== PROPERTY 2 : BOUNDED-LOOP TERMINATION (LIVENESS) =============== *)
(* From EXECUTE the loop always eventually reaches a terminal (DONE | ESCALATE).   *)
Terminated  == lstate \in {"DONE","ESCALATE"}
Termination == (lstate = "EXECUTE") ~> Terminated
(* Equivalent from Init (lstate=EXECUTE): <>Terminated. *)

(* =============== PROPERTY 5 : BOUNDED-AMENDMENT QUIESCENCE (LIVENESS) =============== *)
(* The loop eventually STAYS in a terminal — i.e. amendments cannot re-arm it forever.     *)
(* This is the property with TEETH for BGA: `Termination` (EXECUTE ~> terminal) still holds  *)
(* even under UNBOUNDED amendment (each re-armed lap terminates), so it CANNOT catch runaway  *)
(* graph growth. `Quiesce` fails on a keep-fuel mutant (Amend with fuel' = fuel), whose        *)
(* infinite DONE->EXECUTE->...->DONE re-arm lasso never stabilises — see formal-models.md      *)
(* Property 5 non-vacuity. On the real model fuel strictly decreases, so after <= MaxFuel      *)
(* re-arms Amend is disabled (fuel = 0) and the terminals absorb.                              *)
Quiesce == <>[](lstate \in {"DONE","ESCALATE"})

=============================================================================
