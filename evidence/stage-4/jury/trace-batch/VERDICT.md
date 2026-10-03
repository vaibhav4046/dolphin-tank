# jury verdict - S4-TRACE-BATCH (POST /correction-batches, Revision.correction_batch_id, import/export, ReindexAt reservation)

Commit: **1dd55604328167f20af96d6c69989289381bbf47** (`stage-4\`; code e3eb44c + tests-only fix 1dd5560). Verified in a clean detached `git worktree` (0 dirty files, no `.git*`/`.claude*`/`*.log`/`*.orig`/`*.exe` under stage-4). Later HEAD commits (5a951db, 2eba3ac) touch only `evidence\`: `git diff 1dd5560 HEAD -- stage-4` is empty.
Specification: `spec\stage-4.md` (pocketful), sha256 `1894b002f8827fd36623df4ecf3deb204e20d7fafbbfa671894a114db80e6df1`, 4449 bytes - hash checked by me against the file; I read stages 1-4 before the code.

## Verdict: **ACCEPT** (work item S4-TRACE-BATCH)

Route decisions (a)-(d) judged against the written text: all four accepted (see below). Not covered by this item: browser UI, docker `--network none`, `-race` (no cgo on this host).

## Commands run (from `stage-4\` of the worktree) and real output
- `gofmt -l .` -> empty. `go vet ./...` -> exit 0.
- `go test -count=1 ./...` -> `ok  	pocketful	49.496s` (go-test-full-1dd5560.log). Includes the stage 1-3 Go suites.
- `node --test jstest` -> `tests 21 / pass 21 / fail 0` (node-test-1dd5560.log).
- My own checks, black box over HTTP against binaries I built myself (`go build` of 1dd5560 and, with `git archive`, of the accepted stage commits 0024598 / f33035a / 5e6f83f), final run with the final harness:

| file | scope | result |
|---|---|---|
| jury_batch_1.py | U20-U30 auth/key parity with settlements, shape, 43-body item-validation parity vs the single route, index order, settlement rules, precedence pairs | `PART1 pass=162 fail=0` |
| jury_batch_2.py | U31-U39 net effect incl. held funds, rejection atomicity + key reuse, recorded_at, snapshots, replay, refund x batch, past hold | `PART2 pass=174 fail=0` |
| jury_batch_3.py | U40 concurrency over HTTP, U42 all ten idempotent paths | `PART3 pass=143 fail=0` |
| jury_batch_4.py | U41 real stage-1/2/3 exports (built by me) imported; batches on them; export->import->export | `PART4 pass=161 fail=0` |
| jury_batch_5.py | snapshot vs import (D-B8), HTTP surface, imported revision recorded 2 h ahead of the clock | `PART5 pass=15 fail=0` |
| jury_batch_6.py | the specification's literal example; hostile-body no-5xx sweep | `PART6 pass=42 fail=0` |
| total | | **697 PASS, 0 FAIL** |

- Sensitivity of my own checks (mutate.py on a scratch copy; `mutation-check.txt`, `mutation-check-m3-m6.txt`): 11 deliberate faults (affordability on total instead of available; per-item instead of net; no rollback on historical overdraft; instants not compared; completeness off; recorded_at floor off; current-funds check removed; stale check off; refunded floor off; refund immutability off; imported batch ids not reserved) -> **11 of 11 caught**. (In the first run M3 was SKIPPED for a wrong pattern and M6 "caught" only through a harness crash; both re-run cleanly in mutation-check-m3-m6.txt: CAUGHT.)
- Regression of the earlier stages (`regression-run*.txt`, `reg-wsl-run.txt`): my accepted stage-1/2/3 scripts (unmodified) against the stage-4 image built from this worktree (`docker build`, containers in WSL, 1 or 2 per script): c01 42/0 (re-run twice on an idle host; the first run saw 14 observer samples < its threshold of 20 under load, with `[]` violations), c02 144, c03 195, c04 88, c05 49, c06 40, c07 98, c08 74, c09 10, c11 69, c12 42, c13 2, s2_lifecycle 82, s2_funds 32, s2_errors 73, s2_idem 50, s2_list 70, s2_fixture 84, s2_expiry 30, s2_race 54, s2_export 30, s2_export_expiry 18, r3_corr_order 20, r3_seedmatrix 1407, r3_sweep 118, probe_shapes rc=0 - all `0 fail, 0 5xx`. `d2_smoke` is a sibling-container isolation script that must run on a docker `--internal` network; I ran it on the host by mistake and it correctly reported outbound reachable; it is not part of the stage-3 regression set and the network-off proof belongs to the UI/docker item. The same scripts natively on Windows also passed except three that hit Windows-only environment limits (c09: connection reset on a malformed-percent-escape URL with a body; c13 and s2_race: ephemeral-port exhaustion, WinError 10048) - all three pass on the image above.

## Requirement ledger (mine: one row per normative statement)
| # | Statement | Demonstrated by | Verdict |
|---|---|---|---|
| 1 | requires a settlement operator and an idempotency key, same 401/403 rules as settlements | part1 A: 16 route parity checks vs `POST /settlements` (no token, garbage token, non-operator with/without key and with garbage body 403, operator no/empty/256-char key, bad JSON, array body, `{}`), 255-char key accepted | pass |
| 2 | corrections is 1..32 objects with distinct payment_ids, else 422 validation_failed | part1 B: 15 shapes (missing, null, string, object, empty, 33 unknown ids, 33 real ids, duplicate, non-object element x4, missing/number/null payment_id), exactly 32 -> 201 in input order, 1 item -> 201 | pass |
| 3 | every item has the ordinary correction fields and validation | part1 C: 43 bodies sent to the single route and as a batch item: same (status, code) for all; 201 bodies carry the same revision fields | pass |
| 4 | unknown payment 404; stale expected revision 409 stale_revision | part1 D (12 cases incl. index order, per-item class order) and part3 U40 | pass |
| 5 | operator may correct ordinary, request and settlement payments (any user); captures and refunds immutable | part1 E: one batch over a request payment, an ordinary payment and a whole settlement (3 users) with balances moved by exactly the net deltas; capture/refund items 422 linked_payment_immutable; non-operator sender 403 | pass |
| 6 | any settlement member requires every member, else 422 incomplete_settlement | part1 F (1 of 3, 2 of 3, member + capture, stale member), part4 on imported settlements (1 of 3, 2 of 3, 1 of 2) | pass |
| 7 | members have identical effective instants (offset spellings may differ), else 422 validation_failed | part1 F: 1 s and 1 us apart rejected; +00:00 / +02:00 / -05:00 / +09:00 spellings of one instant accepted; part4 on imported settlements | pass |
| 8 | single corrections remain for nonmembers (members refused singly) | part1 F U27 | pass |
| 9 | unknown fields ignored | part1 E (top level, item level incl. `settlement_id`, `refund_of`) | pass |
| 10 | precedence: item errors in input order, completeness, current available funds, then historical | part1 D/G (each adjacent pair with two simultaneous faults; refund_exceeds item vs funds; validation vs 404 across indices), hist cases | pass |
| 11 | existing codes apply | linked_payment_immutable, refund_exceeds_payment, insufficient_funds, historical_overdraft each produced by a batch (part1/2) | pass |
| 12 | affordability by the combined effect | part2 U31: 11 scenarios, +-1 boundaries, held funds excluded, decrease-debits-receiver, three-wallet chain, both input orders; part3 C4 funds race | pass |
| 13 | rejected batch leaves history, balances, idempotency unchanged | `/_test/export` byte-identical after every failure class (part1 snap_and_check, part2 U32 six classes, part2 hist, part4); same key then succeeds with another valid body and replays | pass |
| 14 | 201 with correction_batch_id, recorded_at, revisions in input order | part2 U33 (keys exactly those three; order [P3,P1,P2]; revision numbers per payment) | pass |
| 15 | shared recorded_at strictly later than each member's previous; each revision exposes correction_batch_id | part2 U34 (members with 4/2/1 earlier revisions; 40 alternating single/batch writes; `/revisions` ids; known_at at the batch instant and 1 us before), part5 member revision recorded +2 h ahead | pass |
| 16 | effective times cannot be later than now | part2 U35 (now+2 s, +1 h, 2099, offset-spelled), part6 | pass |
| 17 | originals and receipts never change; original payment/settlement retries return original bodies | part2 U36 (payment, settlement, refund, correction replays byte-identical after a batch; rev 1 unchanged; `/activity` of 3 users byte-identical) | pass |
| 18 | new statements reflect new revisions; earlier snapshot tokens page frozen entries | part2 U37 (two users, several limit/offset, token taken after one batch survives the next, foreign token 404, `from=` with token 422) | pass |
| 19 | replays return the original batch response with 200 | part2 U38 (byte identical, reordered keys/whitespace, after newer revisions, invalid body same key 409, per-operator and per-path key scope), part3 | pass |
| 20 | adds one idempotent write path (ten) | part3 U42: all ten paths first 201 / replay 200 identical bytes / different body 409 / 12 concurrent same-key calls -> one 201, eleven 200, one effect | pass |
| 21 | settlement payment may be refunded; refunds never change settlement membership | part2 U39 (refund_of, settlement_id null, member keeps id, receipt replay unchanged, raise/lower to exactly refunded/below -> 422, refund payment as item -> 422 linked, completeness over original members only, funds boundary with hold), part4 | pass |
| 22 | concurrent corrections sharing any expected revision cannot both succeed | part3 U40 over HTTP: 16 batches x 4 rounds, 6 batches + 6 single corrections x 5, rings of 3/5/8/12, funds race, refund vs batch x 12, conservation | pass |
| 23 | accepts exports from the same team's stages 1-3, retaining settlement membership, corrections, snapshots | part4 x 3 real exports (6-8 receipts + tokens + activity + membership + corrections replayed/retained, batches on imported data, round trips in same and fresh process, ids never reissued with the counter stripped) | pass for membership and corrections; snapshots: see D-B8 |
| 24 | stage 1-3 requirements continue | Go suites, 26 earlier jury scripts on the image | pass |

## Route decisions
- (a) D-B8 statement snapshots not serialised: **accepted**. Evidence: the accepted stage-3 binary (5e6f83f) itself does not export a token (`snapshot token present in its own export: False`) and answers 404 for it after an export->import of the same state; stage 4 behaves identically. The real stage-1/2/3 exports contain nothing to retain. Tokens of the live service do keep paging frozen entries across batches (row 18). Residual risk (see limitations).
- (b) D-B1 incomplete + unequal instants -> incomplete_settlement: accepted (the text lists completeness as one step between item errors and funds and gives the instants rule no step of its own; the second sentence presupposes every member is present).
- (c) D-B2 array-shape 422 before item errors: accepted (settlements do the same; every shape fault is the same code).
- (d) correction_batch_id null (present) on non-batch revisions, absent from statement entries: accepted (spec requires it on batch revisions only; additive for the single-correction 201).

## Observations (not rejections)
- `expected_revision` 1e30 or 99999999999999999999 (integral, positive) answers 409 stale_revision, not 422 (consistent with "integral numeric value"); fractional/zero/negative/string are 422 (part1 C).
- `effective_at` of year 0000/0001 is accepted (valid RFC 3339, in the past).
- Two harness mistakes of mine were found and fixed, not service defects: effective times chosen earlier than other payments' creation made cy's history negative (the service rightly answered historical_overdraft), and two arithmetic slips in expected balances (hold arithmetic; reversal of a two-member settlement).

## Limitations
- `-race` could not be run (no cgo); concurrency evidence is the single Store lock design plus the HTTP races above.
- D-B8: if a grader's upgrade test expects a statement token taken on the OLD service (or across an export/import of the same service) to keep paging after import, stage 3 and stage 4 both fail it; nothing in the stage-1/2/3 spec text requires it and the accepted stage 3 asserts the opposite. Closing it would mean exporting snapshots in stage 4 (and changing the stage-3 expectation).
- Docker image build with network off, UI, browser states: next item (not verified here). The stage-4 image used for the regression above was built by me from the worktree with network at build time.

## Evidence paths (`evidence\stage-4\jury\trace-batch\`)
VERDICT.md, gaps.md, jlib.py, jury_batch_1..6.py, part1..6-run.txt, mutate.py, mutation-check*.txt, run_reg.py, run_wsl_reg.sh, regression-run*.txt, reg-logs/, reg-wsl-run.txt, reg-wsl-logs/, hostile-individual.txt, go-test-full-1dd5560.log, node-test-1dd5560.log.
Reproduce: build `s4.exe` from `stage-4\`, then `python jury_batch_N.py s4.exe` (part 4 also takes s1/s2/s3.exe built from the accepted commits; part 5 takes s3.exe).
