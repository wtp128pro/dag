I42-3, the RUN-ROOT fall-back of the path-owner reading (invariant-spec §3.3 / the §3.4 "run-root path with
no `units/<uid>/` prefix" corner row). The verify digests `graph.json` — a run-root artifact that **no unit
owns** — and the digest no longer matches. Phase is `P6_EXECUTE_VERIFY`, so the PHASE conjunct alone
decides and the drift is an exit-neutral NOTE. Expected exit 0 on `N-I42 (digest drift`, and the NOTE names
the owner as `run root`.

Two arms meet here, and this is the only fixture that sees either:
  - **The fall-back itself.** Drop the `_own42 is None` disjunct and an unowned path's absent status reads
    as "not in flight" ⇒ hard FAIL ⇒ this fixture turns RED. The spec calls that misreading out by name.
  - **The pre-CR-6 verify-owner keying.** Under `_st42 = _i42_status.get(uid)` the verify's own unit (U01,
    `passed`) decides, so this artifact FAILs (exit 1) where it must be a NOTE. It exits 0 only under the
    path-owner reading. So it is a second, independent discriminator of CR-6, on the opposite arm from
    `digest_mismatch_crossunit_fail`: that one must go from NOTE to FAIL, this one from FAIL to NOTE.
