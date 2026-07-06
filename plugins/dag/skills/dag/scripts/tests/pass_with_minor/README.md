# pass_with_minor — POSITIVE (RESULT: PASS, I6 revised for coverage-first)

`U01`'s `verify.json` verdict is `PASS` while carrying a `minor` defect (a disclosed residual). Under
the PR1 coverage-first revision of I6, a PASS MAY carry `minor` observations (report every finding +
severity, filter downstream) — only a blocker/major defect blocks acceptance.

Expected: **exit 0**, with `PASS  I6 PASS coverage-first (units/U01: minor-only or no defects)`.
