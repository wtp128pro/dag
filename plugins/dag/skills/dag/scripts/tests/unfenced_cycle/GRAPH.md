# Work Graph — unfenced-cycle fixture (closes E)

This fixture reproduces adversarial attack E: a real dependency cycle written
OUTSIDE any code fence, with graph.json deleted so the fenced parser sees 0 edges.
A fail-closed validator must REJECT this (never silently pass an edge-less graph).

Dependencies (deliberately NOT in a code fence):

U01 -> U02
U02 -> U01
