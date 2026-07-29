I41-3, the DEFECT_INDEX half of the "(lens, defect_index)" match. The correctness member records a
`major` at index 0 and a `minor` at index 1; the only `dispositions[]` entry names index 1, so I41-4b is
satisfied (the ref resolves) and the `major` at index 0 is still unexplained. Replace
`x.get("defect_index") == _j` with `True` and the index-1 disposition silently excuses the index-0 major
— the fixture goes green, which is what it pins. Exit 1 on `unexplained major`.
