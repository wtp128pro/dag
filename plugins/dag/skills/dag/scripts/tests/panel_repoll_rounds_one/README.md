I41-4e, the `verify_rounds < 2` disjunct. `panel_repoll_rounds` OMITS `verify_rounds` entirely and so
pins only the `is None` disjunct; this fixture records `verify_rounds: 1` — present, well-formed, and
still short of the second loop-until-dry round a re-poll IS. Neither fixture alone pins both halves.
Exit 1 on `I41-4e`.
