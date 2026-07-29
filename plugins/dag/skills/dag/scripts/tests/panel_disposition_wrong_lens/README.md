I41-3, the LENS half of the "(lens, defect_index)" match. The correctness member's `major` on a PASS is
NOT dispositioned; the only `dispositions[]` entry names a DIFFERENT lens (reproduce) whose own defect it
legally resolves, so I41-4b is satisfied and cannot mask. Replace `x.get("lens") == _lens` with `True`
and the reproduce disposition silently excuses the correctness major — the fixture goes green, which is
what it pins. Exit 1 on `unexplained major`.
