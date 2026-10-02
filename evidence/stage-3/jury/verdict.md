# VERDICT: REJECT - pocketful stage 3, commit 3c7c41160655da780df7567ec93ee7ad8f1c8f79

Two requirement violations, each reproduced deterministically. Everything else I tested passes (ledger.md: 54 of 58 rows PASS; J44, J45 (same-second case), J53 and J58 FAIL).

- Commit verified: `3c7c41160655da780df7567ec93ee7ad8f1c8f79` (clean `git clone` + `git checkout` into WSL `/root/jury/s3`, `git status` 0 lines, no `.git*` inside `stage-3/`). `git diff 0024598 HEAD -- stage-1` and `git diff f33035a HEAD -- stage-2` are both empty (T63 pass).
- Spec: `stage-3.md` sha256 `2255d3f2181c22dc6eac6919bf7712197d812248bd9de8a7e59260ede6056e54` (177 lines) verified on disk; ledger written from it before any source was read.

## F1 - REGRESSION of accepted stage-2 behaviour: a seeded `expired`-status authorization with a future `expires_at` moves the server's timestamps into the future
Requirement: stage-2.md "Model": seeded `status` may be `open`, `captured`, `voided` or `expired`; "Seeded expiry times are at least an hour from reset time, in the past or future"; an open seeded hold reserves funds and can be captured/voided; held funds cannot fund payments. stage-3.md "Payment timestamps": `created_at` is "when it moved money"; corrections' `effective_at` must be "not later than now".
Reproduction (`checks/repro_expired_future.py`, same fixture and calls on the ACCEPTED stage-2 image and on stage 3):
fixture = ada 10000, bob 2500, cy 0; authorizations `a1` open ada->bob 2000 and `a4` **expired** ada->bob 4000, both with `expires_at` = reset time + 2 h; then bob captures 800 of a1 (final:false); then ada pays cy 8001.
```
stage-2 (accepted)     /me held=2000 available=8000 | capture seeded open hold -> 201 None                    | pay 8001 (> available 8000) -> 409 | payment.created_at - now = None s
stage-3 (under test)   /me held=2000 available=8000 | capture seeded open hold -> 409 authorization_expired | pay 8001 (> available 8000) -> 201 | payment.created_at - now = 7199 s
```
Expected: capture 201, over-available payment 409 `insufficient_funds`, `created_at` about now (as on the accepted stage-2 image). Actual: the seeded expired-status entry's `expires_at` becomes its `closed_at`, and that future value ratchets the service's monotonic stamp source: every later payment/authorization is stamped about 2 h ahead (`created_at` +7199 s), the seeded open hold counts as expired at once (capture 409 `authorization_expired`), the hold stops funding checks (payment of 8001 against 8000 available is accepted, 201). The reset alone is enough (`checks/probe_clock_jump.py`: only the expired-status entry triggers it; open, captured and voided entries with future `expires_at` do not).
Evidence: `logs/repro_expired_future.run1.log`; my accepted stage-2 script `s2reg/s2_fixture.py` now fails 5 of 84 (E03, E06, F01, A06, A02) in `logs/s2_fixture.runr1.log` and again in a clean rerun (`logs/s2_fixture.runr2.log`); the same script passes 84/84 on the stage-2 image.
Ledger: J53 (regression), J58.

## F2 - historical `/me` views show impossible holds: `available < 0` and `held > total` at `as_of = authorization.created_at`
Requirement: stage-2.md rule 2 and `GET /me`: "`available` is `total - held`, never negative"; Concurrent operations: "the requirements above hold at every read"; stage-3.md "Historical holds": "all four money fields describe that same view ... A hold starts at authorization creation"; and "A correction is rejected ... if it makes either total or available negative at any past ... boundary" (so valid histories never have negative available).
Cause visible from outside: authorizations report a whole-second `created_at` while payments are stamped to the microsecond, and the hold is placed at the truncated public instant. A payment that really happened BEFORE the authorization therefore carries a LATER `created_at` than the hold it funded.
Reproduction (`checks/t3_holds.py`, section H5; 25 iterations, ada funds bob with 5000, bob immediately authorizes cy for 4000, then GET `/me?as_of=<that authorization's created_at>` for bob):
```
payment.created_at 2026-10-02T07:20:07.357895+00:00   authorization.created_at 2026-10-02T07:20:07+00:00
  GET /me?as_of=2026-10-02T07:20:07%2B00:00  ->  total 0, held 4000, available -4000
second iteration: total 0, held 8000, available -8000   (the previous authorization, voided a few ms earlier, is still counted as open at the truncated second)
```
25 of 25 views violated, in three separate runs (`logs/t3_holds.run1.log`, `.run2.log`, `.run3.log`). Expected: total 5000, held 4000, available 1000 (the payment preceded the hold). It reproduces whenever the funding payment and the authorization fall in one clock second, i.e. for any back-to-back client. With events more than a second apart every probe passes (timeline H1-H3 in the same script: 58 other assertions pass).
The authors listed this as KNOWN_RISK (1) and chose to keep it ("pinned by TestWholeSecondHoldCanLookUnaffordableBeforeTheMoneyThatPaidForIt"). On the written spec it is a violation, not a taste issue: the invariant is stated without a time qualifier and `created_at` precision is not fixed by the spec (payments already use microseconds), so a single clock source/precision for authorizations, closes and payments removes it.
Ledger: J44, J45.

