# Stage 4 requirement ledger (pocketful)

Spec: D:\project\dolphin-tank\dark-factory-wearedevs\pocketful\spec\stage-4.md
SPECIFICATION_HASH (sha256 of exact file bytes read): 1894b002f8827fd36623df4ecf3deb204e20d7fafbbfa671894a114db80e6df1 (4449 bytes, 71 lines)
Stage 1 rows R01..R90, stage 2 rows S01..S66 and stage 3 rows T01..T65 continue to apply; stage-4 is a superset (re-run stage-1/2/3 jury scripts on the stage-4 image where they still apply). Stage-4 adds no written UI requirement; the operator's run brief adds the browser rules (rows B01..B12).
Owners: F=forge (refund domain, Correct changes, Payment.refund_of), T=trace (batch domain and handler, Revision.correction_batch_id, import/export migration, concurrency and attacks), L=loom (refund HTTP handler and parser, refund UI, visual quality, Dockerfile/RUN.md, UI regression), J=jury.
Check column: F-unit = Go unit test in stage-4/, HTTP = black-box request against the running image, UI = real-browser script, ATK = cross-seat attack.

## Refunds and corrected history
| Id | Statement | Observable property | Check | Owner |
|---|---|---|---|---|
| U01 | POST /payments/{payment_id}/refunds, body {"amount": n}, requires an idempotency key | missing/invalid key rejected as for other writes; same key+body replays | HTTP | L,F |
| U02 | Only the original receiver may refund, else 403 forbidden; unknown payment 404 | sender, third party, operator-not-receiver 403; no token 401; unknown id 404 | HTTP | F,L |
| U03 | Target may be a direct payment, request payment or capture; never a refund | refund of direct, request payment, capture each 201; of a refund 422 invalid_refund_target | HTTP | F |
| U04 | Invalid amount is 422 validation_failed | non-integer, <= 0 (as stage-1 amounts), > 1e9, missing, wrong type | HTTP | L,F |
| U05 | Cumulative refunds may not exceed the payment's current corrected amount: 422 refund_exceeds_payment | several partial refunds up to exactly the amount ok, one more unit 422; after a correction the limit is the corrected amount; corrected to 0 refuses all | HTTP+F-unit | F |
| U06 | Refund of a refund is 422 invalid_refund_target | receiver of a refund (original sender) gets 422 | HTTP | F |
| U07 | A refund is a new payment in the opposite direction with refund_of = target id, request_id null, authorization_id null, original note and visibility | body fields; feed visibility follows original (public refund appears in /activity, private does not) | HTTP | F |
| U08 | 201 with that payment; replay 200 with the original body | replay identical bytes after later refunds/corrections; different body same key 409 idempotency_key_reuse | HTTP | L,F |
| U09 | Refund moves existing money from the receiver's available funds, else 409 insufficient_funds, atomically | receiver whose funds are held or spent gets 409 and no change; balances sum preserved | HTTP+F-unit | F |
| U10 | Refunds never reopen a request or authorization or restore a released hold | request stays paid, capture's authorization status/held unchanged after refund | HTTP | F |
| U11 | Other payments have refund_of: null | every payment-returning endpoint (payments, requests pay, splits, settlements, captures, activity, statement entries, revisions parent) carries refund_of null; refunds carry the id | HTTP | F,L |
| U12 | Stage-3 corrections remain available for ordinary direct/request payments | stage-3 correction scripts still pass | HTTP | F |
| U13 | Captures and refund payments cannot be corrected: 422 linked_payment_immutable | correct a capture, a refund payment | HTTP | F |
| U14 | A correction cannot reduce a payment below its already-refunded amount: 422 refund_exceeds_payment | reduce to exactly refunded ok, below 422, state unchanged | HTTP | F |
| U15 | Correction debits are checked against available funds | decrease debits the receiver: receiver with funds held gets 409 insufficient_funds | HTTP | F |
| U16 | Refund payment appears in /me balance, /activity, statements (both parties) as a normal payment with its own created_at and revision 1 | statement entries, as_of views, known_at views include refunds | HTTP | F,T |

