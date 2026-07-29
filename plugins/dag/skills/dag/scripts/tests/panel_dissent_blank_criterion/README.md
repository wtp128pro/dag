I41-2, the non-blank-`criterion` conjunct. The dissenting member DOES carry a `defects[]` entry, but its
criterion is whitespace only — spec 2.4-I41-2(a) requires ">=1 defects entry whose criterion is non-blank
under .strip()", because a finding that names no criterion is exactly as unauditable as no finding at all.
Replace the criterion test with a bare `defects[]`-presence test and this fixture goes green.

`"   "` and not `""`: the schema's `criterion.minLength: 1` rejects the empty string, so only whitespace
exercises `.strip()`. A `panel_adjudication` is present (I41-1 satisfied) and the defect is `minor`
(I41-3 silent). Exit 1 on `bare dissent`.
