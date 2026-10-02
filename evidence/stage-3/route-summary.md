# Stage 3 route summary

- Accepted source commit: `5e6f83f0a2d9fe9e09615341dde23a376d273967`. `git diff 5e6f83f HEAD -- stage-3` is empty at 829e053 (later commits are evidence, docs and history only). Jury verdict R3: ACCEPT, `evidence/stage-3/jury/r3-verdict.md`, ledger `r3-ledger.md` (58 first-pass rows + 14 new rows R01-R14, all PASS), committed 829e053.
- Spec: `stage-3.md` sha256 `2255d3f2181c22dc6eac6919bf7712197d812248bd9de8a7e59260ede6056e54`, 10288 bytes, 177 lines; same hash seen by route, trace and jury.
- Seats (by room announcement, see `evidence/operator/PROVENANCE.md`): forge = revision/correction core, historical hold timeline, one-clock repair (11e76f9), correction ordering (b2d9bf3), import placement at `created_exact` (5e6f83f); trace = statement/snapshots, fixture and stage-1/2 import migration, settlement stamp, attack tests (27c3813, 7e25c9c, 3c7c411), clock repair (ac96360), cross-attacks on 11e76f9 (849b017) and 5e6f83f (6359c0e); loom = HTTP layer, RUN.md, browser/upgrade regression (9a05b27, deea3a5, 31b2361); jury = the only accept/reject decision (54cbd0b REJECT, 829e053 ACCEPT); route = ledger, handoffs, decisions, history.
- Rejections: one jury REJECT (3c7c411: F1 clock ratchet by seeded expired hold, F2 whole-second hold views) and two cross-attack findings by the seat that did not write the code (L1 correction ordering after an imported future revision; L-F2-1 legacy export import). All repaired; see `history/rejections.md`.

## Verification the jury ran at 5e6f83f (real output in `evidence/stage-3/jury/r3-verdict.md`)
- `docker build --no-cache` OK (26.9 s); `go test -count=1 ./...` ok 39.755 s; `go test -race` ok 363.186 s; `node --test jstest` 16 pass 0 fail.
- Shipped harness: stage 1 147/147, stage 2 35/35, stage 3 6/6 (a sample only), stage 4 fails as expected.
- F1 repro matches accepted stage 2 (capture 201, over-available pay 409); `s2_fixture` 84/0. F2 `t3_holds` 59/0 x3 (3c7c411: 25 of 25 views had available < 0).
- Own checks, 0 fail: t3_time, t3_corr, t3_fixture, t3_misc, t3_settle, t3_seedholds, t3_statement, t3_known, t3_snap, t3_import (real stage-1 and stage-2 exports), t3_scale, t3_race x3, s2_export, s2_export_expiry; stage-1 c01..c13 and stage-2 s2_* regression; browser b1..b6 at 375/768/1280; offline image and RUN.md as written.
- New checks that fail on the earlier code (controls run): r3_sweep (3c7c411: 3 FAIL), r3_seedmatrix (3c7c411: 132 FAIL), r3_legacy_import against a real 3c7c411 server, r3_corr_order (ac96360: 3 FAIL), probe_r3_ttl.
- Trace attack on 5e6f83f (`evidence/stage-3/trace/rl1-attack-summary.txt`): no defect; control on ac96360 73 pass / 29 FAIL.

## Demanded by the spec but not exercised by the shipped checks, and how it was covered
The shipped harness runs only a 6-check sample for stage 3. Everything below came from seat-written checks: historical holds at every event instant and the never-negative `available` invariant (r3_sweep, t3_holds); seeded and imported values moving the clock (r3_seedmatrix, repro_expired_future); import of a real 3c7c411 export (r3_legacy_import, trace rand bursts); strictly increasing recorded times under backward wall-clock steps (r3_corr_order); statement pagination and snapshots under concurrency (t3_snap, t3_race x3); stage-2 export -> stage-3 import upgrade (t3_import, browser b4_upgrade).

## Not run / limitations
- Trace tested a Windows host binary; jury tested the Linux Docker image; no seat ran both on every check. Race detector run by jury only (trace host has no cgo).
- Browser coverage is chromium only.
- Jury's WSL clock stepped back about 0.8-1.0 s every ~32 s; the service stayed monotonic (`evidence/stage-3/jury/logs/wsl_clock_steps.log`).
- Cost: route did not instrument per-seat spend and reports no figure for stage 3.

## Residual risks the jury accepted, usable as attack input for stage 4
- `GET /statement?known_at=` does not echo `known_at` (`/me` does); jury reads the echo sentence as `/me`-only.
- Hand-built states only (no real export produces them): O-1 stored-expired hold holds nothing at any instant; O-2 stage-2 export plus injected `created_exact` can give `closed_at` before `created_at`; O-3 `created_exact` slightly ahead of now makes `/me` and `/me?as_of=now` differ in held (neither negative).
- D-IMPORT-FUTURE (import accepts hand-crafted future-dated payments) declined; see `evidence/stage-3/decisions.md`.
- Importing a 3c7c411 export keeps its whole-second `closed_at`, so a hold closed in its creation second can look released slightly early for that legacy data; money views stay consistent and non-negative.
