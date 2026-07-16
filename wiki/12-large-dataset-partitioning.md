# Large-Dataset Partitioning — Map-Reduce onto the DAG

**Audience:** technical — engineers who want to run dag over a dataset far larger than one work unit could ever hold in context (500 contracts, 2k incidents, 5k model answers), and want to know *why* the design does not quietly drop half the data on the floor.

**TL;DR.** A subagent's 32K ceiling is a **reasoning budget, not a data budget** — so you **partition the work, not the context** (`data-partitioning.md:14`). Before anything else you make one fork: *mechanical-uniform* work (extract field X from 10M rows) is a script dag **orchestrates + verifies**, never shards; only *judgment-heavy per-slice* work is turned into units (`data-partitioning.md:22-37`). The judgment-heavy case is a **map-reduce onto the DAG**: a deterministic sharder script emits a `manifest.json` (`shard_id → locator`), a **parametric map wave** applies one brief *template* over it, and a **reduce tree** fans the compressed partials back in. Verification **re-runs the bounded op on the locator and diffs** — it never re-reads the raw data — which is why PR2's reproducible-evidence standard is a hard prerequisite. Structurally this is just **more units + more waves over the same FSM edge set**, so it **PRESERVES** the termination proof verbatim (`data-partitioning.md:129-136`).

Everything here traces to `plugins/dag/skills/dag/references/data-partitioning.md` (cited as `data-partitioning.md §N` / `:line`) and its schema `schemas/manifest.schema.json`. Where a guarantee's strength matters, this page uses the same proof-status legend as its sibling pages:

- **machine-checked (in scope)** — mechanically enforced by a validator/schema over emitted artifacts;
- **hand-proved** — a finite, human-checkable structural argument (a skeptic can walk the rows/edges);
- **asserted (consistent)** — a shipped *design rule* in the reference doc, consistent with the model but not mechanically re-derived or auto-enforced here.

This page never rounds a tier up. Notably, most of the partitioning *discipline* is **asserted (consistent)** — it is a reference-doc rule Phase 4 must follow, **not** something `validate_run.py` auto-checks (`data-partitioning.md:50`); the `manifest.json` shape is the one machine-checkable piece, and even it is run **by the decomposer, by hand, not by the pipeline** (§3.1).

---

## 1. The reframe: 32K is a reasoning budget, not a data budget

The whole unlock is one sentence. A subagent never needs the dataset *in* its context — it needs a **bounded brief that touches data by reference**: a grep, a SQL query, a read-by-byte-range, a file list, a shard id (`data-partitioning.md:10-12`). The raw data stays on disk or in the DB; only the *instruction* plus the *compressed output* ever occupy a context window. So the operating rule is:

> **Partition the *work*, not the *context*.** (`data-partitioning.md:14`)

Under this reframe a **unit** stops being "a chunk of data" and becomes **a bounded operation applied to a locator (shard N) that emits a compressed result** (`data-partitioning.md:16-19`). That is what lets dag operate over datasets orders of magnitude larger than any single 32K unit could hold — the size of the data is decoupled from the size of any context window.

