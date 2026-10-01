# Stage 3 requirement ledger (pocketful)

Spec: D:\project\dolphin-tank\dark-factory-wearedevs\pocketful\spec\stage-3.md
SPECIFICATION_HASH (sha256 of exact file bytes read): 2255d3f2181c22dc6eac6919bf7712197d812248bd9de8a7e59260ede6056e54 (10288 bytes, 177 lines)
Stage 1 rows R01..R90 and stage 2 rows S01..S66 continue to apply; stage-3 stays a superset (re-run stage-1/2 jury scripts on the stage-3 image where they still apply). The spec has NO new UI requirement: the browser product must keep working unchanged (balance = current corrected values, feed shows original payments) and survive the stage-2 export -> stage-3 import upgrade.

Owners: F=forge (domain model, revisions, corrections, hold timeline, history primitives), T=trace (statement, snapshots, fixture/import migration, settlement, time/concurrency attacks), L=loom (HTTP routes, query parsing, UI regression, Dockerfile/RUN.md), J=jury.
Check: H=shipped harness, G=jury gap check (API), B=jury real-browser check, U=implementer test.

| ID | Spec § | Normative statement | Observable property | Owner | Check |
|---|---|---|---|---|---|
| T01 | intro | Stage 1 and 2 requirements continue to apply | Stage-1/2 behaviour unchanged with no corrections | all | G/H |
| T02 | ts | Every payment `created_at` is an RFC 3339 instant with offset (when money moved); every endpoint returning a payment includes it | Payment bodies on pay, request pay, capture, settlement, activity, statement, revisions | F | G |
| T03 | ts | `GET /activity` keeps ordering by `created_at` (newest first) | Seeded out-of-insertion-order created_at appear sorted | F | G |
| T04 | ts | Seeded payments may supply `created_at`; omission uses reset time, before later API payments | Seed with/without; later pay sorts after | T | G |
| T05 | ts | Seeded `created_at` in the future -> 422 validation_failed from reset, no state change | Reset rejected, prior state intact; bad format also 422 | T | G |
| T06 | ts | Fixture `balance` stays the balance after all seeded payments; loading payments must not change it | /me after reset with payments equals seeded balance | T | G/H |
| T07 | me | `GET /me?as_of=<RFC3339 with offset>` optional; naive time, bare date, empty -> 422 | Each invalid form 422 | L,F | G |
| T08 | me | Without temporal params /me keeps the existing money fields and reports current corrected values | Shape unchanged; balance reflects corrections | F | G |
| T09 | me | With as_of: balance after every payment of the caller with created_at/effective <= as_of, before every later one; payment exactly at as_of counts | Boundary at, 1us before, after | F | G |
| T10 | me | as_of at/after latest payment -> current balance; before earliest -> opening balance (what the wallet held before anything moved) | Far future, far past | F | G |
| T11 | me | Response echoes `as_of` exactly as given (e.g. +02:00 offset kept) | String equality | L,F | G |
| T12 | stmt | `GET /statement?from&to&limit&offset`; from default = opening of wallet, to default = now; limit/offset as GET /requests (422 on bad values) | Defaults, invalid values | T,L | G |
| T13 | stmt | Returns payments the caller sent or received in half-open window [from,to), oldest first, each with delta and balance_after | Window edges (from inclusive, to exclusive) | T | G |
| T14 | stmt | Response keys: opening_balance, entries[{payment,delta,balance_after,...}], closing_balance, has_more | Shape | T | G |
| T15 | stmt | Entries ordered by created_at/effective_at ascending, then payment id ascending for ties | Same-instant payments ordered by id | T | G |
| T16 | stmt | opening_balance = balance immediately before `from`; closing_balance = balance immediately before `to` | Compare with /me?as_of | T | G |
| T17 | stmt | opening + sum(delta over full window) == closing; sent negative, received positive | Arithmetic over several windows | T | G |
| T18 | stmt | Pagination does not change balance_after, opening, closing: they describe the full window regardless of limit/offset | Page through, compare | T | G |
| T19 | stmt | Only payments sent/received by the caller appear (public payments of others excluded; feed visibility rules do not apply: private own payments appear) | Third-party public, own private | T | G |
| T20 | bitemp | Every payment has a revision history; revision 1: amount as paid, effective_at = recorded_at = created_at | GET revisions of fresh payment | F | G |
| T21 | bitemp | Seeded payment's supplied created_at is its original recorded/effective time; omission = reset time | Revisions of seeded payment | F,T | G |
| T22 | bitemp | Opening balances = seeded ending balance minus net effect of original seeded payments; corrections never change them; new accounts open at zero | as_of before all payments; after corrections; signup user | F,T | G |
| T23 | corr | `POST /payments/{id}/corrections` needs idempotency key (400 missing) and the original sender; non-sender (incl receiver) 403 forbidden; unknown 404; no token 401 | Matrix | L,F | G |
| T24 | corr | Body fields expected_revision, amount, effective_at, reason all required; expected_revision positive integer; amount integer 0..1e9 (0 reverses whole payment); reason string 1..200 chars; effective_at RFC3339 instant not later than now; invalid -> 422 validation_failed | Each field missing/wrong/boundary; future effective_at | F,L | G |
| T25 | corr | Correction changes neither parties nor visibility; appends immutable revision; 201 with payment_id, revision, amount, effective_at, recorded_at (server-assigned), reason | Response shape | F | G |
| T26 | corr | Recorded times for one payment strictly increase (back-to-back corrections) | Several corrections in <1 ms apart | F | G |
| T27 | corr | Stale expected revision -> 409 stale_revision | Reuse revision number | F | G |
| T28 | corr | Replay (same key+body): 200 with the original revision even after newer revisions; different body same key -> 409 idempotency_key_reuse; claimed key beats validation | Replay after revision 3 | T,F | G |
| T29 | corr | Difference between new and previous amount moves between the same two wallets in the same atomic step; increase debits original sender; decrease debits original receiver | Balances before/after | F | G |
| T30 | corr | Currently unaffordable debit -> 409 insufficient_funds (evaluated against available) | Receiver spent funds then decrease; sender short then increase | F | G |
| T31 | corr | Otherwise a corrected balance negative at any effective-time boundary (combined effect of all movements at that instant) -> 409 historical_overdraft | Back-dated reversal making an earlier boundary negative; two movements at same instant netting nonnegative OK | F | G |
| T32 | corr | Either failure preserves balances, revision history, statements, idempotency state (key reusable after failure) | State identical before/after; same key reused | F,T | G |
| T33 | corr | Sum of balances equals seeded total in every historical view | Sum over users at several as_of/known_at | F,T | G |
| T34 | corr | Original payment and every original idempotent response unchanged; GET /activity keeps displaying the original payment; correction records are not feed payments | Activity before/after; replay original pay | F | G |
| T35 | corr | `GET /payments/{id}/revisions` returns {"revisions":[...]} in revision order incl revision 1 (reason ""); only the two parties; third party 404 even if public; no token 401; unknown 404 | Matrix | F,L | G |
| T36 | known | `GET /me` and `GET /statement` accept optional `known_at` (RFC3339 with offset; future allowed); invalid/empty -> 422; echoed exactly as supplied | Forms and echo | L,F,T | G |
| T37 | known | Per payment select the latest revision recorded at or before known_at; none recorded yet -> contributes nothing; omission = everything known when the read begins | Known_at between revisions, before payment | F | G |
| T38 | known | Selected revisions applied by their effective times; as_of inclusive; statement half-open; both may be in the future | Matrix of (as_of, known_at) | F,T | G |
| T39 | known | Statement ordering by selected effective_at then payment id; entries add selected revision, effective_at, recorded_at; payment.amount is the selected amount; zero-amount revisions appear with zero delta | Corrected payment moved/reversed | T | G |
| T40 | known | A correction is never counted alongside the revision it replaces; with no corrections and no known_at behaviour unchanged | No double count | F,T | G |
| T41 | snap | First GET /statement also returns opaque `snapshot` token freezing selected revisions, window, balances, entries and default `to` | Token present on first call | T | G |
| T42 | snap | `GET /statement?snapshot=<t>&limit&offset` pages that exact result after later payments or corrections | Pay+correct then page | T | G |
| T43 | snap | Only limit/offset may accompany a snapshot; from/to/known_at with it -> 422 validation_failed | Each combo | T,L | G |
| T44 | snap | Unknown token, another user's token, token from before reset -> 404 not_found; tokens last until reset | Matrix incl reset | T | G |
| T45 | snap | Paging changes neither balances nor entries; final partial page and offsets beyond end report has_more correctly | Last page, offset > n | T | G |
| T46 | snap | Unrecognized query params ignored | Extra params | L | G |
| T47 | snap | A correction may move a payment into/out of a statement window; existing snapshots unchanged under concurrent payments/corrections | Concurrent writers + paging | T,F | G |
| T48 | snap | Concurrent corrections with the same expected revision cannot both succeed | N-way race: exactly one 201 per revision | F | G |
| T49 | settle | Stage-1 settlements keep original receipts and privacy; each member's original revision effective=recorded=committed_at | Revisions of members | T | G |
| T50 | settle | Single-payment corrections reject settlement members with 422 linked_payment_immutable | Correct a member | F | G |
| T51 | upgrade | Stage-3 accepts exports from the same team's stage-1 or stage-2 service; ledger imports and accounts for authorizations and captures | Real stage-1 and stage-2 exports imported; /me as_of, statement, revisions work | T | G/B |
| T52 | upgrade | Captures are immutable linked payments: correcting a capture -> 422 linked_payment_immutable | Correct a capture | F | G |
| T53 | holds | `/me?as_of=T&known_at=K`: balance=total, available=total-held for that same view | Four fields consistent | F | G |
| T54 | holds | Hold starts at authorization creation; nonfinal capture reduces it at capture time; final capture/void/expiry release the remainder at that event's time; expiry at expires_at | held at times around each event | F | G |
| T55 | holds | Events other than clock expiry are known at their server event time; once creation is known the expiry deadline is known; beyond now an open hold expires at its deadline; without as_of use request start | known_at before void -> still held; future as_of after deadline | F | G |
| T56 | holds | Authorizations expose `closed_at` (null while open; event time when closed) | Open/captured/voided/expired bodies and list | F | G |
| T57 | holds | Historical total follows effective/recorded-time rules; correction rejected 409 historical_overdraft if total or available negative at any past effective/event boundary under latest known revisions; current unaffordable debits take precedence as insufficient_funds | Hold-caused available underflow at past boundary | F | G |
| T58 | holds | Seeded open holds assumed created at reset unless created_at supplied; seeded closed holds need not reconstruct a lifecycle | Seed with and without created_at | T | G |
| T59 | holds | Statement is money movements only (authorize/release/expire are not payments); captures appear exactly once with their links | Statement after authorize+capture+void | T | G |
| T60 | holds | Old snapshots unchanged after any lifecycle action or correction | Snapshot, authorize/void/correct, page | T | G |
| T61 | conc | Concurrent requests behave as some sequential order; invariants hold at every read (stage 2 S63 extended: corrections, statements, snapshots) | Storm + observers (sum constant, balances >= 0, available >= 0, opening+deltas=closing) | all | G |
| T62 | deploy | stage-3 folder: source, Dockerfile, RUN.md; builds and serves from a clean container, no outbound network; fonts/scripts/styles inside image | Internal-network drive, no external URLs | L | G/B |
| T63 | user | stage-1 and stage-2 folders untouched; nothing from stage 4; no nested .git | diff vs accepted commits | route,J | route |
| T64 | user | Browser product unchanged in quality (stage-2 visual direction, 375px to desktop, states, focus, contrast); stale-state, lost-response, refused-payment recovery paths and stage-2 export -> stage-3 import upgrade (session kept, pending request payable, lost payment retryable) still work | Stage-2 browser scripts re-run on stage-3 image | L,J | B |
| T65 | contract-decision | Spec-silent choices recorded in the work orders (microsecond timestamps for payments/recorded_at, id ordering, statement from>to) | see pf3-common DECISIONS | route | J |
