# trace decisions, stage 4 batch corrections (implementation commit e3eb44cc80732b79b703c6f0bcd4f41ee8b306a6)

Spec: stage-4.md sha256 1894b002f8827fd36623df4ecf3deb204e20d7fafbbfa671894a114db80e6df1. Ledger rows U20-U41.

## Error order of POST /correction-batches (U29)

1. Route level, as POST /settlements: no/unknown token 401; authenticated non-operator 403 (before the key and the body);
   Idempotency-Key 400/422; body not a JSON object 400. All of this happens before the Store lock.
2. Inside Store.Idempotent (key lookup, effect, record are one critical section): a stored key with the same canonical
   body replays 200; a stored key with another body is 409 idempotency_key_reuse.
3. Array shape, 422 validation_failed: `corrections` is not an array of 1..32 objects, an element is not an object, an
   element has no string `payment_id`, or two elements name the same payment_id. Evaluated before any item error (D-B2).
4. Item errors, items walked in input order, the first failing item wins. Per item: its correction fields (the existing
   ParseCorrectionBody rules, kept on the item until the walk reaches it) 422 -> effective_at not later than the batch's
   instant 422 -> unknown payment 404 -> capture or refund 422 linked_payment_immutable -> expected_revision not the latest
   409 stale_revision -> new amount below refundedAmount 422 refund_exceeds_payment. This mirrors forge's single Correct.
5. Settlement completeness, 422 incomplete_settlement (any member of a settlement named, not every member named). Every
   touched settlement is checked for completeness first.
6. Identical effective instants of the members of each touched settlement (compared as instants, any offset spelling),
   else 422 validation_failed. Sits with the completeness class, after every completeness check (D-B1, risk).
7. Current affordability by the combined net per wallet: net = sum over items of (+delta to the payee, -delta to the payer);
   a wallet with net < 0 needs Available(wallet) + net >= 0, else 409 insufficient_funds. A wallet one item credits and
   another debits is judged on the net. Held funds do not count (Available = balance - holds).
8. Every new revision is applied, then overdrawnInThePast runs for the sender and receiver of every item (total and available
   at every effective/event boundary, movements sharing an instant combined); any failure rolls everything back (balances,
   revisions, nothing else was touched) and answers 409 historical_overdraft.

A rejected batch changes nothing: /_test/export is byte-identical (balances, revisions, idempotency records, id counters,
sessions). The batch id (st.NewID("cb")) and the clock are taken only after every check passed.

## Decisions on points the spec leaves open

- D-B1 The identical-instant rule is 422 validation_failed (the spec names that code) and is placed with the settlement
  completeness class: completeness for all touched settlements first, then instants. Reason: the spec lists "settlement
  completeness" as one precedence step between item errors and funds and gives no separate step to the instant rule.
  KNOWN_RISK: a reference that checks the instants first (or per settlement) answers validation_failed where we answer
  incomplete_settlement for a batch that is both incomplete and has unequal instants.
- D-B2 Array-level shape errors (including a missing payment_id and duplicate ids) precede item errors, so a duplicate id
  after an unknown payment is 422 and not 404. The spec states the 1..32 distinct-ids rule before the per-item rules.
- D-B3 Item errors are returned in input order across classes: item 0 unknown (404) beats item 1 with a bad amount (422).
  The brief and the spec ("item errors in input order") say so; within one item validation comes first.
- D-B4 recorded_at: one instant per batch = the operation's stamp (ReadNow, which is never earlier than the previous write
  plus 1 microsecond), raised to (latest recorded_at of every member + 1 microsecond) so each member's new recorded_at strictly
  increases even when an imported revision was recorded ahead of the clock (the stage-3 L1 case). All new revisions share it.
  The clock (lastStamp) only moves when the batch succeeds, to max(stamp, recorded_at): a read that begins after the batch sees it.
- D-B5 correction_batch_id is "cb_N" from st.NewID, persisted in the export (seq["cb"]); ReindexAt also reserves every imported
  revision's batch id so an export whose id counters were lost never re-issues one (tested by dropping `seq`).
- D-B6 Revision.correction_batch_id is null (not omitted) on every non-batch revision, including revision 1, imported old
  revisions and the 201 of a single POST /payments/{id}/corrections. Stored idempotent bodies written before this stage are
  not rewritten. Three stage-3 test expectations changed accordingly (correct_test.go, handlers_history_test.go, upgrade_test.go;
  edited by another seat; when e3eb44c was committed those three edits were still uncommitted in the shared tree, so e3eb44c
  alone fails four stage-3 expectation tests until they are committed).
- D-B7 correction_batch_id is not added to statement entries (spec silent; statement entries keep payment, delta, balance_after,
  revision, effective_at, recorded_at).
- D-B8 Statement snapshots are not part of the export, as in the accepted stage 3 (State.snaps is "never serialised, dropped by
  reset/import"; the stage-3 test statement_test.go:500 asserts snapshot 404 after import). The real stage-1/2/3 exports contain
  no snapshot, so there is nothing for a stage-4 import to retain or to re-serve in an original form; the "original form" of a
  stage-3 statement is the frozen page of the same service, which the batch does not touch (tested: pages before and after a
  batch are byte-identical). KNOWN_RISK, the most likely place for a spec-literal disagreement: stage-4.md says an import
  "retains ... snapshots". If route reads that as "a stage-4 export -> import keeps statement tokens", snapshots must be added
  to the export (statement.go and snapshot.go, about 60 lines, plus changing the stage-3 expectation at statement_test.go:500);
  I did not do it because it is new behaviour the accepted stage 3 explicitly tests the opposite of, and it makes every
  export grow with every statement read.
- D-B9 Refund payments are never settlement members (settlement_id null), so a batch over a settlement names only its original
  members; a member that has been refunded can be corrected in a batch down to, not below, its refunded amount.
- D-B10 A batch may touch payments of any user (the operator need not be a party); the revisions endpoint stays readable only by
  the two parties of a payment (stage 3), so the operator reads the new revisions from the batch response.
- D-B11 No new import code was needed for stages 1-3: the existing migration (trMigrateHistory) already gives stage-1/2 exports
  their history, and a stage-3 export gains exactly `refund_of: null` on payments and `correction_batch_id: null` on revisions
  (asserted by deep equality in TestBatchOnImportedOlderExports/stage3-export.json).

## Evidence

- go-full-suite.txt, go-test-batch-verbose.txt: gofmt, vet and the full suite at the implementation commit.
- batch_blackbox.py + blackbox-run.txt: a stage-4 binary built from `git archive e3eb44c`, driven over HTTP with exports written by
  binaries built from git at 0024598 (stage 1), f33035a (stage 2) and 5e6f83f (stage 3), regenerated for this run with
  stage-4/testdata/gen_stage{1,2,3}_export.go: 18 checks per export, all pass.
- mutation-check.txt: eight deliberate faults in a throwaway copy; every one is caught by a batch test (after adding the
  rollback case that the first run missed).

## Not tested / assumptions

- `go test -race` is unavailable on this host (CGO_ENABLED=0, no C compiler): the concurrency tests ran without the race
  detector. Everything runs under the one Store mutex; there is no shared state outside it.
- Hold timelines at batch level are covered by one case (funding arrives after a hold exists); the general hold boundary logic is
  the stage-3 overdrawnInThePast shared with Correct.
- Tests use dates in September 2026 as past instants, as the existing suite does; a host clock before 2026-09-27 would make
  effective_at "in the future".
- Settlement operators other than the first (several operators in one fixture) share no idempotency state by design (keys are per
  user); not exercised.
