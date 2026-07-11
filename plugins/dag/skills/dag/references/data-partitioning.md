<!-- references/data-partitioning.md — Workstream B: operating dag over datasets far larger than
     one unit's 32K budget. Read at Phase 4 when the objective is a judgment-heavy pass over many
     data slices. Structurally PRESERVES the FSM termination proof (more units + more waves, same
     edge set); the ONLY invariant-adjacent change is the aggregate ledger (migration note §7). -->

# Large-dataset partitioning — map-reduce onto the DAG

## 1. The reframe (the whole unlock)

**32K is a *reasoning / instruction* budget, not a *data* budget.** A subagent never needs the
dataset in its context — it needs a **bounded brief that touches data by reference**: a grep, a SQL
query, a read-by-byte-range, a file list, a shard id. So the rule is:

> **Partition the *work*, not the *context*.**

A **unit** becomes *a bounded operation applied to a locator* (shard N) that emits a **compressed
result**. The raw data stays on disk / in the DB; only the instruction + the compressed output ever
live in a context window. This is what lets dag operate over datasets orders of magnitude larger
than any single unit could hold.

## 2. First fork — decide this BEFORE anything else

Most "big data" problems are secretly the *first* kind below. Sort that out first, because the two
demand opposite machinery:

- **Mechanical-uniform** ("extract field X from 10M rows", "re-encode every image"). This is
  **ETL / SQL / Spark**, *not* a reasoning pipeline. Running personas + Socratic gates + adversarial
  verify over 10k identical shards is pure overhead. dag should **orchestrate + verify a script**:
  one unit writes the transform, one *independent* verifier re-runs it on a sample and diffs. **Do
  NOT shard the work into units.** (This is a Non-Goal for the partitioning machinery below.)
- **Judgment-heavy per slice** ("assess 500 contracts", "triage 2k incidents", "rate 5k answers").
  Each slice needs *reasoning*, not a fixed transform. **Now** partition into dag units. This is the
  case the rest of this document designs for.

If you cannot state, in one sentence, why a *fixed script* could not do the per-slice work, you are
probably in the mechanical-uniform case — orchestrate a script.

