I42-3, the STATUS conjunct of the transient window. The phase IS `P6_EXECUTE_VERIFY` — the half of the
I9 window that would excuse a digest drift — but the owning unit is `passed`, i.e. terminal: nothing is
in flight and nothing may legitimately still be rewriting the evidence. Byte-identical to
`digest_mismatch_p6_note` except the ledger status. Drop the status conjunct from the transient arm and
this fixture is downgraded to a NOTE and goes green. Exit 1 on `digest mismatch`.
