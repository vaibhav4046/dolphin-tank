# forge attack on batch corrections - S4-FORGE-ATTACK-BATCH

Verdict: no failing observation against stage-4.md (sha256 1894b002...6df1). 297 checks PASS, 0 FAIL, 1 INFO.
Target: stage-4\ of commit 1dd55604328167f20af96d6c69989289381bbf47 (batch code e3eb44c). HEAD's stage-4 is
byte-identical to that commit (`git diff --quiet 1dd5560 HEAD -- stage-4`).

## How it ran
- Clean copy: `git archive 1dd5560 stage-4 | tar -x -C <scratch>`; `go build -o pocketful.exe .`; `PORT=18080 ./pocketful.exe`.
- `python3 batch_attack.py http://127.0.0.1:18080` -> `run-clean-1dd5560.txt` (full output). Exit 0, last line `ALL PASSED`.
- HTTP only (`/_test/reset` fixtures with seeded created_at and holds, `/_test/export`, `/_test/import`); every expectation
  comes from the spec, plus a small independent oracle for S5. Every rejection also asserts `/_test/export` is byte-identical.
- Mutation check (`mutation-check.txt`): 6 one-line mutants of correct_batch.go, each killed (2 to 21 FAILs). Run on the
  script as it was before S12 was added; no mutant targets S12.

## Priority list -> evidence (PASS counts in run-clean-1dd5560.txt)
| # | State | Checks |
|---|-------|--------|
| 1 | settlement member lowered below a refund (S1, S9) | complete and partial batches give refund_exceeds_payment as an item error (beats incomplete_settlement, input order against stale item); exact floor 201; one over; refund of a member keeps settlement_id null and membership; settlement retry bytes unchanged after batch; balances exact |
| 2 | refund racing batch/single over HTTP (S2) | 3 rounds x (12 refunds + 4 batches + 2 singles on one revision): exactly one correction wins, losers only stale/refund_exceeds, refunded <= current amount, ada = 110000-L+R and bob = 50000+L-R exactly, sum conserved |
| 3 | batch vs batch vs single on one revision (S3) | 5 rounds of overlapping chains A[p1,p2] B[p2,p3] C[p3,p4] + single p2, and D/E/F on p5: no two conflicting winners, every loser is a plain 409 stale_revision with a conflicting winner, revision counts exact; 12 identical retries -> one 201 + eleven identical 200 |
| 4 | combined affordability with held funds (S4) | alone fails / together passes (raise+raise, lower+lower across two wallets); exactly available passes, one over 409; held funds excluded; funds fault beats historical fault; stale and 404 item errors beat funds |
| 5 | historical_overdraft at an intermediate boundary (S5, S9) | all 7 subsets of three backdated moves compared with an independent oracle (pair and triple overdraw only at an intermediate instant, singles pass); refund created_at is a boundary (also for settlement members) |
| 6 | parity one-item batch vs single Correct (S6) | 21 fault/success cases, each on an identical fresh fixture: same status+code, same balances, same revision history; success: same fields, null vs batch id, 6-digit UTC recorded_at; refund payment linked in both |
| 7 | capture/refund items mixed with valid ones (S7) | linked_payment_immutable in input order against stale / 404 / validation items; beats incomplete/unaffordable; nothing changes; rejected key can still succeed, retry replays 200 |
| 8 | recorded_at and clock ratchet (S8) | after a single correction and across 25 rapid batch+single rounds the clock is strictly increasing per member and globally; one shared recorded_at; imported revision recorded 2h in the future -> batch recorded_at later than it and shared; later single correction later still; original payment retries unchanged |
| + | extra (S10-S12) | earlier snapshot token pages identical bytes after a batch, new statement shows revision 2 and the new closing balance, known_at/as_of views split correctly; 32 items ok / 33 -> 422; request payment correctable by a non-party operator, request stays paid through batch and refunds |

## Observations that are not defects (spec silent, recorded for route)
1. Differing settlement instants vs an unaffordable amount: the code returns 422 validation_failed (the instants check runs
   after completeness and before funds, trace D-B1). The spec's precedence list names no slot for it. Printed as INFO in S1.
2. Zero-change corrections (same amount, new effective instant) are accepted by both the single and the batch path (S6 parity).
3. A batch over a member whose imported revision was recorded in the future moves the service clock to that instant + 1us,
   as single Correct already does (stage-3 behaviour). Required by "strictly later than the previous recorded_at".
4. refund_exceeds_payment is an item error, so it beats incomplete_settlement and any later stale item (consistent with
   "item errors in input order"; same order as my single-correction decision D2).

## Not covered
-race (no cgo here), docker build / no-network run, browser UI, HTTP method/path surface of /correction-batches (trace, jury),
statement paging beyond the one snapshot probe in S10, malformed-body shapes (trace's U21 rows). Running several copies of the
script at once exhausts Windows ephemeral ports (WinError 10048); run it alone.
