# jury requirement ledger - pocketful stage 2 (written from stage-2.md BEFORE reading any source)

Spec: stage-2.md sha256 39aaf9d7743c6fd831663e5b8363866f7d70795e5efb9000c2803f471397b13f (verified against the file on disk),
stage-1.md sha256 65497dea09a8b432598c71662320cf66c3550e183cfd76e2d7f97318e0d30aa4 (verified).
Columns: id | normative statement (spec section) | property implied | demonstrating check | verdict + evidence. Rows were written before any source was read; verdicts filled after the runs.

## A. API - money model

| id | statement | property | check | verdict |
|---|---|---|---|---|
| A01 | Sum of all `total` equals seeded total; a hold moves no money (Authorizations 1) | conservation under authorize/capture/void/expiry/pay/settle, concurrent | s2_conserve (concurrent observer, 3 runs) | PASS - s2_lifecycle (6 conservation reads), s2_race x5 clean runs (credit-first/debit-first observers, final reconcile), s2_export under 12 writers, b4_upgrade (sum 15500) |
| A02 | `available = total - held` never negative; held funds cannot fund payments, authorizations, settlement net debits; captures may spend reserved funds (2) | boundary: pay of exactly available OK, available+1 refused; capture of held succeeds although available==0 | s2_funds | PASS - s2_funds (available 0 refuses 1 unit, exact available accepted, capture of reserved funds at available 0), s2_race H02 boundary, b2_wallet UI |
| A03 | Cumulative captures <= authorized; each idempotent capture moves money once; closed hold cannot be captured again (3) | no over-capture under race; replay one effect | s2_lifecycle, s2_race | PASS - s2_lifecycle, s2_idem (24-way capture, 20 distinct-key default captures: 1 success), s2_race (40x100 captures -> exactly 10; 20x300 -> 3) |
| A04 | `GET /me` keeps `balance`, `balance == total`, adds `available`, `held`; no holds => all agree, held 0 (API) | shape + identity at every read incl. under load | s2_me, s2_conserve | PASS - s2_lifecycle shape; inv() (balance==total, held+available==total, available>=0) on every /me read in s2_race observers (4 threads x 5 runs) |
| A05 | `POST /payments` immediate, no intermediate hold, no capture needed | payment never creates an authorization / held funds | s2_funds | PASS - s2_funds: payment moves money at once, no hold/authorization created |
| A06 | Every `409 insufficient_funds` (payments, request pay, settlements) evaluated against `available`; authorizations too | each of 4 paths blocked by holds, unchanged state, no payment created | s2_funds | PASS - s2_funds: payments, request pay (stays pending, refused unchanged), settlements (net-debit rule, exact boundary, net-zero cycle), authorize; s2_fixture seeded holds; b2/b3 UI |
| A07 | `POST /splits` unchanged (stage 1 shares, no balance check) | splits still 201 with holds present, rounding table | s1 regression + s2_funds | PASS - s2_funds split with available 0 (334/333/333), stage-1 c07 98/98 |
| A08 | Seven idempotent paths; replay rules independent per path (API) | all stage-1 replay rules on authorize and capture | s2_idem | PASS - s2_idem + s2_errors on both new paths (key required/empty/255/256, replay, reuse, claimed-key-beats-validation, failed key reusable, per-user, per-path, concurrent x3 rounds, 3 runs) |

## B. API - fixture model

| id | statement | property | check | verdict |
|---|---|---|---|---|
| B01 | `authorization_ttl_seconds` defaults to 600 when omitted; supplied must be positive integer; else 422 | omitted->600 (expires_at-created_at); 0,-1,"x",1.5,true,null,[],{} -> 422 `validation_failed` and state unchanged; 1 ok; large ok | s2_fixture | PASS with NOTE - omitted->600, 1/3600/86400/1e9 ok, 0/-1/x/'600'/1.5/true/false/null/[]/{}/0.0 -> 422 with state unchanged (s2_fixture run2 84/84). NOTE: ttl > 1e9 (e.g. 2^31) is rejected 422 although the spec says only 'positive integer' (no upper bound stated); no 5xx for 1e9+1..2^64 (logs/s2_fixture.run1-ttl-2pow31-note.log) |
| B02 | `balance` seeded is total; `available` derived, never seeded (Model) | seeded available/held ignored; /me derives | s2_fixture | PASS - s2_fixture (seeded users[].available/held ignored, derived) |
| B03 | Seeded unexpired open holds summing above balance -> 422, nothing changed | boundary: == balance accepted, balance+1 rejected; previous state intact; expired/captured/voided holds do not count | s2_fixture | PASS - s2_fixture: sum==balance accepted, +1 rejected 422 with old token/state intact, expired/captured/voided/clock-expired holds do not count, payers do not pool |
| B04 | Seeded status open/captured/voided/expired; only open holds | each status reads back; only open held | s2_fixture | PASS - s2_fixture: open/captured/voided/expired read back, only open holds, filters, closed seeded capture 409 |
| B05 | Omitted `authorizations` => empty list | stage-1 fixture accepted | s2_fixture | PASS - s2_fixture/stage-1 fixtures |
| B06 | Seeded `expires_at` at or before now => expired (holds nothing); seeded expiries at least an hour from reset time, past or future | seeded past -> status expired, held 0; future -> open | s2_fixture | PASS - s2_fixture: past open -> expired holds nothing, future open holds, expires_at echoed RFC3339 |
| B07 | Reset: 204, replaces all state incl. authorizations/idempotency | reset clears holds and keys | s2_fixture | PASS - s2_fixture: reset clears holds, keys, tokens; malformed seeded authorizations (7 kinds) -> 422, no 5xx, state unchanged |

