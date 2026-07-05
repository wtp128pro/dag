<!-- DISAGREEMENT DOSSIER — prepared for a Socratic gate (Phase 7) when a MATERIAL
     disagreement can't be settled by evidence or bounded retries. Present EVERY option
     in full. Mark the best-supported one ★ Recommended. Never hide an option. -->

# Disagreement — <UNIT-ID or phase>: <the exact question>

- **Origin:** <executor-verifier | persona-persona | criteria-conflict> (schema `origin` enum values)
- **Why it's material:** <what downstream outcome changes depending on the answer>

## The question (stated neutrally)
<one sentence the user can answer>

## Options (all of them, in full)

> Sidecar note: each option's **Why recommended** line is prose-only (`.md`) — it is NOT carried
> into `disagreement.json`, whose per-option object is `additionalProperties:false` (`name,
> recommended, what_it_is, proposed_by, evidence_for, evidence_against, consequences,
> reversibility`). The single `recommended:true` flag plus the `recommendation` summary are its
> JSON home.

### Option A — <name>  ★ Recommended
- **What it is:** <description>
- **Proposed by:** <persona>
- **Evidence for:** <locators>
- **Evidence against / costs:** <locators>
- **Downstream consequences:** <what it commits us to>
- **Reversibility:** <easy/hard to undo later>
- **Why recommended:** <the deciding rationale>

### Option B — <name>
- **What it is / Proposed by / Evidence for / against / Consequences / Reversibility:** …

### Option C … (add as many as exist)

## Rollback options (always offer these)
- Re-clarify (Phase 2) · Re-map (Phase 3) · Re-decompose (Phase 4) · Revise the input.

## Recommendation summary
<one paragraph: which option and why, and what you'll do the moment the user picks.>
