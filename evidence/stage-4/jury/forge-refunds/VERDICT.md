# jury verdict - S4-FORGE-REFUNDS (refunds domain + Correct changes)

Commit: f2698c29fabf99fb648243cc80bb7c3a472c7481 (main). Clean detached `git worktree` at that commit, 0 dirty files.
Verdict: **ACCEPT** for this work item (refund domain, Correct changes, refund handler as present in the tree).
Scope not covered (not part of this item): batch corrections (trace), browser UI (loom, 620e5df), Docker build/run with no network, `-race` (no cgo here).

## Commands (from stage-4\ in the worktree)
- `gofmt -l .` -> empty; `go vet ./...` -> no output; `go build ./...` ok
- `go test -count=1 ./...` -> `ok  	pocketful	43.049s` (go-test-full-f2698c2.log); includes stage 1-3 suites (regression)
- `node --test jstest` -> tests 16, pass 16, fail 0
- jury checks `jury_s4_refund_test.go` (added to the worktree only): `go test -count=3 -run TestJury .` -> ok 25.6s; one verbose run in jury-and-refund-tests.log
- folder hygiene: no .git*/.claude*/*.log/*.orig under stage-4

## Requirement ledger (my own, one row per normative statement)
| # | Statement | Demonstrated by | Verdict |
|---|---|---|---|
| 1 | POST /payments/{id}/refunds, key required | TestRefundRoute (400 missing key, 422 long key); Jury HTTPSurface (GET/PUT/PATCH/DELETE, trailing slash, case, extra segment -> 404 envelope) | pass |
| 2 | only original receiver, else 403; unknown 404 | TestRefundErrorOrderAndAtomicity; Jury Surface (stranger on private payment 403); Fuzz oracle (30 seeds, 575 forbidden, 248 not_found) | pass |
| 3 | target direct/request/capture, never a refund (422 invalid_refund_target) | TestRefundOfRequestCaptureAndSettlementMember; Fuzz oracle (374 invalid_refund_target); import round trip HTTP | pass |
| 4 | invalid amount 422 validation_failed | TestRefundRoute (8 shapes) + Fuzz oracle (-1, 0, >1e9) | pass |
| 5 | cumulative refunds <= current corrected amount, else 422 refund_exceeds_payment | TestRefundAndCorrectionLimits (down/up/zero); Fuzz oracle exact-limit +-1 (973 hits); Jury HTTP race (3 rounds, exact money accounting: ada = 10000 - latest + refunded) | pass |
| 6 | refund = new payment, opposite direction, refund_of, request_id/authorization_id null, same note/visibility | TestRefundFieldsPartialsAndExactLimit; Fuzz checks every one of 716 accepted refunds field by field incl. revision 1 and created after target and every target revision.recorded; Jury Surface (private note/visibility kept) | pass |
| 7 | 201 with payment; replay 200 original body | TestRefundRoute/Replay; Jury ReplayIsStable: replay after limit used up AND after upward/downward corrections is 200 byte-identical, moves nothing; Jury HTTPConcurrency: 40 same-key calls -> exactly one 201, 39 x 200 identical | pass |
| 8 | moves existing money from receiver's available funds or 409 insufficient_funds, atomically | TestRefundUsesAvailableNotHeldFunds; Fuzz (holds, captures, voids in history; rejected op leaves JSON state byte-identical; money conserved) | pass |
| 9 | never reopens request/authorization, never restores released hold | TestRefundOfRequestCaptureAndSettlementMember (request body, authorization body, Held() unchanged); Jury RequestPaymentCorrectionAroundRefunds (request stays paid) | pass |
| 10 | other payments have refund_of null | Jury Surface: every payment in /activity has the key; only the refund is non-null; statement entries (Jury Snapshot); TestRefund... upgrade tests replay stage-1/2 stored receipts byte-identically | pass |
| 11 | corrections stay for direct/request payments; capture/refund -> linked_payment_immutable | TestRefundPaymentsAreImmutable; Jury Surface over HTTP (sender 422, other 403); Fuzz (1145 linked, never accepted); request payment corrected around a refund | pass |
| 12 | correction cannot go below refunded: refund_exceeds_payment | TestRefundAndCorrectionLimits; Fuzz post-condition (accepted => amount >= refunded; with correct revision and below => must be refund_exceeds_payment); Jury import test (after export->import twice) | pass |
| 13 | correction debits checked against available funds | TestCorrectionDebitsAvailableAndRefundHistory (held funds excluded) + Fuzz hsCheck (incl. overdrawnInThePast on every step) | pass |
| 14 | refunds never change settlement membership; settlement payment refundable | TestRefundOfRequestCaptureAndSettlementMember; Fuzz pool includes settlement members (refund ok, member corrections refused) | pass |
| 15 | stage-4 accepts exports of stages 1-3 | upgrade tests in the full suite; TestRefundLegacyExportWithoutRefundOf | pass |
| 16 | state round trip keeps refunds, limits, idempotency | Jury ExportImportOverHTTP: export -> fresh server import -> replay both keys 200 same bytes, key reuse 409, limits enforced, exact remainder ok, export -> import again; TestRefundExportImportRoundTrip byte-identical re-export | pass |
| 17 | earlier snapshot tokens page frozen entries | Jury SnapshotTokenStaysFrozen: token taken before a refund still pages 1 entry and the old closing balance; new statement shows refund entry with refund_of | pass |

## What the supplied checks did not demonstrate, and what I ran
- Handler/HTTP behaviour for the refund route (forge declared it untested; only TestRefundRoute existed): method/path surface, replay under concurrency, replay after state change, race of refunds vs corrections over HTTP -> Jury J1-J4, all pass.
- Restart/round trip with idempotency records over HTTP: J5 pass.
- Independent oracle for the refund error order and global invariants over random histories with holds, captures, settlements, requests, backdated and stale corrections: 30 seeds x 300 steps, 716 accepted / 1997 rejected refunds, 841 / 1781 corrections, every error code of the work item produced at least once, no violation.

## Observations (not rejections)
- Spec is silent on relative order of validation/404/403 and of stale_revision vs refund_exceeds_payment; forge's order matches stage 3 precedent. No requirement violated.
- RUN.md at f2698c2 does not list the refund route; loom's later commit updates it. Re-check at stage acceptance.
- `-race` could not run (no cgo); concurrency evidence is by Store-lock design plus the HTTP race tests above.