This is the same principle the accuracy machinery states from the other direction: **atomicity is "verifiable within 32K"** — a reasoning budget, not a data budget (`data-partitioning.md:11`; and the evidence rulebook's insistence that a verifier re-runs a bounded op on a locator rather than ingesting raw data, `evidence-standards.md:26-27`).

---

## 2. The first fork — decide this *before* anything else

Most "big data" problems are secretly the *first* kind below, and the two kinds demand **opposite** machinery. Sorting this out first is the single highest-leverage decision on the page (`data-partitioning.md:21-24`).

**Mechanical-uniform** — "extract field X from 10M rows", "re-encode every image". This is **ETL / SQL / Spark**, *not* a reasoning pipeline. Running personas, Socratic gates, and adversarial verification over 10k identical shards is pure overhead. Here dag should **orchestrate + verify a script**: one unit writes the transform, one *independent* verifier re-runs it on a sample and diffs. **Do NOT shard the work into units** — this is an explicit **Non-Goal** for the partitioning machinery (`data-partitioning.md:26-30`).

**Judgment-heavy per slice** — "assess 500 contracts", "triage 2k incidents", "rate 5k answers". Each slice needs *reasoning*, not a fixed transform. **Only now** do you partition into dag units. This is the case the rest of the document designs for (`data-partitioning.md:31-33`).

The tie-breaker is a one-sentence test:

> If you cannot state, in one sentence, why a *fixed script* could not do the per-slice work, you are probably in the mechanical-uniform case — orchestrate a script. (`data-partitioning.md:35-36`)

Phase 4 of the pipeline carries this fork as a first-class callout: mechanical-uniform work is "a script dag *orchestrates*, not units it shards"; only judgment-heavy work partitions (`SKILL.md:474-477`, echoed in the decomposition method `methodology.md:203-207`). Getting the fork wrong in the mechanical direction wastes an enormous amount of budget; getting it wrong in the judgment direction silently replaces reasoning with a rigid transform.

---

## 3. Map-reduce onto the DAG (the judgment-heavy pattern)

Once you are genuinely in the judgment-heavy case, the pattern is a classic map-reduce, lowered onto dag's wave structure (`data-partitioning.md:45-84`).

### 3.1 Deterministic sharder → `manifest.json` (validated *by the decomposer*)

A **script** — not an LLM — partitions the data and emits a **manifest** mapping `shard_id → locator`, by the *natural grain*: rows → hash/range buckets; documents → per-doc or per-group; logs → time windows; categories → by class (`data-partitioning.md:47-55`). The sharder is deterministic **on purpose**: a reproducible partition is what lets the verifier later re-derive which locator a shard id points at (`data-partitioning.md:56-57`).

The manifest is checked against [`schemas/manifest.schema.json`](../plugins/dag/skills/dag/schemas/manifest.schema.json), whose only two required keys are `grain` and `shards` (`manifest.schema.json:8`). `grain` is an enum (`rows | hash | range | key_range | document | group | time_window | category | other`, `:11-15`); every shard requires a `shard_id` and a `locator`, and the locator is a **by-reference handle** `{kind, ref}` — a `file`, `glob`, `byte_range`, `sql`, `key_range`, or `url` — explicitly **"NEVER the data itself — that stays on disk/DB"** (`manifest.schema.json:27-38`). The schema *is* the enforcement of "touch data by reference."

The load-bearing subtlety: **`validate_run.py` does NOT auto-check `manifest.json`.** This is by design — the schema's own header says it is "NOT auto-run against a run by `validate_run.py`" (`manifest.schema.json:5`), and the reference repeats it (`data-partitioning.md:50`). So the manifest is validated **explicitly by you, the decomposer**, by running jsonschema yourself:

```bash
python3 -c "import json,jsonschema,sys; jsonschema.validate(json.load(open(sys.argv[1])), json.load(open(sys.argv[2])))" \
  <RUN_DIR>/manifest.json "${CLAUDE_PLUGIN_ROOT}/skills/dag/schemas/manifest.schema.json"
```

(or check by hand against the schema's required keys when `jsonschema` is unavailable) (`data-partitioning.md:52-53`, mirrored in the Phase-4 callout `SKILL.md:480-483`). Recording the manifest in the ledger is what makes the run **resumable** and every shard **verifier-addressable** (`data-partitioning.md:55`).

> **Tier honesty.** The manifest *shape* is **machine-checked (in scope)** — a real Draft-2020-12 schema jsonschema can validate — but its enforcement is **not** part of the pipeline's automatic checks: it is a decomposer-run, by-hand validation step, deliberately outside `validate_run.py` (`manifest.schema.json:5`, `data-partitioning.md:50`). Do not describe it as auto-enforced.

### 3.2 Parametric map wave — one brief *template*, not N briefs

Phase 4 today hand-reasons a *handful* of units in prose; it **cannot** enumerate 10k shards in prose (`data-partitioning.md:60`, `:105-107`). So the map wave is **parametric**: you author **ONE brief *template*** over the manifest, and the wave is that template applied across the `shards[]` array (`data-partitioning.md:59-61`; the schema states the same — "The map wave is ONE brief template applied over this array (parametric wave), not N hand-written briefs", `manifest.schema.json:23`). Each **map unit**:

- reads its brief template **plus its one shard `locator` by reference** — never the whole dataset (`data-partitioning.md:62-63`);
- performs the bounded judgment op;
- emits a **compressed partial** — a count, a summary, a top-k, the extracted rows, a per-shard verdict — **a reduction, not a copy**. If a map unit's output is as large as its input, the op was not a reduction; fix the op (`data-partitioning.md:64-66`).

Map units run in **bounded-concurrency batches** — cap in-flight units to a fixed batch size, drain and refill — never all 10k at once (`data-partitioning.md:68`, `:122`). This matters because 10k units × (execute + verify) is 20k Agent calls, so bounded concurrency plus sampling plus pushing bulk mechanical work to scripts is **mandatory, not optional** (`data-partitioning.md:113-114`, `:120-127`).

### 3.3 Reduce as a *tree*, not one node

5k partials will not fit one reduce unit's 32K budget — that would just recreate the original over-budget problem at the aggregation step. So you **fan in in groups** (e.g. 20 partials → 1 intermediate aggregate), produce intermediate aggregates, then repeat until a single root aggregate remains (`data-partitioning.md:70-73`). Each level is **just more dag waves**, and every reduce unit stays bounded. A reduce tree of fan-in `k` over `N` partials is:

```
⌈log_k N⌉  waves   — finite and small
```

(`data-partitioning.md:74`). For 5k partials at fan-in 20 that is `⌈log_20 5000⌉ = 3` reduce waves. The depth grows logarithmically, so even enormous maps reduce in a handful of waves.

### 3.4 Verify by re-run + diff, never re-read (why PR2 is the prerequisite)

The verifier **re-runs the bounded op on the same shard locator and diffs** the result against the map unit's compressed partial — it **never pulls the raw shard data into its own context** (`data-partitioning.md:76-78`). This is exactly why **PR2's reproducible/executable-evidence standard is a *prerequisite*, not a nicety**. The evidence rulebook ranks evidence **executable/reproducible > located > asserted** (`evidence-standards.md:10-20`), and spells out precisely this dependency:

> reproducible evidence is *model-independent* … "It is also the **prerequisite for data-parallel verification**: a verifier that re-runs a bounded op on a shard locator and diffs the result never needs the raw data in context." (`evidence-standards.md:24-27`)

A re-run's correctness does not depend on the checker's reasoning depth — the machine settles it — so a modest verifier reaches the same verdict a stronger one would (`evidence-standards.md:22-25`). Without that property, data-parallel verify would collapse back into "a big model re-reads everything," which is the very thing the 32K reframe forbids. Where the map op is uniform, you **sample-verify** (§5) rather than re-running every shard (`data-partitioning.md:82-83`).

### The shape, as a diagram

```mermaid
flowchart TD
    D[dataset<br/>on disk / DB] --> S["sharder (deterministic script)"]
    S --> M["manifest.json<br/>shard_id → locator {kind, ref}<br/>(schema-checked by the decomposer)"]
    M -.->|ONE brief template<br/>over shards[]| MAP
    subgraph MAP["parametric map wave (bounded-concurrency batches)"]
        m1["map(shard₁)<br/>reads locator by ref<br/>→ compressed partial"]
        m2["map(shard₂)<br/>→ compressed partial"]
        mn["map(shard_N)<br/>→ compressed partial"]
    end
    m1 -.->|verify: re-run op on locator, diff partial<br/>stratified sample, logged| V[(sample-verify)]
    MAP --> R1["reduce wave 1<br/>fan-in k (20→1)"]
    R1 --> R2["reduce wave 2<br/>fan-in k"]
    R2 --> ROOT["root aggregate"]
    ROOT --> P8["Phase 8 synthesis"]
```

Each map unit is an ordinary dag unit running the same `EXECUTE→VERIFY→ADJUDICATE` loop; the tree levels are ordinary dag waves (`data-partitioning.md:85-101`, `:131-136`). Nothing here adds an FSM edge — a fact §7 turns into the termination-preservation argument.

---

## 4. The aggregate-ledger index — a migration note that preserves "ledger is truth"

"Ledger is truth" ships today as a `units/<id>/` directory **per unit** — the durable record the validator enforces via I2 (`fsm-state.json` absent while other artifacts exist ⇒ FAIL — `validate_run.py:4317-4329`). But **10k of those directories blow up the orchestrator's own bookkeeping** (`data-partitioning.md:108-111`). A massive map wave therefore uses an **indexed / aggregate ledger** — the manifest plus a `results_index` plus a `sampling_log` — **not** 10k linear files (`data-partitioning.md:109-112`).

The schema carries both optional pieces: `results_index[]` is "one row per shard, replacing 10k linear `units/<id>/` dirs", each row a `{shard_id, partial_ref, verified}` (`manifest.schema.json:45-57`); the `sampling_log` is the honesty record (§5). Addressing is by shard id through the index:

```
manifest.shards[shard_id]  →  results_index[shard_id]
```

(`manifest.schema.json:47`, `data-partitioning.md:142-143`).

This is deliberately framed as a **migration note, not a silent change** — the discipline CLAUDE.md demands for any guarantee-touching representation change. It **revises the *representation* of "ledger is truth" while *preserving the guarantee*** (`data-partitioning.md:138-145`): everything is still written to disk and still verifier-addressable — **by shard id through the index instead of by a per-unit directory.** The migration is explicit — the index is authoritative, a per-shard record resolves through it, and the sampling log records every shard *not* individually verified. Crucially it is **opt-in for massive map waves**: small runs keep the linear `units/<id>/` layout **byte-for-byte unchanged**, so existing runs and fixtures are unaffected (`data-partitioning.md:144-145`).

> **Tier.** "PRESERVES 'ledger is truth'" is **asserted (consistent)** with a stated migration argument (`data-partitioning.md:138-145`). The *guarantee* it preserves (I2 ledger-is-truth) is itself **machine-checked (in scope)** by `validate_run.py` on the linear layout; the aggregate index is a documented representation swap that keeps the "everything is written down, addressable" property, not an auto-checked path.

---

## 5. Honest sampling — log what was *not* verified

If verification is not exhaustive — and at 10k shards it usually cannot be — you **sample (stratified) and log what was dropped. No silent truncation** (`data-partitioning.md:115-118`). Re-run + diff a *stratified* sample of shards (by class / bucket / time window), record the sample size, the stratification, and what was excluded, and **escalate any diff mismatch to a full re-run of that stratum** (`data-partitioning.md:123-125`).

The schema makes the honesty machine-shaped. `sampling_log` requires a `strategy ∈ {exhaustive, stratified, random, none}` (`manifest.schema.json:59-66`), and carries an `excluded[]` list of "shard_ids NOT individually verified — surfaced, never hidden" (`manifest.schema.json:68`). The failure mode this guards against is named directly:

> "a partial pass that *reads* as 'covered everything' is the failure mode (methodology §Hard-won #7: absence is an attack surface)." (`data-partitioning.md:117-118`)

That is the same "absence is a finding" principle the evidence standards apply everywhere: an unstated gap is not a pass, it is an unlogged hole. The sampling log makes the hole a first-class, auditable artifact rather than an invisible one.

---

## 6. The genuinely hard case — non-independent shards

Map-reduce assumes shards verify **in isolation**. That assumption breaks the moment the work has **cross-shard dependencies** — SQL/entity **joins**, cross-shard **entity resolution**, **graph edges** that cross partition boundaries (`data-partitioning.md:148-151`). A unit then *cannot* verify against its shard alone, and the clean re-run-and-diff story stops being clean. Flag which escape you are taking **early**, at Phase 3/4:

- **(a) Locality-aware partitioning** — choose the shard grain to **minimize cut edges**: partition so related records land in the same shard (by customer, by connected component, by key range), so most work stays shard-local (`data-partitioning.md:154-156`).
- **(b) Two-pass** — a **local pass** per shard, then a dedicated **boundary-resolution wave** that handles only the cross-shard cases (the cut edges), fanning in just the boundary records. The boundary wave is itself ordinary dag units over a (much smaller) boundary manifest (`data-partitioning.md:157-159`).

And the honesty backstop, which matters as much as the escapes: if neither is feasible — the data is a dense graph with no good cut — **say so at Phase 3/4**. Partitioning will not give independent verification, and the run should either shrink scope or accept a non-parallel pass. **"Do not pretend independence you do not have."** (`data-partitioning.md:161-163`).

---

## 7. Why this preserves the termination proof

The most important formal claim on the page is that all of this is **free of the FSM**. It is **hand-proved** by a short structural argument the reference states directly (`data-partitioning.md:129-136`):

- A parametric map wave is still **a wave of independent units** — *more units*, the **same edge set**. Each map unit runs the same `EXECUTE→VERIFY→ADJUDICATE` loop with the **same sole back-edge LT7** and the **same variant `V = 2 − retries`**.
- The reduce tree is **just more waves** — no new node type, no new transition.
- **No new FSM edge and no new back-edge**, so the **≤12-transition per-unit bound and Claims A–D hold verbatim** for every unit (`data-partitioning.md:133-136`; the four-claim termination proof itself lives in [`04-self-learning-loops.md`](04-self-learning-loops.md) §4 and is machine-checked in TLC as the `Termination` property, see [`03-formal-methods.md`](03-formal-methods.md)).

The reference's classification is explicit: **"Classification: PRESERVES termination and every AO/I invariant"** (`data-partitioning.md:136`), and the Phase-4 callout closes with the same line — "more units + more waves, the same FSM edge set → **PRESERVES** the termination proof" (`SKILL.md:493-494`). The DAG's acyclicity is likewise untouched, because a parametric wave is still a topological wave of mutually-independent units (`methodology.md:203-207`).

This lands squarely on the repo's hard-won discipline: a guarantee-touching change must be classified *preserves* vs *revises* and carry a migration argument for any revision. Partitioning has exactly **one** invariant-adjacent change — the aggregate ledger of §4 — and it is flagged as a **PRESERVES**-with-migration-note, never a silent change (`data-partitioning.md:129-145`).

---

## 8. What you can and cannot claim

Stated at true strength, mirroring the source's own hedges:

- **The map-reduce pattern, the first fork, the sharder discipline, verify-by-re-run** — **asserted (consistent)**: shipped *design rules* in `data-partitioning.md` (§2–§4, §6) and the Phase-4 callout (`SKILL.md:472-494`). They are the discipline Phase 4 must follow, **not** predicates `validate_run.py` auto-checks.
- **The `manifest.json` shape** (`grain`, `shards`, `locator{kind,ref}` by-reference, optional `results_index`/`sampling_log`) — **machine-checked (in scope)** by a real Draft-2020-12 schema, but run **by the decomposer, by hand — deliberately outside the pipeline's auto-checks** (`manifest.schema.json:5`, `data-partitioning.md:50`).
- **"Verify-by-re-run needs reproducible evidence"** — **asserted (consistent)** with a stated rationale (model-independence), sourced to the PR2 ordering that names data-parallel verification as its use case (`evidence-standards.md:24-27`).
- **The aggregate-ledger index preserves "ledger is truth"** — **asserted (consistent)** with a written migration argument; opt-in, small runs byte-for-byte unchanged (`data-partitioning.md:138-145`).
- **Sampling honesty** — partly **machine-checked (in scope)**: the `sampling_log.strategy` enum + `excluded[]` list are schema-shaped (`manifest.schema.json:59-70`); whether a stratification is *genuinely* representative stays a human/verifier call.
- **"Partitioning PRESERVES the termination proof"** — **hand-proved**: a finite structural argument (more units + more waves, same edge set, same sole back-edge LT7, same variant `V = 2 − retries`), resting on the §2 four-claim proof that is itself hand-proved *and* machine-checked in TLC (`data-partitioning.md:129-136`).
- **Independent verification of non-independent shards** — explicitly **NOT claimed**: when the graph has no good cut, the source instructs you to say so and shrink scope rather than fake independence (`data-partitioning.md:161-163`).

Source of record for every claim above: `plugins/dag/skills/dag/references/data-partitioning.md` and `schemas/manifest.schema.json`.

---

## Deliverable checklist (when a run uses this pattern)

Reproduced from `data-partitioning.md:165-173`:

- [ ] First fork decided **in writing**: mechanical-uniform → orchestrate a script (do NOT shard); only judgment-heavy work partitions into units.
- [ ] Deterministic sharder script emits a **schema-valid `manifest.json`** (`shard_id → locator` + `grain`).
- [ ] Map wave is **ONE brief template** over the manifest; each unit emits a **compressed** partial.
- [ ] Reduce is a **bounded fan-in tree**, not a single over-budget node.
- [ ] Verify by **re-run + diff on the locator** (never re-read raw data); sampling is **stratified + logged**.
- [ ] **Aggregate ledger (index)** used for massive waves, with the §7 migration note honored.
- [ ] **Non-independent-shard risk** assessed; escape (a) or (b) chosen, or the limit stated honestly.

---

## See also

- `plugins/dag/skills/dag/references/data-partitioning.md` — the reference this page documents (the ground truth).
- `plugins/dag/skills/dag/schemas/manifest.schema.json` — the shard-manifest schema (the one machine-checkable piece).
- [`04-self-learning-loops.md`](04-self-learning-loops.md) — the correction-loop FSM + the termination proof (Claims A–D, `V = 2 − retries`, sole back-edge LT7) that §7 shows this pattern preserves.
- [`02-llm-workings.md`](02-llm-workings.md) / [`07-accuracy.md`](07-accuracy.md) — the "dataset > context → partition the work" failure-mode row and the PR2 reproducible-evidence ordering this page depends on.
