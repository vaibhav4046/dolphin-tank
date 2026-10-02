# What stage-3.md demands that the shipped checks never demonstrated, and the check I wrote

The shipped stage-3 run (`harness/report.json`, `stage-3.counts.json`) reports **6 tests, all passing, one file (`test_sample.py`)**
and no per-requirement output. Everything below is therefore treated as uncovered by shipped evidence. Every script is stdlib-only
Python (`checks/`), runs against a fresh production container (`run_check.sh`, `run_multi.sh`), real threads, real clock.

| Requirement group (ledger) | Check | Result on 3c7c411 |
|---|---|---|
| created_at on every payment-returning endpoint, activity order (J01-J02) | t3_time | 46/0 x3 |
| seeded created_at, omission = reset time, future -> 422, balance not replayed, opening balances, new account opens 0 (J03-J05, J19) | t3_fixture | 67/0 x3 |
| `/me?as_of`: inclusive boundary at exact instant +-1 us, far past/future, echo, bad-value table (J06-J09) | t3_time | pass |
| statement vs independent oracle: ordering, ties, half-open window, opening/closing, balance_after, pagination, validation, visibility (J10-J17, J33) | t3_statement seeds 7, 45 (21: oracle equal, only my tie-coverage assertion unmet) | 72/0 |
| corrections: auth/403/404, validation table, shape, strictly increasing recorded_at, stale revision, replay after newer revisions, key scope, claimed key beats validation, failed keys reusable (J18, J20-J25, J28, J30-J31) | t3_corr | 97/0 x3 |
| correction money rule: increase debits sender / decrease debits receiver, insufficient_funds precedence, historical_overdraft (sender side, receiver side, effective_at moved earlier, same-instant COMBINED effect), atomic failure (J26-J28) | t3_corr | pass |
| known_at x as_of grid on /me and /statement vs oracle (recorded_at -1us/exact/+1us, before first record, future) (J32-J33) | t3_known seeds 11, 21, 45 | 13/0 |
| snapshots: frozen after payments/corrections, only limit/offset allowed, 404 for unknown/other user/pre-reset, has_more at end/beyond, storm of 6 writers + 6 pagers (J34-J38) | t3_snap | 52/0 x3 |
| same-expected-revision races, 30-way identical key, correction vs payment/authorize at the funds boundary, 8-writer storm with live observers, final oracle validation of every effective-time boundary (J39, J52) | t3_race x3, t3_seedholds | 48/0 x3, 26/0 |
| settlement members: revision 1 at committed_at, privacy, 422 linked_payment_immutable (J40-J41) | t3_settle | 27/0 x3 |
| REAL stage-1 and REAL stage-2 exports imported; sessions, replays, opening balances, closed_at, capture immutability, round trip, correction replay after import (J42-J43, J51) | t3_import (run_multi, 5 containers) | 57/0 |
| historical holds: creation/partial capture/final capture/void/expiry timeline, known_at x holds, closed_at, hold-aware historical_overdraft, statement purity, seeded holds (J44-J50) | t3_holds, t3_misc, t3_seedholds | 58 pass **1 FAIL (F2)**, 6/0, 26/0 |
| resource limits: 20 000 seeded payments, reset <= 10 s, 50-way burst, odd instant spellings (no 5xx) | t3_scale | 20/0 |
| stage-1 and stage-2 regression against the stage-3 image (J53) | s1reg c01-c13, s2reg | all pass **except s2_fixture: 79/5 FAIL (F1)** |
| browser product still works at 375/768/1280 (J56) | browser b1-b6 | 146, 84, 82, 19, 18, 26 all 0 fail |
| offline run, RUN.md as written, clean build (J55), stage-1/2 untouched (J54) | offline_check.sh, git diff | pass |

Not demonstrated by anyone (stated, not hidden): screen-reader pass; `go test -race` (I did not rerun it for stage 3; the authors could not);
error precedence where the spec is silent (401 vs 400 for corrections, 403 vs 422 for a non-sender on a linked payment); the statement
`known_at` echo (spec ambiguous, see verdict note 1).
