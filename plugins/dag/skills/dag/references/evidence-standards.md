# Evidence Standards — the anti-hallucination rulebook (req 10)

The rule is simple and absolute: **no material claim without admissible evidence.** What
counts as "admissible" is *adaptive to the claim type* (chosen because a generic task may
have no web-researchable facts at all — code claims are proven by code, not citations).

Executors attach an **evidence table** to every debrief. Verifiers reject any row whose
evidence is missing, inadmissible, or unreproducible.

## Evidence preference ordering — executable/reproducible **over** asserted (PR2)

Not all admissible evidence is equal. **Prefer evidence the verifier can *mechanically
regenerate* over evidence it must take on faith**, in this order:

1. **Executable / reproducible** — a command + its output, a re-run test, a diff of expected vs
   actual, a re-derived number (with the derivation). The verifier *re-runs it* and compares.
2. **Located but static** — a `file:line`, a dated URL + quoted section, an observed
   request/response captured earlier. The verifier *re-opens* it.
3. **Asserted** — "I checked and it holds." Admissible only when 1–2 are genuinely infeasible,
   and then it must be labeled `ASSUMPTION:` with its blast radius (rule 2).

Why this ordering is **load-bearing** (not stylistic): a re-run's correctness does **not depend on
the checker's reasoning depth** — the machine settles it. That makes reproducible evidence
*model-independent*: a modest verifier re-running a test reaches the same verdict a stronger one
would, so structure (reproducibility) substitutes for raw model IQ. It is also the **prerequisite
for data-parallel verification** (references/data-partitioning.md): a verifier that re-runs a
bounded op on a shard locator and diffs the result never needs the raw data in context. When a
claim *can* be made executable, an asserted-only version of it is a weaker debrief and the verifier
should down-rank or reject it.

## Claim taxonomy → admissible evidence

| Claim type | Example | Admissible evidence (ground truth) | Inadmissible (reject) |
|---|---|---|---|
| **Empirical/world fact** | "Library X's v3 dropped API Y." | Primary/official source (docs, changelog, spec, standard), quoted + URL/locator, dated. Two independent sources for contested facts. | "I recall…", blog without primary backing, model's parametric memory alone |
| **Code behavior** | "`verify()` rejects expired tokens." | The code itself (path:line), plus a **run**: a test/REPL/command output showing the behavior | "It should…", reading a name and inferring behavior |
| **API/tool contract** | "This endpoint returns 429 on limit." | Official API docs (URL) **or** an observed request/response | Guessing from the function name |
| **Numeric/quantitative** | "p95 latency is 180ms." | The measurement + how it was produced (command, dataset, date) | Round numbers with no derivation |
| **Causal** | "The leak is caused by Z." | A reproduction that toggles Z and shows the effect appear/disappear | Correlation, plausibility |
| **Design/judgment** | "Approach A is better than B." | An argument grounded in the *clarified acceptance criteria*, with the tradeoff made explicit; not "facts" but must be *reasoned*, and the losing option's merits stated | Assertion of superiority with no criteria linkage |
| **Provenance/quote** | "Author says '…'." | The exact source, verbatim, with locator; verify it exists before quoting | Paraphrase presented as a quote; unverifiable attributions |

## Operating rules

1. **Tag every material claim** with its type and evidence in the debrief evidence table.
   Immaterial asides don't need rows, but anything a downstream unit or the final
   deliverable relies on is material.
2. **Assumptions are labeled, never laundered into facts.** If you must proceed without
   evidence, write "ASSUMPTION:" + why it's reasonable + its blast radius if wrong. The
   verifier decides whether it needs to become a clarification (Phase 2 loop) or a
   dedicated verification unit.
3. **Cite locators, not vibes.** `file.py:42`, a URL + section, a command + its output, a
   dated measurement. A claim a verifier cannot re-open is not evidence.
4. **Verify before quoting.** Never produce a verbatim quote, citation, API name, config
   key, function signature, or file path you have not confirmed exists. Fabricated
   citations/APIs are the highest-severity hallucination — verifiers hunt these first.
5. **Two sources for contested world-facts.** If a fact could be wrong or is version-
   sensitive, corroborate independently and note the date (facts expire).
6. **Reproduce where feasible — and prefer the reproducible form.** Follow the evidence
   preference ordering above: when a claim *can* be backed by an executable/reproducible signal
   (run the test, diff the output, re-derive the number), that form is required over an asserted
   one; a verifier can regenerate it, and its correctness is model-independent. Reserve asserted
   evidence for claims where reproduction is genuinely infeasible.
7. **Absence of evidence is a finding.** "I could not verify X" is a legitimate, required
   output — surface it, don't paper over it. This is the single most important anti-
   hallucination behavior: say "unknown" out loud.

## Verifier's evidence checklist (per claim)

- [ ] Claim is tagged with a type.
- [ ] Evidence is admissible for that type (table above).
- [ ] Evidence is in its **most reproducible feasible form** (executable > located > asserted);
      an asserted claim that could have been made executable is down-ranked.
- [ ] Locator is present and resolves (the file/line/URL/command actually exists).
- [ ] For reproducible claims: the verifier reproduced it independently (re-ran + diffed).
- [ ] Quotes/citations/APIs/paths were confirmed real, not plausible.
- [ ] Assumptions are labeled as such and their risk assessed.
- [ ] Any "could not verify" is surfaced, not hidden.

A debrief with an unbacked material claim is a **FAIL**, regardless of how plausible the
claim is.
