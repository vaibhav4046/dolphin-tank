# VERDICT R3: ACCEPT - pocketful stage 3, commit 5e6f83f0a2d9fe9e09615341dde23a376d273967

Both findings of my REJECT of 3c7c411 (F1 seeded expired-status hold ratcheting the clock, F2 whole-second hold views with available < 0) are repaired, the repairs introduced no regression, and every check I ran from scratch on this commit passes. No requirement violation found.

## What I verified (exact commit, clean directory)

- Commit: `5e6f83f0a2d9fe9e09615341dde23a376d273967`, `git clone` + `git checkout` into WSL `/root/jury/s3r3`: `git status --porcelain` 0 lines, `.git*` inside `stage-3/` 0. `git diff 5e6f83f HEAD -- stage-3` empty (HEAD 6359c0e is evidence only). `git diff 0024598 HEAD -- stage-1` and `git diff f33035a HEAD -- stage-2` empty. `git diff --stat 3c7c411 5e6f83f -- stage-3` lists 18 Go files and nothing else (no `web/`, no `jstest`, no Dockerfile/RUN.md change).
- Spec: stage-3.md sha256 `2255d3f2181c22dc6eac6919bf7712197d812248bd9de8a7e59260ede6056e54` (177 lines, 10288 bytes) verified on disk and equal to the part 1/2 text; stage-1.md `65497dea...` and stage-2.md `39aaf9d7...` verified. Ledger rows J01-J58 were written from the spec in the first pass, before any source; this pass added rows R01-R14 (`r3-ledger.md`).

## Commands run and real results

1. `docker build --no-cache -t pocketful-s3-r3 stage-3` (clean checkout): `Successfully tagged pocketful-s3-r3:latest`, 26.9 s, image id `428e11dd1fd8`; the RUN.md build ran again with the same id.
2. `go vet ./... && go build ./... && go test -count=1 ./...` (golang:1.24, source from the clean checkout): `ok  pocketful  39.755s`. `go test -count=1 -race ./...` (CGO): `ok  pocketful  363.186s`. `node --test jstest` (node:20-alpine): `# tests 16 # pass 16 # fail 0`.
3. Shipped harness: `python -m harness run --track pocketful --repo /root/jury/s3r3 --all --mode isolated --out .../s3-5e6f83f-jury1`: `stage-3/: claims stage 3 on the shipped checks`, report revision `5e6f83f0...`, stage 1 147/147, stage 2 35/35, stage 3 6/6 (a sample only), stage 4 fail (expected). Copy in `harness-r3/`.
4. F1 repro (`checks/repro_expired_future.py`, accepted stage-2 image vs 5e6f83f, same fixture and calls):
   ```
   stage-2 (accepted)     /me held=2000 available=8000 | capture seeded open hold -> 201 None | pay 8001 (> available 8000) -> 409 | payment.created_at - now = None s
   stage-3 (under test)   /me held=2000 available=8000 | capture seeded open hold -> 201 None | pay 8001 (> available 8000) -> 409 | payment.created_at - now = None s
   ```
   3c7c411 had capture 409 `authorization_expired`, pay 201, created_at +7199 s. `s2reg/s2_fixture.py`: 84 pass / 0 fail (3c7c411: 79/5).
5. F2: `t3_holds.py` H5 (every `/me?as_of=<authorization.created_at>` after back-to-back pay+authorize has available >= 0; expected total 5000 held 4000 available 1000): 59 pass / 0 fail x3 (3c7c411: 25 of 25 views violated).
6. My first-pass checks, fresh container per run, image `pocketful-s3-r3`, all 0 fail and 0 5xx: t3_time 46 x2, t3_corr 97 x2, t3_fixture 67, t3_misc 6, t3_settle 27, t3_seedholds 26, t3_statement 72 (seeds 7, 45; seed 21 71/1, see notes), t3_known 13 (seeds 11, 21, 45), t3_snap 52, t3_import 57 (REAL stage-1 and stage-2 exports), t3_scale 20, **t3_race 48/0 x3** (11199, 11775, 11875 requests, since b2d9bf3 touched correct.go), s2_export 30, s2_export_expiry 18.
7. Stage-1 and stage-2 regression (`run_regression.sh r3`): c01 42, c02 144, c03 195, c04 88, c05 49, c06 40, c07 98, c08 74, c09 10, c11 69, c12 42, c13 2; s2_lifecycle 82, s2_funds 32, s2_errors 73, s2_idem 50, s2_list 70, s2_fixture 84, s2_expiry 30, s2_race 54; all 0 fail, 0 5xx.
8. Browser (Playwright chromium in df-harness-runner, 375/768/1280, states, keyboard, recovery, stage-1 session upgrade): b1 146, b2 84, b3 82, b5 18, b6 26, b4_upgrade 19, all 0 fail. The browser product is unchanged by these commits (no web file differs from 3c7c411).
9. Offline and RUN.md (`r3_offline_check.sh`): RUN.md commands verbatim -> `{"status":"ok"}`; `docker network create --internal`, sibling container: outbound to 1.1.1.1 and 8.8.8.8 blocked; six routes, three CSS files, `main.js`, both woff2 fonts 200 from the image; `EXTERNAL REFERENCES: none`; stage-3 endpoints answer offline.

## New checks written for this commit (each fails on the code it guards; controls run)

