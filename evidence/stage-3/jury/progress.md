# jury stage-3 progress (resume notes)

Order: route msgs 0e3e616f (1/3, no_reply sent), e2f38dd8 (2/3, no_reply sent), 722901d5 (3/3 LAST) -> UNSETTLED: reply to 722901d5 with verdict via mcp__jam__jam_reply_to_message.
Commit under test: 3c7c41160655da780df7567ec93ee7ad8f1c8f79 (repo D:\project\dolphin-tank\band-work\result, WSL clean clone /root/jury/s3, image pocketful-s3-jury built --no-cache OK 17.9 s).
Done: spec sha256 verified (2255d3f2...), clean clone clean (0 status lines, no .git* in stage-3), stage-1 diff vs 0024598 empty, stage-2 diff vs f33035a empty (J54 pass), ledger.md written (J01..J57, verdicts empty).
Harness stage 3 launched in background: out /mnt/d/project/dolphin-tank/band-work/checks/s3-3c7c411-jury1 (log evidence/stage-3/jury/logs/harness-stage3.log, buffered until end); then copy report to evidence/stage-3/jury/harness/.
Helpers to reuse: evidence/stage-2/jury/checks/lib.py (+ run_check.sh, run_check2.sh); copy to evidence/stage-3/jury/checks, image name pocketful-s3-jury. Browser: evidence/stage-2/jury/browser b1..b6 + run_browser2.sh (df-harness-runner).
Other images: pocketful-s1-accepted-jury (stage-1), pocketful-s2-jury (stage-2) for REAL exports.
Spec notes: as_of with '+' must be %2B encoded (RUN.md says unencoded + => 422).
TODO: t3_time, t3_fixture, t3_statement, t3_corr, t3_known, t3_snap, t3_holds, t3_settle, t3_import, t3_race (>=3 runs), offline check, stage-1/2 regression, browser regression, gaps.md, verdict.md, commit only evidence/stage-3/jury, reply route.

## Update (after t3_time/t3_fixture/t3_statement)
- Harness stage 3 DONE: claimed stage 3; stage1 147/147, stage2 35/35, stage3 6/6 (sample only), stage4 fail expected. Saved in harness/.
- checks/ has lib.py lib3.py (Oracle: opening + selected revisions at effective times) run_check.sh run_check2.sh; PASS: t3_time(46), t3_fixture(67), t3_statement seed 7 (72). Run: wsl ... bash run_check.sh <script> <run#> (logs/ gets output).
- OPEN CONCERN (likely REJECT): authorization created_at is whole second but payments microsecond. Hold starts at truncated created_at => /me?as_of=auth.created_at can show held > total, available < 0 when funding payment same second (spec: available never negative). Reproduce in t3_holds: receive pay, authorize immediately, read as_of=a.created_at.
- TODO: t3_corr, t3_known, t3_snap, t3_holds, t3_settle, t3_import(real s1+s2 exports), t3_race x3, stage1/2 regression, browser, offline, gaps.md, verdict.md

## Update 2
- PASS: t3_corr(97) t3_known(13, seed 11) t3_snap(52) t3_settle(27) ; t3_holds 58 pass, 1 FAIL = the whole-second hold bug: J44/H5 25 of 25 views /me?as_of=<authorization.created_at> available<0 (e.g. payment.created_at 07:20:07.357895, auth.created_at 07:20:07+00:00, view total 0 held 4000 available -4000; second example held 8000 total 0 because earlier voided auth still open at truncated second). => REJECT candidate (stage-2 invariant available never negative; stage-3 same view).
- TODO: t3_import (real s1+s2 exports, run_import.sh 4 containers), t3_race x3, regression s1/s2, browser, offline, gaps/verdict.
- Statement does not echo known_at (spec ambiguous) -> note only.

## Update 3
- PASS: t3_import (57, real s1 + s2 exports -> s3, round trip; run via run_multi.sh t3_import.py N pocketful-s1-accepted-jury pocketful-s2-jury pocketful-s3-jury x3), t3_race run 2 (48; observer fixed: negative running balance within an equal-effective_at tie group is legit per 'combined effect at boundary').
- Remaining: repeat runs (t3_race x3, statement/known/snap extra seeds), stage-1/2 regression vs s3 image, offline, browser b1..b6, gaps.md, verdict.md (REJECT on hold whole-second), commit evidence/stage-3/jury, reply 722901d5.
