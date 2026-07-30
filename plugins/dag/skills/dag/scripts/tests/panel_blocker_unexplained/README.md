I41-3, the `blocker` half of the severity set (the sibling of panel_major_unexplained, which carries a
`major`). Spec 2.4 binds `severity` in {blocker, major}; with only a `major` fixture, narrowing the
implementation to `("major",)` alone left every fixture green. Byte-identical to panel_major_unexplained
except the member defect's severity. Exit 1 on `unexplained major`.