## Batch corrections
| Id | Statement | Observable property | Check | Owner |
|---|---|---|---|---|
| U20 | POST /correction-batches requires a settlement operator and an idempotency key; same 401/403 rules as settlements | no token 401; non-operator 403; operator without key rejected like settlements | HTTP | T |
| U21 | corrections has 1..32 objects with distinct payment_ids, else 422 validation_failed | 0, 33, duplicate id, non-array, non-object element, missing field | HTTP | T |
| U22 | Every item has the ordinary correction fields and validation | expected_revision positive int, amount int 0..1e9, effective_at RFC 3339 with offset not later than now, reason 1..200 chars | HTTP | T |
| U23 | Unknown payment 404; stale expected revision 409 stale_revision | item index order respected | HTTP | T |
| U24 | Operator may correct ordinary, request and settlement payments of any user; captures and refunds stay immutable | 422 linked_payment_immutable for capture/refund items | HTTP | T |
| U25 | Correcting any settlement member requires every member of that settlement, else 422 incomplete_settlement | all members ok; one missing 422 | HTTP | T |
| U26 | Members of one settlement must have identical effective instants (offset spellings may differ), else 422 validation_failed | same instant in +00:00 and +02:00 spelling accepted; different instants 422 | HTTP | T |
| U27 | Ordinary single-payment corrections remain available for nonmembers; settlement members still refused singly | single correction of non-member ok; of a member 422 linked_payment_immutable | HTTP | T,F |
| U28 | Unknown fields are ignored | extra keys in body and items accepted | HTTP | T |
| U29 | Error precedence: item errors in input order, settlement completeness, current available funds, then historical total/available at every boundary | batches with two simultaneous faults return the earlier class; first failing item in input order | HTTP | T |
| U30 | Existing codes apply: linked_payment_immutable, refund_exceeds_payment, insufficient_funds, historical_overdraft | each produced by a batch | HTTP | T |
| U31 | Affordability is by the combined effect of all proposed revisions | batch whose decrease of one payment funds the increase of another passes; net shortfall 409; a single wallet's net effect, not item by item | HTTP | T |
| U32 | A rejected batch leaves history, balances and idempotency records unchanged | /export before == after for every failure class; same key retried after a rejection can succeed | HTTP | T |
| U33 | 201 with correction_batch_id, recorded_at and revisions in input order | body shape and order | HTTP | T |
| U34 | All new revisions share recorded_at, strictly later than the previous recorded_at of every member; each revision exposes correction_batch_id | recorded_at equal across revisions, > every member's earlier rev; revisions endpoint shows the id (null for non-batch revisions) | HTTP | T |
| U35 | Effective times cannot be later than now | future effective_at 422 | HTTP | T |
| U36 | Original payments and receipts never change; original payment and settlement retries return original bodies | replay of earlier payment/settlement keys byte-identical after a batch | HTTP | T |
| U37 | New statements reflect the new revisions; earlier snapshot tokens keep paging their frozen entries | snapshot before batch unchanged after | HTTP | T |
| U38 | Replays return the original batch response with 200 | same bytes; different body 409 idempotency_key_reuse | HTTP | T |
| U39 | A settlement payment may be refunded under the existing refund rules; refunds never change settlement membership | refund of a settlement member 201; refund payment has settlement_id null; settlement members unchanged; batch completeness counts original members only | HTTP | F,T |
| U40 | Concurrent corrections sharing any expected payment revision cannot both succeed | N parallel batches/single corrections on overlapping payments: exactly one wins per shared revision; sum of balances preserved | HTTP+ATK | T |
| U41 | A stage-4 service accepts exports from the same team's stages 1-3, retaining settlement membership, corrections and snapshots; its own export imports back | real stage-1, stage-2, stage-3 (5e6f83f) exports imported; settlements, revisions, snapshot tokens page the same entries; stage-4 export with refunds and batches round-trips byte-identical | HTTP | T |
| U42 | Ten idempotent write paths: payments, requests, request pay, split, settlement (stage 1), authorization, capture (stage 2), correction (stage 3), refund, correction batch | each path replays 200 identical, key reuse 409, concurrent same key exactly one effect | HTTP | J |
| U43 | Stage 1-3 behaviour keeps working | stage-1/2/3 jury scripts and harness | HTTP | J |

## Browser product (operator brief; no new written spec rule)
| Id | Statement | Check | Owner |
|---|---|---|---|
| B01 | Coherent, responsive 375 px phone to desktop, no horizontal scrolling | UI scroll width at 375/768/1280 | L,J |
| B02 | Clear empty, loading, error, refused and uncertain states | UI | L,J |
| B03 | Stale-state, lost-response and refused-payment recovery paths keep working | UI (stage-2/3 scripts) | L,J |
| B04 | Stage 3 export then stage 4 import upgrade path in the browser (session kept, pending request payable, lost payment retryable) | UI | L,J |
| B05 | Visible labels, visible keyboard focus, sufficient contrast | UI | L,J |
| B06 | Palette canvas #030014, surface #060317, raised #10093a, text #f4f0ff, secondary #a8a6b7, one accent #9382ff | CSS inspection | L,J |
| B07 | Headings DM Sans 500, body Inter 400/500, bundled in image, never a weight above 500 | computed styles, no network | L,J |
| B08 | Radii controls 5 px, cards 16 px, badges 32 px; depth from inset rim light, no drop shadows | CSS inspection | L,J |
| B09 | No red/green status signalling; label, glyph and opacity instead | UI | L,J |
| B10 | Available funds is the headline number; no stock imagery, mascots, large gradient fills | UI | L,J |
| B11 | Builds and serves from a clean container with no outbound network at run time | docker run --network none | J |
| B12 | Refund control for a received payment with loading, refused, uncertain and success states (route decision: the spec states no control; the capability is user-facing) | UI | L,J |

Route decisions (not spec rows): refund amount follows the stage-1 payment amount range; single-correction error order puts refund_exceeds_payment after stale_revision (forge records the final order in evidence/stage-4/decisions.md); the identical-instant settlement check sits with the settlement-completeness class (trace records it).