## C. API - expiry (real clock)

| id | statement | property | check | verdict |
|---|---|---|---|---|
| C01 | `expires_at` at or before now => `expired`, holds no funds, reflected by reads and writes even if no request at deadline | ttl=1or2, wait, first request after deadline: /me available restored, list shows expired, capture 409 authorization_expired (or authorization_not_open per stored/clock rule), void 409 authorization_not_open, never open in filter status=open | s2_expiry | PASS - s2_expiry x3 (ttl 2): /me, list, capture (409 authorization_expired), void (409 authorization_not_open), pay of released funds, authorize, settlement - each as the FIRST request after the deadline; b6 UI |
| C02 | `GET /authorizations` shows `status: "expired"` for clock-expired; filter `status=expired` matches, `open` does not | filter both ways | s2_expiry | PASS - s2_expiry: status=expired matches, status=open never, expired remaining 0 |
| C03 | Expiry of partially captured hold releases only the remainder, keeps captures | partial capture final:false, expire, available = total - nothing held, payment_ids preserved | s2_expiry | PASS - s2_expiry: partial capture then expiry releases only remainder, payment_ids/captured_amount kept |
| C04 | `expires_at = created_at + ttl`, RFC 3339 with explicit offset | arithmetic | s2_lifecycle | PASS - s2_lifecycle: expires_at = created_at+600s, RFC3339; s2_expiry ttl 2/1; s2_fixture ttl 1/3600/86400/1e9 |

## D. API - POST /authorizations

| id | statement | property | check | verdict |
|---|---|---|---|---|
| D01 | Key required; caller is payer; 201 body per example incl. `captured_amount:0`, `payment_id:null`, `status:open`, `expires_at`, `created_at`, from/to handles, `remaining_amount` | shape | s2_lifecycle | PASS - s2_lifecycle |
| D02 | `note`/`visibility` optional, defaults as POST /payments ("" / public) | defaults | s2_lifecycle | PASS - s2_lifecycle |
| D03 | error table: available < amount -> 409 insufficient_funds; amount <1, >1e9, non-integer -> 422; own handle -> 422 self_payment; note >200 or visibility invalid -> 422; unknown handle -> 404 | each row, boundaries (1, 1e9, 1e9+1, 0, 1.5, "5", true, 1e3 ok), note 200/201 | s2_validation | PASS - s2_errors (17 refusal rows, boundaries 1/1e9/1e9+1, 1000.0/1e3, note 200/201, unicode note) |
| D04 | Open authorization never in `GET /activity` | absent for payer, receiver, stranger (public and private) | s2_lifecycle | PASS - s2_lifecycle + s2_fixture (open holds never in activity) |
| D05 | Funds reserved immediately: authorize 2000 of 10000 -> available 8000 held 2000 total 10000 | /me | s2_lifecycle | PASS - s2_lifecycle |

## E. API - capture

