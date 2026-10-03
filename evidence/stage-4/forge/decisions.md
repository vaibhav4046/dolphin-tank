# forge decisions - stage 4 refunds (domain) and the Correct() changes

Spec: stage-4.md sha256 1894b002f8827fd36623df4ecf3deb204e20d7fafbbfa671894a114db80e6df1, section "Refunds and corrected history".
Code: stage-4/refund.go, stage-4/correct.go (Correct only), stage-4/model.go (Payment.RefundOf only).

## D1 Refund order of checks (State.Refund)
caller 401 -> validation 422 (integer 1..1e9) -> unknown payment 404 -> caller is not the original receiver 403 ->
target is a refund 422 invalid_refund_target -> refundedAmount + amount > latest revision amount 422 refund_exceeds_payment ->
Available(receiver) < amount 409 insufficient_funds. Every check precedes the first mutation, so any error changes nothing.
The spec fixes none of the relative order except what the work item states; these are the reading with least new behaviour
(same shape as Correct: validation, 404, 403, state rules, funds). Tests: TestRefundErrorOrderAndAtomicity (15 ordered cases).

## D2 Correct order
validation 422 -> 404 -> 403 -> linked 422 (settlement member, capture, refund) -> stale 409 -> refund_exceeds_payment 422
-> insufficient_funds 409 -> historical_overdraft 409. stale_revision before refund_exceeds_payment is the written order from
the work item; the spec is silent (KNOWN_RISK). A refund payment is "linked" for correction purposes, so its sender (the
original receiver) gets linked_payment_immutable, any other caller 403 first. Test: TestRefundPaymentsAreImmutable,
TestRefundAndCorrectionLimits (stale beats refund_exceeds_payment; refund_exceeds beats insufficient_funds).

## D3 Limit is the current corrected amount
Limit = amount of the latest revision (st.revByPay[id] last). refundedAmount is a plain scan of st.Payments with
RefundOf == id: no index or counter, so import, reset and export have nothing to rebuild and cannot drift. Cost is O(payments)
per refund or correction (ponytail comment in refund.go). A payment corrected to 0 refuses every refund (amount >= 1).
A correction may go to exactly the refunded amount; one below is refund_exceeds_payment.

## D4 The refund payment
TransferFor(from=receiver, to=sender, amount, original note, original visibility, nil request, nil settlement, nil authorization, now)
with RefundOf = target id. It gets revision 1 (effective_at = recorded_at = created_at). One st.Stamp(now) at the top of
the operation is the only clock read; created_at is that instant at microsecond precision. The target's request status,
authorization status/closed_at/held and settlement membership are never touched (tests assert the request body, the
authorization body and Held() are byte-identical before and after). A capture and a settlement member can be refunded.

## D5 Serialisation
Refund and Correct run inside the Store's critical section (Exec / Idempotent). The refunded total is read and the refund
appended in that one section, so concurrent refunds share one limit and a refund racing a correction sees either the old or
the new amount, never both. TestRefundRaceSharedLimit (64 goroutines x 100 against 1000: exactly 10 succeed),
TestRefundRacesCorrections. -race was not run: no C compiler on this machine (cgo unavailable); the tests pass without it.

## D6 Legacy
Every Payment JSON carries refund_of (no omitempty; null for non-refunds), so the stage-1/2/3 export -> stage-4 import
re-exports refund_of null. Stored idempotency bodies are never rewritten: the stage-1 and stage-2 upgrade tests replay all
6 and 13 stored receipts and compare bytes. The two upgrade tests and txCheckMigratedReads now expect the new refund_of null
(same pattern as authorization_id in stage 2). TestRefundLegacyExportWithoutRefundOf imports an export with refund_of stripped.

## D7 Amount range
Refund amount range equals the payment amount range (1..1e9, maxAmount). KNOWN_RISK: spec says only "invalid amount".

## Notes for the attack on trace's batch corrections (states to try; not run yet)
1. Same payment twice in one batch (must be validation_failed, 422); 32 vs 33 items; empty list; non-object items; unknown fields ignored.
2. Batch containing a capture or a refund payment: linked_payment_immutable in input order, before settlement completeness.
3. Settlement subset (incomplete_settlement) vs all members; members whose effective instants are equal but spelled with different offsets (ok) vs 1 microsecond apart (validation_failed).
4. A settlement member that was refunded, corrected below its refunded amount inside a batch: refund_exceeds_payment as an item error (item errors come before completeness).
5. Refund after a batch correction: the limit must be the batch revision's amount (batch revisions must land in revByPay like single ones).
6. Combined affordability: A's increase funded by B's decrease in one batch passes only as a combination; each alone fails; held funds excluded from available.
7. Historical boundaries with a refund in the member's history: a correction that is affordable now but overdraws a wallet at the refund's created_at.
8. Concurrent: two batches sharing one expected revision; a batch racing a single correction or a refund of the same payment.
9. Rejected batch: no history, balance, idempotency record, id counter or clock change; the key stays free; replay of an accepted batch returns the stored 201 body as 200.
10. recorded_at strictly later than every member's previous recorded_at, including an imported revision recorded in the future.
11. Export with batch revisions -> import -> export byte-identical; an imported correction_batch_id is never reissued.
12. effective_at later than now; effective_at in the past before the payment's creation (whole payment moves to the effective instant in stage-3 semantics).

## Open for others
The three test expectations for `correction_batch_id: null` on revision bodies (correct_test.go, handlers_history_test.go,
upgrade_test.go revisions comparison) follow trace's Revision field; they are committed only after trace commits model.go.
