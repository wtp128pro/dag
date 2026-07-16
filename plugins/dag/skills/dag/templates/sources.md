<!-- SOURCES.md — the source-cartography REGISTER (Phase 3 source sweep; doctrine lives in
     SKILL.md Phase 3's source-sweep step — the single authoritative copy).
     A source row is admissible only WITH a disposition — a file listing is not cartography.
     Rows are APPENDED as the run learns, never rewritten; an append lands in BOTH surfaces in
     one edit (sources.json is authoritative; this file is its human rendering). -->

# Sources register — <run label>

## Register (every source mapped, each with tier + disposition)
| ID | Tier | Source | Locator | Disposition | Accessed | Yielded / why |
|----|------|--------|---------|-------------|----------|---------------|
| S1 | <T-VENDOR \| T-COMM \| T-LOCAL> | <what it is> | <URL / path:line / git SHA / PR# / ledger path> | <consulted \| queued (for U<n>/execution) \| rejected> | <YYYY-MM-DD, consulted only — from THIS run, never invented> | <consulted: what it yielded ("silent on X" is a finding); queued: why deferred + consumer; rejected: why excluded> |

## Venue admissions (T-COMM only; once per venue — the K answers are recorded rationale, not checkboxes)
| Venue ID | Venue | K-A accountable (author/curation + correction machinery) | K-B chaseable to primary | K-C dated + version-matched | Admitted |
|----------|-------|----------------------------------------------------------|--------------------------|-----------------------------|----------|
| V1 | <site/forum> | <NAME the author/curator or editorial body; NAME the correction machinery (edit history, moderation, errata)> | <NAME a primary it chases — the doc/repo/spec it cites or the artifact it ships> | <the visible date + the version scope it matches> | <yes/no> |

## Coverage claims (what the sweep covered — each claim rests on CONSULTED rows)
| Area | Claim | Based on (consulted S-ids) | Gaps (explicit — write "none" out) |
|------|-------|----------------------------|-------------------------------------|
| <territory slice: e.g. "vendor surface for X", "repo history on Y"> | <what is now known/mapped> | <S1, S4> | <what was NOT swept and why it matters — feeds the clarification round> |

## Feeds
Consumption is evidenced where it happens — CLARIFICATIONS.md items and brief context_pointers
cite `S<n>`; grep, don't curate.

> Sidecar note: the **Register**, **Venue admissions**, and **Coverage claims** tables carry into
> `sources.json` (`sources{id,title,tier,locator,disposition,why,accessed,yielded,queued_for,venue_ref}`,
> `venues{venue_id,venue,k_a,k_b,k_c,admitted}`, `coverage{area,claim,based_on,gaps}` — schema
> `schemas/sources.schema.json`, `additionalProperties:false`). The **Feeds** section is prose-only
> and is NOT carried into the sidecar.
