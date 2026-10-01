# jury progress - pocketful stage 2 acceptance (resume notes)

Pending Band message to settle with the VERDICT: id 1333a231-73f5-4bcd-8259-fb8b690d2a84 (PART 3/3, from route). Messages ef765e10-... (1/3) and ff52cbca-... (2/3) are ALREADY settled with jam_no_reply. Reply to route with ACCEPT/REJECT via mcp__jam__jam_reply_to_message (load schema with ToolSearch select:mcp__jam__jam_reply_to_message).

Commit under test: f33035a390c63c61dfc4ce12feb8076542c8469b (main worktree clean; clean clone at WSL /root/jury/s2, image pocketful-s2-jury built --no-cache OK).
Spec: stage-2.md hash verified 39aaf9d7...13b; stage-1.md hash verified 65497dea...aa4. stage-1/ folder unchanged since my accepted 0024598 (git diff empty).

DONE
- ledger.md written pre-code (verdict column PENDING, fill at end).
- Clean clone + image build from scratch (19.7 s). Offline: internal network, outbound blocked, health+6 routes+assets+fonts served, no external URLs (only SVG xmlns in js/dom.js). Evidence offline-assets.log.
- Shipped harness (fresh --out checks/s2-f33035a-jury1; the -a dir pre-existed from someone else, harness refused it): claimed stage 2, stage1 147/147, stage2 35/35 (test_sample 10, test_ui 25). Copied to harness/. stage 3 fails (expected).
- checks/lib.py (stage-1 lib + helpers authorize/capture/void/authz/inv/sleep_until), run_check.sh (fresh container per run; usage: wsl -d Ubuntu-24.04 -u root -- bash -lc "cd /mnt/d/project/dolphin-tank/band-work/result/evidence/stage-2/jury/checks && ./run_check.sh s2_x.py 1"), s2_lifecycle.py written (NOT yet run).

TODO (check scripts to write/run, each 3 runs when race-type): s2_lifecycle, s2_funds, s2_errors, s2_idem, s2_expiry, s2_fixture, s2_list, s2_neg, s2_race (50-way authorize/pay boundary, capture storm, void vs capture), s2_conserve (concurrent observer), s2_export, s2_upgrade_api (needs stage-1 image: docker build stage-1 folder as pocketful-s1-jury), stage-1 regression (evidence/stage-1/jury/checks c01..c13 vs stage-2 image), browser (Playwright chromium in df-harness-runner image, widths 375/768/1280, all routes, states, stale-state, lost-response, latest-wins, split preview, upgrade, S66 visual), gaps.md, verdict.md, then commit ONLY `git add evidence/stage-2/jury && git commit -m ... -- evidence/stage-2/jury`.
Notes: WSL docker containers die between separate wsl invocations sometimes (exit 255) - run start+test in ONE wsl call. Git Bash /tmp is not WSL /tmp.

UPDATE (after context ~95%): API checks PASSED on f33035a image pocketful-s2-jury: s2_lifecycle 82/0, s2_funds 32/0, s2_errors 73/0 (final-field non-bool -> 400 malformed_request ok; capture with no body = full remainder 201), s2_idem 50/0 (24-way concurrent same key; 20-way capture storm), s2_expiry 30/0 (real clock ttl=2/1), s2_fixture run2 84/0, s2_list 70/0 (list+negotiation), s2_race 54/0 x5 clean runs (max latency 0.09s) [infra noise logged: run2-connrefused-infra, run3-worker-timeout - WSL VM restarted ~21:53 shared host; reruns clean].
NOTE finding (non-blocking, spec silent on upper bound): authorization_ttl_seconds > 1e9 -> 422 ("must be an integer from 1 to 1000000000"); spec says only 'positive integer'. 1e9 accepted, 1e9+1 rejected, no 5xx for 2^31..2^64. Log: logs/s2_fixture.run1-ttl-2pow31-note.log.
Seeded captured authorization: captured_amount = amount, payment_id None, payment_ids [] (spec silent).
REMAINING: s2_export (+ s2_conserve covered by s2_race), s2_upgrade_api (stage-1 image from stage-1/ folder), stage-1 regression c01..c13 vs stage-2 image, browser suite, gaps.md, verdict.md, ledger verdicts, commit evidence/stage-2/jury only, reply to route on 1333a231-73f5-4bcd-8259-fb8b690d2a84.

FINAL: all checks run; verdict.md (ACCEPT with 4 notes), gaps.md, ledger.md (78 rows PASS) written. Remaining: commit only evidence/stage-2/jury, then reply to route on message 1333a231-73f5-4bcd-8259-fb8b690d2a84.
