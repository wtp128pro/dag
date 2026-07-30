I42-5: an absolute path and a path escaping the run dir. Integrity is NOT decidable from emitted
artifacts for either, so both are an exit-neutral NOTE, never a FAIL. Expected exit 0 is what pins
that — if I42-5 were implemented as a rep.fail this fixture goes red.