| id | statement | property | check | verdict |
|---|---|---|---|---|
| E01 | Key required; only receiver captures | 400 missing key, 403 payer, 403 stranger | s2_errors | PASS - s2_errors |
| E02 | `amount` optional, defaults to remaining; replay needs identical body; `{}` vs `{"amount":2000}` reuse -> 409 idempotency_key_reuse | idem | s2_idem | PASS - s2_idem |
| E03 | 201 payment in `POST /payments` shape, `authorization_id` set, `request_id:null`, amount=captured, note/visibility copied, in activity by ordinary rule | shape; private not visible to stranger; payments elsewhere `authorization_id:null` (payments, request pay, settlement members) | s2_lifecycle | PASS - s2_lifecycle (shape, authorization_id, request_id null, note/visibility copied, feed visibility; payments/request-pay/settlement members authorization_id null) |
| E04 | Default: becomes `captured`, `captured_amount`, `payment_id`; releases remainder immediately (1500 of 2000 returns 500 to available in same step) | /me right after capture | s2_lifecycle | PASS - s2_lifecycle |
| E05 | Second capture after final -> 409 `authorization_not_open` | | s2_lifecycle | PASS - s2_lifecycle |
| E06 | `final:false`: stays open while remainder; further captures up to remainder; capturing whole remainder closes even with final:false; final capture closes and releases | state machine incl. final:false for whole remainder -> captured, held 0 | s2_lifecycle | PASS - s2_lifecycle (final:false, whole remainder closes, final capture releases, omitted amount) |
| E07 | `capture_exceeds_authorization` compared to remaining; omitted defaults to remaining; `captured_amount` cumulative; `payment_id` latest; `payment_ids` ordered; `remaining_amount` on every authorization response (zero closed) | list/get/void/capture/create | s2_lifecycle | PASS - s2_lifecycle, s2_list, s2_race |
| E08 | Void/expiry of partially captured releases only remainder, preserves all capture records | void after partial: held 0, payment_ids kept, captured_amount kept, status voided | s2_lifecycle | PASS - s2_lifecycle (void after partial), s2_export (void of imported partial hold) |
| E09 | error table: not open -> 409 authorization_not_open; expired -> 409 authorization_expired; > remaining -> 422 capture_exceeds_authorization; amount <1 / non-integer -> 422 validation_failed; non-receiver 403; unknown 404 | each row | s2_errors | PASS - s2_errors, s2_expiry |
| E10 | New fields do not change idempotency body equality | capture replay body independent of response fields | s2_idem | PASS - s2_idem (replay after response fields exist), s2_export (replay on destination) |
| E11 | `final` boolean default true; non-boolean `final` | "false"/0/null -> 400 or 422 (spec: wrong JSON type = 400 malformed, invalid -> 422; either rejection acceptable but must not capture) | s2_errors | PASS - s2_errors: final non-boolean -> 400 malformed_request, nothing captured |

## F. API - void and list

| id | statement | property | check | verdict |
|---|---|---|---|---|
| F01 | Only payer voids, no key; 200 voided, hold released; void twice -> 200 current state; captured/expired -> 409 authorization_not_open | | s2_lifecycle | PASS - s2_lifecycle |
| F02 | 403 for caller who is not permitted party incl. strangers on capture and void; receiver on void 403; 404 unknown | | s2_errors | PASS - s2_errors (403 stranger on open and closed holds, receiver void 403, 404 unknown) |
| F03 | `GET /authorizations`: only caller's, newest first, direction outgoing/incoming/absent, status filter (4 values), clock-expired matches expired never open | | s2_list | PASS - s2_list (7 holds, 3 users, order, direction, status, combined) |
| F04 | limit/offset/has_more as `GET /requests`; invalid limit/offset/direction/status -> 422; `1e9`,`+4` -> 422 | | s2_list | PASS - s2_list (paging, has_more, 18 invalid query forms -> 422) |
| F05 | Unknown query params ignored | | s2_list | PASS - s2_list |
| F06 | 401 envelope with no/bad token on all new endpoints; 400 missing key vs 401 precedence (spec silent) | | s2_errors | PASS - s2_errors/s2_list (401 envelope). Precedence 401 vs 400 missing key is not decidable from the spec: not asserted |

## G. Idempotency on authorize + capture

| id | statement | property | check | verdict |
|---|---|---|---|---|
| G01 | replay same key+body -> 200 identical JSON value; effect once | | s2_idem | PASS - s2_idem |
| G02 | same key different body -> 409 idempotency_key_reuse | | s2_idem | PASS - s2_idem |
| G03 | claimed key beats validation (changed to invalid body -> 409) | | s2_idem | PASS - s2_idem (5 invalid bodies after a claimed key) |
| G04 | failed 4xx key reusable as first use | | s2_idem | PASS - s2_idem |
| G05 | scoped per user; same key different path not a replay | | s2_idem | PASS - s2_idem |
| G06 | 20+ concurrent identical with unused key: exactly one 201, rest 200 same body, one effect | | s2_idem (3 runs) | PASS - s2_idem x3 runs (24-way identical: one 201; 24-way two bodies: one winner, 12 reuse 409) |
| G07 | replay returns original response even after authorization changed (voided/captured/expired) and makes no state change | | s2_idem | PASS - s2_idem, s2_expiry, s2_export |

