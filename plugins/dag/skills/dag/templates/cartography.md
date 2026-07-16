<!-- CARTOGRAPHY.md — the CONTEXTUAL map of the terrain (output of Phase 3).
     Annotated meaning + relationships, NOT an inventory. A newcomer should be able to
     ACT from this, not just locate things. -->

# Cartography — <run label>

## Shape of the terrain (the few structures that organize everything)
<2–5 sentences: the mental model. What is the spine of this domain/system/topic?>

## What matters for THIS task (relevance defined by the objective)
| Element | What it is | Why it matters here | Authority / ground truth |
|---------|-----------|---------------------|--------------------------|
| <component/source/system> | <role> | <relevance to objective> | <the file/test/doc that decides; external ⇒ cite SOURCES register row S<n>> |

## Relationships (dependencies, data flows, contracts, ownership)
- <A → B: nature of the link, and the invariant that must hold>

## Invariants & risks (the things that will bite)
- **Invariant:** <must always hold> — enforced by <where>.
- **Risk:** <what could go wrong> — likelihood/impact.

## Unknowns (each becomes a clarification or a work unit)
- [ ] <unknown> → <Phase 2 clarification | Phase 4 unit>

## Lens used
- Cartographer persona(s): <name(s)>; second lens applied? <yes/no — what it caught>

> Sidecar note: the **Relationships** and **Lens used** sections are prose-only (`.md`) and are
> NOT carried into `cartography.json` — the sidecar is `additionalProperties:false` and holds only
> `run_label, terrain_shape, elements{element,role,relevance,authority}, invariants, risks, unknowns`.
> The source landscape lives in the sibling SOURCES.md / sources.json register (templates/sources.md,
> schemas/sources.schema.json) — produced by the source sweep BEFORE the cartography-informed
> clarification round; this map CITES its rows (`S<n>`), never re-describes them.