| Check | Result on 5e6f83f | Control |
|---|---|---|
| `r3_sweep.py` seeds 1-6: random back-to-back lifecycle, then 4 users x every payment/authorization/closed/expiry instant +-1us via `/me?as_of`, oracle from public timestamps only (held, total), echo, conservation, `expires_at - created_at == ttl`, `closed_at == last capture created_at`, stamps inside request windows | 118, 115, 130, 136, 124, 136 passes; 1596, 1584, 1596, 1464, 1620, 1680 views; 0 fail; 0 views with available < 0 | 3c7c411 seed 1: 3 FAIL |
| `r3_seedmatrix.py`: 24 seeded-hold cases (status x deadline x created_at) + funded seed (seeded payment funds seeded hold, both defaulted): clock window, hold `created_at` = reset instant, `closed_at` never in the future, live hold held exactly 2000, capture 201/409 as stage 2, pay above available 409, views +-1us, export -> import x2 unchanged | 1407 pass / 0 fail | 3c7c411: 132 FAIL |
| `r3_legacy_import.py` seeds 5, 6, 7: REAL 3c7c411 server (`git archive 3c7c411 stage-3`, built by me), 30-step history with back-to-back fund+authorize, captures, voids, expiry, a correction; export -> POST `/_test/import` into 5e6f83f twice | 33 pass / 0 fail each: closed_at/expires_at/payment_ids/status/amounts unchanged (0 diffs), imported `created_at == created_exact`, payments/revisions/current views identical, 153/135/171 instants x 4 users with 0 negative available, held == public-field oracle, total == the legacy server's own total at every instant, next payment stamped at its own request time | the legacy server itself had 14/17, 14/16, 9/18 `authorization.created_at` views with available < 0 |
| `r3_corr_order.py`: 60 rapid corrections, seeded payments corrected at once, hand-built import with revision 1 recorded 0.03 s and 0.6 s ahead, 70 s loop of pay + correct + export/import round trips across natural wall-clock steps | 20 pass / 0 fail, 3546 requests (steps of -932.6 and -617.4 ms occurred during the run) | ac96360: 3 FAIL (correction recorded before its revision 1; "not strictly after" right after a -954 ms step) |
| `probe_r3_ttl.py`: `authorization_ttl_seconds` 1 .. 1e30 | identical to accepted stage 2 (201 for 1 and 3600, 422 for huge values), no 5xx | - |

## Requirement ledger result

`r3-ledger.md`: 58 first-pass rows + 14 new rows, all PASS. The four rows that failed on 3c7c411 (J44, J45, J53, J58) now PASS with the evidence above.

## Notes (non-blocking, not tied to a failing requirement)

1. `GET /statement?known_at=` still does not echo `known_at` (`/me` does). The spec's "Echo supplied `known_at` exactly" follows a paragraph covering both endpoints, but the statement example has no echo field and `handlers_history.go` is untouched by the repairs. I treated it as `/me`-only in the first pass and still do; adding the field would be harmless.
2. Route's KNOWN_RISKS O-1, O-2, O-3 and the declined D-IMPORT-FUTURE concern hand-built states that no export of this or an earlier service produces; I found no written requirement they violate. My own hand-built imports (revision recorded 0.03 s and 0.6 s ahead) behave correctly.
3. Importing an export of the rejected 3c7c411 keeps its whole-second `closed_at`, so for such legacy data a hold closed in the same second it was created can show as released slightly earlier than it truly was. Money views stay consistent and non-negative (checked at every instant); the spec says nothing about 3c7c411 exports.
4. Environment: this WSL2 VM steps its wall clock back ~0.8-1.0 s about every 32 s (`logs/wsl_clock_steps.log`). The service stays strictly monotonic through it (`ReadNow`/`Stamp`, b2d9bf3), and `r3_corr_order` D exercises exactly that. My window assertions use `checks/clk.py` to tolerate the steps.
5. Not run: a Windows host binary (trace tested one; I ran the Docker image under Linux), and no persistent storage across container restarts (not required by the spec).

## Honest notes on my own check development

Early failures that were mine, fixed before the final runs (details in `r3-ledger.md`): r3_sweep seed 4 first run flagged stamps 60 ms ahead of their request window (WSL clock step; fixed with `clk.py`, failing line kept in `logs/wsl_clock_steps.log`); r3_seedmatrix first run had 16 FAIL from a bug in my snapshot comparison; r3_legacy_import first trial had a too-high self-check threshold; t3_statement seed 21 keeps its one self-coverage failure (no tie drawn), as in the first pass; three docker port collisions in the regression run did not affect any result (c08, the two-container script, passed 74/0).

## Evidence paths (all under `evidence/stage-3/jury/`)

`r3-verdict.md`, `r3-ledger.md`, `logs/r3-run-main.summary.log`, `logs/r3-run-new.summary.log`, `logs/r3-regression.summary.log`, `logs/r3-browser.summary.log`, `logs/r3-offline-and-runmd.log`, `logs/r3-harness.log`, `logs/r3-gotest.log`, `logs/r3-gotest_race.log`, `logs/r3-docker_build.log`, `logs/r3-jstest.log`, `logs/wsl_clock_steps.log`, per-run logs `logs/*.runr3*.log` (controls: `*.runr3ctl*.log`), `harness-r3/`, scripts `checks/r3_*.py`, `checks/clk.py`, `checks/probe_r3_*.py`, `r3_run_main.sh`, `r3_run_new.sh`, `r3_browser_all.sh`, `r3_offline_check.sh`, browser screenshots `browser/shots/runr3/`.
