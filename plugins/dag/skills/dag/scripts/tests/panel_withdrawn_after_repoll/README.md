GREEN control pinning the `repoll[] is empty/absent` conjunct of the N-I41 trigger (spec 2.4). The
dissent WAS withdrawn — but only after an independent lens that had never tested the finding was
re-polled, and that re-poll is recorded. This is the one shape the rubber-stamp NOTE must stay silent
on: an independent re-poll happened, so "withdrawn with no independent re-poll" is simply false.

Exit-neutral in both directions, so expectations.tsv cannot pin it (it carries exit code + a REQUIRED
substring only); the pin is a FORBID check in artifacts/i41_i42_ablation.py — drop `not _repoll` from the
trigger and this fixture starts emitting `N-I41 (dissent withdrawn`. Legal throughout: I41-4c is scoped
to `resolution == "repoll"`, I41-4d holds (panel[reproduce].verdict == post_verdict; the majority over
[FAIL, PASS, PASS] is PASS == the top verdict), and I41-4e is likewise repoll-scoped. Exit 0.
