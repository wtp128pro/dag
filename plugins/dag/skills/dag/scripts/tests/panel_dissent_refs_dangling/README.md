I41-4b, the `dissent_refs[]` LOCUS (the sibling of panel_adj_dangling_ref, which pins the
`dispositions[]` locus). `dissent_refs[0]` names defect_index 3 on a member that records ONE defect,
while every `dispositions[]` entry resolves. Spec 2.4-4b binds BOTH keys ("Every `dissent_refs[]` /
`dispositions[]` entry"), so narrowing the implementation's key loop to `("dispositions",)` alone must
be caught — with only panel_adj_dangling_ref in the suite it was not.

The member defect stays `minor` on purpose: a dangling ref over a real major would trip I41-3 as well
and the fixture could no longer distinguish the two clauses (the panel_adj_dangling_ref precedent).
Exit 1 on `dangling ref`.