## What passed (commands and real output)
All commands run by me against the clean checkout's image `pocketful-s3-jury` (built `docker build --no-cache`, 17.9 s, `Successfully tagged`).
1. Shipped harness, exact command, new `--out` (`.../checks/s3-3c7c411-jury1`): `highest contiguous stage: 3`, `claimed stage: 3 on the shipped checks`, `report.json` revision `3c7c4116...`, stage 1 147/147, stage 2 35/35, stage 3 6/6 (sample only), stage 4 fail (expected). Copy in `harness/`.
2. Own checks (counts are passes/fails, every run 0 5xx): t3_time 46/0 x3, t3_fixture 67/0 x3, t3_statement 72/0 (seeds 7, 45; seed 21 oracle-equal), t3_corr 97/0 x3, t3_known 13/0 (seeds 11, 21, 45), t3_snap 52/0 x3 (688 full snapshot reads under 6 writers), t3_settle 27/0 x3, t3_import 57/0 (REAL stage-1 and stage-2 exports, round trip), t3_race 48/0 x3 (about 11k requests each), t3_seedholds 26/0, t3_scale 20/0 (20 000 seeded payments, reset within limit, 50-way burst under 5 s), t3_misc 6/0, t3_holds 58 pass / 1 fail (F2).
3. Stage-1 regression c01..c13 on the stage-3 image: all pass (c01 failed once under host load with 9 observer samples and passed on a quiet rerun, 42/0; c08 passed 74/0 after a port collision on my side). Stage-2 regression: s2_lifecycle 82, s2_funds 32, s2_errors 73, s2_idem 50, s2_list 70, s2_expiry 30, s2_race 54, s2_export 30, s2_export_expiry 18, s2_upgrade_api 23 all 0 fail; **s2_fixture 79/5 fail (F1)**.
4. Browser (Playwright chromium, df-harness-runner, 375/768/1280): b1_quality 146/0, b2_wallet 84/0, b3_flows 82/0, b4_upgrade (stage-1 session -> stage-3) 19/0, b5_visual 18/0, b6_states 26/0.
5. Offline and RUN.md: `docker network create --internal`; sibling container: outbound to 1.1.1.1 and 8.8.8.8 blocked; six routes, three CSS files, `main.js`, both woff2 fonts 200 from the image; no external URL; stage-3 endpoints work (`logs/offline-and-runmd.log`). RUN.md build and run as written: `/health` -> `{"status":"ok"}`.

## Spec-silent author choices (route KNOWN_RISKS / decisions.md) - decided from the written spec only
| Choice | Ruling |
|---|---|
| (1) whole-second authorization created_at; overdraft check uses exact time, views use public time | **Violation** (F2). |
| (2) a correction is the SELECTED revision at its effective_at (whole movement moves), not a diff | Not a violation: "apply selected revisions according to their effective times"; my oracle built on this reading matches every view/statement, incl. after 2 600 random corrections. |
| (3) statement `from` in the future with no `to` = empty window | Not a violation (spec silent on inverted windows). |
| (4) reset/import hold validation uses the real clock | Not a violation. |
| (5) microsecond created_at; ties by bytewise payment id | Not a violation ("then payment id ascending"). |

## Notes (non-blocking)
1. `GET /statement?known_at=` does not echo `known_at` (the `/me` response does). The sentence "Echo supplied `known_at` exactly" follows the paragraph on both endpoints and the statement example shows no echo field; I treated it as `/me`-only. If the authors can add the echo cheaply, do.
2. Wrong-typed correction fields (`expected_revision: "1"`, `reason: 5`, nulls) answer 422 `validation_failed`; stage-1 5 reserves 400 for wrong types but stage-3 says "Invalid input is 422", so both readings are defensible.
3. Seeded `created_at: null` on a fixture payment is accepted (204); only future values are named by the spec.
4. Infrastructure on my side: concurrent runs caused three docker port collisions and one observer-count flake; all affected scripts were rerun alone and passed.

## Honest notes on my own check development
Failures in early runs that were my own test bugs, fixed before the final runs (logs kept): t3_time run 1 (oracle ignored a hold I had created); t3_fixture (wrong arithmetic in one expectation); t3_corr (a decrease also lowers the receiver's history, so my first "reusable key" scenario was historically overdrawn - rebuilt with slack and a different-body retry); t3_snap (indexed past a 19-payment list); t3_import (two count expectations); t3_race run 1 (observer treated a negative running balance inside an equal-effective_at tie group as a violation - the spec's "combined effect at that instant" makes the boundary balance the right test - and the oracle read only the first 200 statement entries). Two assertions in earlier drafts that could not fail were removed. Real exports written during t3_import contain session tokens and password hashes, so they were deleted instead of committed; they are regenerated by `t3_import.py`.

## Required for ACCEPT (what would change my verdict)
Fix F1 (seeded `expired` hold must not feed the stamp source; `closed_at` of a seeded expired hold should not be later than now) and F2 (one timestamp precision/clock for authorization creation, closure and payments, so `/me?as_of` never shows available < 0 or held > total). I will verify the new commit from scratch with the same scripts (`checks/t3_holds.py`, `checks/repro_expired_future.py`, `s2reg/s2_fixture.py`, the full list above).

## Verification budget (rough, not measured)
About 110 tool calls this session; context peaked near 410k tokens of the 1M window; wall time about 3 h including WSL docker start-ups; no subagents.