## H. Concurrency / invariants / export

| id | statement | property | check | verdict |
|---|---|---|---|---|
| H01 | Concurrent = some serial order; invariants hold at every read: sum totals constant, 0 <= available, held <= total, captured <= authorized | live observer during mixed storm | s2_conserve (3 runs) | PASS - s2_race x5 clean runs (2 further runs lost to infrastructure, logged), observers 4 threads, 12-worker random storm + reconcile |
| H02 | 50-way authorize/pay at available boundary | exactly floor(available/amount) succeed | s2_race | PASS - s2_race: 50-way authorize -> 33 ok/17 refused; mixed authorize+pay -> 33 total |
| H03 | capture storm: N concurrent partial captures of one hold with distinct keys, sum <= authorized | exactly the allowed ones succeed | s2_race | PASS - s2_race |
| H04 | void vs capture race | exactly one outcome per final state; money consistent | s2_race | PASS - s2_race (40 void-vs-capture races x 3 rounds, exactly one outcome each) |
| H05 | Export atomic under writers, import preserves holds/captures/replays/open expiry | s2_export | s2_export | PASS - s2_export x4 clean (holds, partial captures, replays, expired-after-import, 8 snapshots under 12 writers, re-import, garbage imports) + s2_export_expiry x4 |
| H06 | A stage-2 service accepts an export from stage 1 (Existing clients after an upgrade), tokens, pending requests, lost-payment retry | | s2_upgrade_api + browser upgrade | PASS - s2_upgrade_api (accepted stage-1 image -> stage-2) + b4_upgrade x3 |
| H07 | No 5xx anywhere; 50 in flight; per-request < 5s | | all | PASS - 0 5xx across every log; max latency 0.09 s; go test -race ok (45.6 s) |

## I. Browser / UI

