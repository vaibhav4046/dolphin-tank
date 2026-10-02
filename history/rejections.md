# Rejection history

Every jury rejection: commit, requirement id, reproduction, root cause, repair commit. Append only.

## Stage 1 (pocketful)
No rejections. Jury ACCEPTED 0024598cf4a43b6584171b1f7b8f92523c652c3a on first submission (evidence/stage-1/jury/verdict.md).
Own-check failures during jury development were all jury script bugs, fixed before the final runs; the product failed none.

Residual risks the jury accepted, usable as attack input for later stages:
- net/http rejects some malformed requests (bad %-escape in path, control byte in header) with plain-text 400, no JSON envelope.
- A zero-amount request (zero split share) is payable and records a 0-amount payment.
- Import accepts a state that lacks minor_units/seq/splits/sys/tokens (204); 10 of 63 corrupted-state variants were accepted.
- Unknown route or wrong method gives 404 (no 405); HEAD /health is 404.

## Stage 2 (pocketful)
No jury rejections. Jury ACCEPTED f33035a390c63c61dfc4ce12feb8076542c8469b on first submission (evidence/stage-2/jury/verdict.md).
Own-seat repairs before submission (not rejections): quiet-row contrast and inline link touch targets (loom 7875bf1); overlapping refreshes allowed and write buttons freed before the refresh read (loom dbf467c); explicit null authorization_ttl_seconds now 422 on reset and import (trace 17aa87e, found by route's spec review). Jury-test bugs fixed by jury before final runs (logs kept under evidence/stage-2/jury/logs/).
Residual risks the jury accepted: see evidence/stage-2/route-summary.md.

## Stage 3 (pocketful)
### Rejection 1 - jury REJECT of 3c7c41160655da780df7567ec93ee7ad8f1c8f79 (evidence/stage-3/jury/verdict.md, committed 54cbd0b)
Everything else passed in jury's runs: shipped harness 147/147, 35/35, 6/6 sample; t3_* checks; stage-1 c01..c13; stage-2 regression except s2_fixture; browser b1-b6; offline.

- F1 (ledger J53, J58; REGRESSION of accepted stage 2). Reproduction: evidence/stage-3/jury/checks/repro_expired_future.py (logs/repro_expired_future.run1.log); s2reg/s2_fixture.py fails 5/84 (E03, E06, F01, A06, A02).
  Fixture: seeded authorization status "expired" with expires_at = reset + 2 h (stage 2 allows: "in the past or future").
  Stage 2: capture of the seeded open hold 201, pay above available 409. Stage 3: capture 409 authorization_expired, pay above available 201, payment.created_at = now + 7199 s.
  Root cause (route reading of the code): a seeded expired hold gets closed_at = expires_at (fixture.go trSeededClosedAt; also snapshot.go trFillClosedAt on import); store.go newestInstant() folds every Authorization.closed into st.lastStamp, so a FUTURE derived closed_at ratchets Stamp/ReadNow into the future.
  Author seat: trace (fixture/import/store). Repair: ac96360 (trace). store.go newestInstant ignores instants beyond now+50 ms; an expired seeded hold's closed_at is expires_at, or the load instant while the deadline is ahead; omitted seeded hold created_at is the reset instant (F1b). Side effect found by trace (L1): an imported future-recorded revision then lets Correct record an earlier time; follow-up in correct.go (forge) in progress.
- F2 (ledger J44, J45). Reproduction: evidence/stage-3/jury/checks/t3_holds.py section H5 (25/25 views, 3 runs).
  Authorization created_at is whole-second while payments are stamped to the microsecond; views place the hold at the truncated created_at, so GET /me?as_of=<authorization.created_at> shows total 0, held 4000, available -4000 when the funding payment and the authorization share a clock second.
  Root cause: decisions.md D-HOLD-TIME (route/forge) chose public whole-second created_at for views; it was a KNOWN_RISK, jury rules it a violation of "available = total - held, never negative" at every read.
  Author seat: forge (authz.go/history.go). Repair: 11e76f9 (forge). Authorization created_at/expires_at/closed_at share the payment clock and microsecond precision; D-HOLD-TIME revoked (decisions.md, eac8c61). Lesson for later stages: every timestamp that orders money and holds uses one clock and one precision.

### Cross-attack finding L-F2-1 (operator-recorded from the room log; evidence/stage-3/trace/, commit 849b017)

Not a jury rejection. `@trace` was asked to attack `11e76f9` at `ac96360` precisely because it did
not write either repair. Its attack found that the F2 fix did not cover state produced by the
rejected build.

- Symptom: an export written by `3c7c411` carries `created_exact`. On import that field was
  ignored, so a legacy authorization kept its whole-second `created_at` and the hold was placed
  at the truncated second — the F2 failure mode again, reachable through import. Observed as
  `available -2000` on the imported state.
- Root cause: `placeAtCreatedExact` did not exist; `created_exact` was vestigial on import.
- Repair: `5e6f83f` (forge). `store.go` gains `placeAtCreatedExact`, called in
  `indexAuthorizations` after `checkCreatedExact` passes and before the clock is derived. A valid
  `created_exact` that differs from `created_at` becomes `created_at` (microsecond) and
  `created_exact` is rewritten to the same string; `expires_at`, `closed_at`, `payment_ids` and
  `status` are untouched; absent or equal `created_exact` is left alone; a bad `created_exact`
  is still 422.
- Verification: reproduction `evidence/stage-3/trace/f2_attack.py` cases `legacy`, `imp1`,
  `imp2` return rc=0 against a build of `5e6f83f`; the reviewer's own `t3_holds.py` scores
  59 pass / 0 fail at `5e6f83f` (`evidence/stage-3/trace/rl1-jury-checks.txt`).
- Transferable rule: **a repair is only as good as the states it is reachable from.** When fixing
  a class of defect, enumerate every path that can produce the bad state — here, import of an
  older build's own export — not only the path that produced it in the failing test.

### Declined, on the record (not defects)

`D-IMPORT-FUTURE` (import does not reject a hand-crafted future-dated payment) was raised,
considered against the written specification and **declined**; see `evidence/stage-3/decisions.md`
and commit `71d08d4`. Recorded here so it is not silently re-opened later.

### Stage 3 outcome
Jury ACCEPTED `5e6f83f0a2d9fe9e09615341dde23a376d273967` on its second pass (verdict `evidence/stage-3/jury/r3-verdict.md`, evidence commit 829e053). F1 and F2 repaired and each guarded by a check that fails on 3c7c411; L1 and L-F2-1 repaired at b2d9bf3 and 5e6f83f. Residual risks and what the shipped harness never exercised: `evidence/stage-3/route-summary.md`.