> **Not the same tool as Bounded Graph Amendments.** BGA (SKILL.md Phase 6 "Graph amendments
> (bounded)") grows the graph by a *few reasoning units* when executed work surfaces an unknown, spent
> from a small `expansion` fuel budget — it is **not** for dataset scale. A large-dataset pass stays a
> manifest-driven **parametric map wave** (below), sized at decomposition; do **not** spend amendment
> fuel to fan out over shards. The two mechanisms are deliberately separate — fuel bounds *discovered*
> work, the manifest bounds *data* work — so neither blurs into the other (an explicit non-goal).

## 3. Pattern: map-reduce onto the DAG (judgment-heavy case)

### 3.1 Deterministic sharder (a script, not an LLM)
A **script** partitions the data and emits a **manifest** — `shard_id → locator` — validated against
[schemas/manifest.schema.json](../schemas/manifest.schema.json) **explicitly by you (the decomposer)**:
`validate_run.py` does NOT auto-check `manifest.json` (by design — its schema header + LIMITATIONS.md),
so run
`python3 -c "import json,jsonschema,sys; jsonschema.validate(json.load(open(sys.argv[1])), json.load(open(sys.argv[2])))" <RUN_DIR>/manifest.json "${CLAUDE_PLUGIN_ROOT}/skills/dag/schemas/manifest.schema.json"`
(or check by hand against the schema's required keys when `jsonschema` is unavailable). Partition by the **natural grain**:
rows → hash/range buckets; documents → per-doc or per-group; logs → time windows; categories → by
class. Record the manifest in the ledger so the run is **resumable** and every shard is
**verifier-addressable**. The sharder is deterministic (no LLM) so the partition is reproducible and
the verifier can re-derive which locator a shard id points at.

### 3.2 Map wave — parametric + batched
Author **ONE brief *template*** over the manifest, not N hand-written briefs (Phase 4 cannot
hand-reason 10k units in prose — see §5 "Parametric waves"). Each **map unit**:
- reads its brief template + its one shard **locator** (by reference — never the whole dataset);
- performs the bounded judgment op;
- emits a **compressed partial** — a count, a summary, a top-k, the extracted rows, a per-shard
  verdict — **a reduction, not a copy**. If a map unit's output is as large as its input, the op was
  not a reduction; fix the op.

Run map units in **bounded-concurrency batches** (§6), never all 10k at once.

### 3.3 Reduce as a *tree*, not one node
5k partials will not fit one reduce unit's 32K budget. **Fan-in in groups** (e.g. 20 partials → 1
intermediate aggregate), produce intermediate aggregates, then repeat until a single root aggregate
remains. Each level is just **more dag waves**; every reduce unit stays bounded. A reduce tree of
fan-in `k` over `N` partials is `⌈log_k N⌉` waves — finite and small.

### 3.4 Verify by re-run + diff, NOT re-read
The verifier **re-runs the bounded op on the same shard locator and diffs** the result against the
map unit's compressed partial — it **never pulls the raw shard data into its context**. This is
exactly why **PR2's reproducible/executable-evidence standard is a prerequisite**
([evidence-standards.md](evidence-standards.md) §Evidence preference ordering): data-parallel verify
only works when the evidence is a re-runnable command + a diff, whose correctness is
*model-independent*. Sample-verify the map wave (§6) rather than re-running every shard when the op
is uniform and the sample is stratified.

## 4. Worked shape

```
                 ┌───────────────┐
   dataset ─────▶│ sharder (script)│──▶ manifest.json  (shard_id → locator; schema-checked)
                 └───────────────┘
                         │  (Phase 4: parametric map wave over the manifest)
        ┌────────────────┼────────────────┐            each map unit:
        ▼                ▼                ▼               brief template + ONE locator
   map(shard_1)     map(shard_2) …   map(shard_N)   ──▶  compressed partial (reduction)
        │                │                │
        └── verify: re-run op on locator, diff partial (sampled, stratified)
                         │
                 reduce tree (fan-in k):  20→1, 20→1, …   (⌈log_k N⌉ bounded waves)
                         ▼
                 root aggregate ──▶ Phase 8 synthesis
```

## 5. Gaps dag must grow (real work, not free)

- **Parametric waves.** Phase 4 today hand-reasons a *handful* of units in prose; it cannot
  enumerate 10k shards. It needs **manifest-driven wave generation**: one brief *template* + the
  manifest → the map wave. (New Phase-4 discipline + `manifest.schema.json`; see SKILL Phase 4.)
- **Aggregate ledger.** "Ledger is truth" is a `units/<id>/` directory per unit today; 10k of those
  blow up the orchestrator's *own* bookkeeping. A large map wave needs an **indexed / aggregate
  ledger** — a manifest + a `results_index` + a sampling log — **not** 10k linear files. This
  *preserves* "everything is written down" but swaps linear files for an index → **migration note in
  §7**, per CLAUDE.md.
- **Concurrency + cost bound.** 10k units × (execute + verify) = 20k Agent calls. **Bounded
  concurrency + sampling + pushing bulk work to scripts is mandatory, not optional.**
- **Sampling honesty.** If verification is not exhaustive, **sample (stratified) and log what was
  dropped** — no silent truncation. A partial pass that *reads* as "covered everything" is the
  failure mode (methodology §Hard-won #7: absence is an attack surface). The sampling log is part of
  the aggregate ledger.

## 6. Bounded concurrency, sampling, cost

- Cap in-flight map units to a fixed batch size; drain and refill (never fan out all shards at once).
- **Sample-verify**: for a uniform map op, re-run + diff a *stratified* sample of shards (by class /
  bucket / time window), not all — and record the sample size + stratification + what was excluded in
  the sampling log. Escalate any diff mismatch to a full re-run of that stratum.
- Push bulk mechanical work (filtering, counting, joining) to **scripts** the units *invoke*, not to
  the units' reasoning — reasoning budget is the scarce resource, compute is not.

## 7. Invariant note + the aggregate-ledger migration

**Structurally PRESERVES the FSM termination proof** (references/self-learning-loops.md §2,
state-machine.md): a parametric map wave is still **a wave of independent units** (more units, the
*same* edge set — each map unit runs the same EXECUTE→VERIFY→ADJUDICATE loop with the same sole
back-edge LT7 and the same `V = 2 − retries` variant); the reduce tree is **just more waves**. No new
FSM edge, no new back-edge, so the ≤12-transition per-unit bound and Claims A–D hold verbatim for
every unit. **Classification: PRESERVES** termination and every AO/I invariant.

**The one invariant-adjacent change — the aggregate ledger (migration note).** Replacing 10k linear
`units/<id>/` directories with an **indexed aggregate ledger** (manifest + `results_index` + sampling
log) *revises the representation* of "ledger is truth" while **preserving the guarantee**: everything
is still written to disk and is still verifier-addressable — by shard id through the index instead of
by a per-unit directory. Migration: the index is authoritative; a per-shard record is addressable as
`manifest[shard_id] → results_index[shard_id]`; the sampling log records every shard NOT
individually verified. Small runs keep the linear `units/<id>/` layout unchanged (this index is
opt-in for massive map waves), so existing runs and fixtures are byte-for-byte unaffected.

## 8. The genuinely hard case — non-independent shards

Map-reduce assumes shards verify **in isolation**. That breaks when the work has **cross-shard
dependencies**: SQL/entity **joins**, cross-shard **entity resolution**, **graph edges** that cross
partition boundaries. A unit then *cannot* verify against its shard alone. Two escapes, flag which
one **early** (this is where the clean pattern stops being clean):

- **(a) Locality-aware partitioning** — choose the shard grain to **minimize cut edges** (partition
  so related records land in the same shard: by customer, by connected component, by key range), so
  most work stays shard-local.
- **(b) Two-pass** — a **local pass** per shard, then a dedicated **boundary-resolution wave** that
  handles only the cross-shard cases (the cut edges), fanning in just the boundary records. The
  boundary wave is itself ordinary dag units over a (much smaller) boundary manifest.

If neither is feasible — the data is a dense graph with no good cut — say so honestly at Phase 3/4:
partitioning will not give independent verification, and the run should either shrink scope or accept
a non-parallel pass. Do not pretend independence you do not have.

## 9. Deliverable checklist (when a run uses this pattern)
- [ ] First fork decided in writing: mechanical-uniform → orchestrate a script (do NOT shard); only
      judgment-heavy work partitions into units.
- [ ] Deterministic sharder script emits a schema-valid `manifest.json` (shard_id → locator + grain).
- [ ] Map wave is ONE brief template over the manifest; each unit emits a *compressed* partial.
- [ ] Reduce is a bounded fan-in tree, not a single over-budget node.
- [ ] Verify by re-run + diff on the locator (never re-read raw data); sampling is stratified + logged.
- [ ] Aggregate ledger (index) used for massive waves, with the §7 migration note honored.
- [ ] Non-independent-shard risk assessed; escape (a) or (b) chosen, or the limit stated honestly.