| id | statement | property | check | verdict |
|---|---|---|---|---|
| I01 | Routes `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` reachable by URL (direct GET and reload) | each route renders its screen; unauth -> sensible | b_routes | PASS - b1_quality x3 (6 routes x 3 widths, signed-in and signed-out redirects), s2_list HTML routes |
| I02 | `Accept: text/html` on /requests and /authorizations -> UI; otherwise JSON incl. 401 envelope with no token | negotiation | s2_neg | PASS - s2_list (Accept matrix on /requests and /authorizations, POST unaffected) |
| I03 | signup/login testids, `auth-error` only when error; `current-user` (display name), `current-handle` (exact handle, no `@`), `logout-button` on every signed-in screen | | b_auth | PASS - b1_quality (signup/login/logout/errors via real forms; chrome on every signed-in screen) |
| I04 | `wallet-balance` exact formatted amount, `data-amount`; `100.00 EUR`, `1200 JPY`, 3-decimals BHD | | b_money | PASS - b1, b2 (100.00 EUR, 1200 JPY, 100.000 BHD, data-amount) |
| I05 | pay form: `15`,`15.00`->1500, `15.5`->1550, `15.005` rejected with NO request, nonnumeric rejected with NO request; error element shown | request log | b_pay | PASS - b2_wallet x2 (15, 15.00, 15.5 submit; 15.005, abc, empty, -5, 1,5, 15.123, 1e2 rejected with NO request; JPY/BHD rules; request/authorize/split forms) |
| I06 | pay form keeps values after success; resubmit unchanged sends no second payment, balance falls once, one feed item, no pay-error; change a field -> new payment | | b_pay | PASS with NOTE - values kept; unchanged resubmit leaves balance, feed and pay-error as required (one payment), but the UI RE-SENDS the same POST with the same Idempotency-Key and body (server replay 200) rather than sending nothing; any changed field (note/amount/visibility/handle) uses a new key |
| I07 | feed: newest first, item attrs data-visibility, parties text has both handles, amount exact, note exact (present when empty), empty-activity | | b_feed | PASS - b2_wallet (newest-first DOM order equals API, attributes, parties, amount, note present when empty, empty-activity) |
| I08 | /requests: lists, pending-only buttons, request-error, empty-requests, refresh after action | | b_requests | PASS with NOTE - b3_flows x2: lists, pending-only buttons, pay/decline/cancel, request-error; the empty-requests element is always in the DOM and hidden when requests exist (visible only when both lists are empty) |
| I09 | /split: preview equals server shares (1000/3 -> 334/333/333), reorder moves extra unit, split-error, submit creates requests | | b_split | PASS - b3_flows x2 (preview 334/333/333 and reorder, 0.01/3, JPY, preview posts nothing, equals server shares) |
| I10 | After success, balance/feed/request lists refresh without manual reload; navigation waits for write | | b_pay/b_requests | PASS - b2/b3 (no manual reload after pay/decline/cancel/authorize/capture/void) |
| I11 | `wallet-refresh` latest wins; out-of-order responses; pay form not cleared | route interception reorder | b_refresh | PASS - b2_wallet x2 (out-of-order /me and /activity; 3 overlapping reads; pay form untouched) |
| I12 | Stale balance: refused payment -> `pay-error`, refresh balance/feed, inputs preserved | | b_stale | PASS - b2_wallet x2 |
| I13 | Request cancelled elsewhere while pay button visible -> `request-error`, list refreshed, stale button gone | | b_stale | PASS - b3_flows x2 (cancelled/declined/paid elsewhere), b6 |
| I14 | Lost response after POST /payments commits -> `pay-uncertain` nonempty, not `pay-error`; retry unchanged form sends SAME key and body; money once; both elements removed; balance/feed refreshed | | b_lost | PASS - b2_wallet x2 (committed-then-dropped, never-committed, offline; same key+body; money once) |
| I15 | Upgrade: stage-1 export -> import to stage-2; browser stays signed in; pending request payable; lost payment retry recovers original, imported balance shown; form/pending identity survive; no reload | | b_upgrade | PASS - b4_upgrade x3 (same-origin proxy: stage-1 token from login form, lost response, export/import, same page: refresh shows 85.00 EUR, retry replay, pending request paid) |
| I16 | `wallet-available` headline once holds exist; `wallet-balance` total retained; `wallet-held` absent at zero; seeded hold shows available right after reset | computed font sizes / DOM | b_wallet | PASS - b2_wallet, b3_flows, b6 (available headline font-size > total/held, held absent at 0, seeded hold immediately) |
| I17 | authorize form (same input rules), `authorize-error`; `/authorizations` list newest first, amount/captured/expires(RFC3339)/capture-amount prefilled remaining/capture/void presence rules, `authorization-error`, `empty-authorizations` | | b_authz | PASS - b3_flows x2 (list order, statuses, amounts, captured only when captured, expires RFC3339, capture prefilled, void/capture presence rules, authorize form rules, errors, empty) |
| I18 | Capture UI partial then rest; void UI | | b_authz | PASS with NOTE - capture/void/stale refusals; the UI capture is final-only (sends {amount}); a partial capture releases the remainder, so partial-then-rest is not possible through the UI (the spec lists no testid for extended mode) |
| I19 | Product quality: 375 px and desktop no horizontal scroll; visible labels; visible keyboard focus; contrast >= 4.5; empty/loading/error/refused/uncertain/pending/available/held visibly distinct (not by colour alone); nav consistent; people-first formats; no raw ids in primary text | | b_quality | PASS - b1 x3 (no h-scroll 375/768/1280, visible labels, measured contrast >= 4.5 on every text node, Tab walk with visible focus indication, nav consistent), b6 x2 (loading skeleton/aria-busy, error + Try again on /, /requests, /authorizations, keyboard-only payment), screenshots reviewed |
| I20 | S66 visual system: canvas #030014, surface #060317, raised #10093a, text #f4f0ff, secondary #a8a6b7, accent #9382ff; DM Sans 500 headings, Inter 400/500 body, weight <= 500; radii 5/16/32; inset rim light, no drop shadows; no red/green status; no stock imagery/mascots/large gradients | computed styles + screenshots | b_visual | PASS - b5_visual: palette/typography/radii/shadows/status colours all within the stated system; see verdict.md |

## J. Delivery

| id | statement | property | check | verdict |
|---|---|---|---|---|
| J01 | Image builds from clean checkout per RUN.md, runs with `-e PORT` + port map, no outbound at runtime; assets (fonts/js/css) from image, no external URL | | docker build/run, internal net, grep | PASS - clean clone f33035a, docker build --no-cache 19.7 s, RUN.md commands verbatim, internal-network run, assets and fonts same-origin, PORT 9999/80/8080/default, read-only fs + uid 12345 + 2 cpu/2g |
| J02 | Folder holds only stage-2 behaviour, no repo metadata inside it | | tree listing | PASS - stage-2/ has no .git*, only stage-2 routes, tests/testdata/jstest only; stage-1/ unchanged since accepted 0024598 |
| J03 | Stage-1 checks still pass (regression) | | harness stage 1 + my c01..c13 | PASS - shipped stage-1 147/147; my c01-c13 x3 (c04/c09 adapted for the two stage-2 changes: /me gains total/available/held, GET / serves HTML) |
