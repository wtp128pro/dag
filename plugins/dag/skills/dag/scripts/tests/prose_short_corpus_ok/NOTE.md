# I50 minimum-corpus floor — the GREEN control for the wrong-direction repair

This DECISIONS.md is the shape a **freshly scaffolded, empty run** has: a handful of fragmentary
lines, most of them a table. Scored naively it breaches TWO of the three aggregate bounds — its
prose-line share is under the 0.50 floor, and its few long technical tokens push ARI over 14 on a
mean sentence length of about six words.

**Both are noise, not findings.** ARI is a continuous-prose index and the three thresholds were
fitted against four real files carrying 45-181 scorable sentences; a statistic over seven fragments
measures nothing. Firing here is the WRONG-DIRECTION defect, which is the worse one: it pays an
author to **pad an empty ledger** to buy a green. This was found by pointing the validator at the
output of `init_run.sh` itself — a run that had not yet had a word written into it FAILED.

So the aggregates require a minimum corpus (30 scorable sentences) and this fixture must be
**SILENT**. Its red twin is `prose_over_bounds`, whose DECISIONS.md is **equally short** and still
goes RED — because `max_wps` is a property of ONE SENTENCE, needs no corpus, and therefore binds at
any size. That pair is what proves the split is a calibration floor and not a hole: a 90-word
sentence cannot hide inside a small file.
