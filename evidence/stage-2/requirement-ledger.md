# Stage 2 requirement ledger (pocketful)

Spec: D:\project\dolphin-tank\dark-factory-wearedevs\pocketful\spec\stage-2.md
SPECIFICATION_HASH (sha256 of exact file bytes read): 39aaf9d7743c6fd831663e5b8363866f7d70795e5efb9000c2803f471397b13f (20079 bytes, 380 lines)
Stage 1 rows R01..R90 (evidence/stage-1/requirement-ledger.md) continue to apply; "must keep working" is checked by the stage-1 jury scripts re-run on the stage-2 image where they still apply.

Owners: F=forge (authorization domain, validators, JS logic modules), T=trace (reset/import/export, settlements, idempotency, expiry, upgrade), L=loom (HTTP routes, browser UI, fonts, Dockerfile), J=jury.
Check: H=shipped harness, G=jury gap check (API/concurrency), B=jury real-browser check, U=implementer test.

| ID | Spec § | Normative statement | Observable property | Owner | Check |
|---|---|---|---|---|---|
| S01 | intro | Stage-1 requirements continue to apply | Stage-1 behaviours unchanged with no holds | all | G (re-run stage-1 scripts) |
| S02 | routes | `/`, `/requests`, `/split`, `/signup`, `/login` reachable by URL; other screens reachable through the UI | GET each with Accept text/html -> 200 UI; `/authorizations` linked from nav | L | H/B |
| S03 | routes | `/requests` shared: UI for `Accept: text/html`, JSON otherwise | Same URL: html vs JSON (401 envelope without token) | L | H/G |
| S04 | routes | UI exposes the listed data-testid attributes | Each id present in the stated state | L | H/B |
| S05 | visual | Coherent, presentation-ready, calm; available funds clearest value once holds exist; total and held secondary | Screenshot review; headline element is wallet-available | L | B |
| S06 | visual | Payments/requests/splits/authorisations scannable; status, direction, privacy, money movement understandable without raw data; consistent system; primary actions identifiable | Review: labels, glyphs, grouping | L | B |
| S07 | visual | Available, held, pending, loading, success, refused, uncertain states visually distinct | Distinct label/glyph/opacity per state, not color alone | L | B |
| S08 | visual | People, amounts, timestamps formatted for people; technical ids only where they help | No raw ids/ISO in primary text (expires testid is RFC3339 by spec) | L | B |
| S09 | visual | Usable at 375 px and desktop, no horizontal page scroll | scrollWidth <= clientWidth at 375/768/1280 on every route | L | B |
| S10 | visual | Inputs have visible labels; keyboard focus apparent; sufficient contrast; empty/loading/error states; consistent navigation | Tab walk shows focus ring; contrast >= 4.5; states reachable | L | B |
| S11 | auth | signup/login testids; `auth-error` present only when there is one | Absent initially; present after bad login; removed after success/edit | L | H/B |
| S12 | auth | `current-user` visible on every screen when signed in, text contains display name; `current-handle` text exactly the handle (no @) ; `logout-button` | On all 6 routes | L | H/B |
| S13 | balance | `wallet-balance` text is exactly formatted amount and carries data-amount (minor units) | `100.00 EUR`, data-amount=10000 | L,F | H |
| S14 | balance | Formatted: exactly minor_units decimals, one space, currency code; 0 decimals -> no point; no sign | EUR `100.00 EUR`, JPY `1200 JPY`, BHD 3 places | F,L | H/U |
| S15 | pay | pay-handle/amount/note inputs, pay-visibility select with values public/private, pay-submit, pay-error | Elements + option values | L | H |
| S16 | pay | pay-amount decimal: `15.00` and `15` -> 1500, `15.5` -> 1550; nonnumeric or too many decimals -> form error, no request; `15.005` rejected not rounded | Request log shows no POST; pay-error shown | F,L | H/B |
| S17 | pay | Pay form keeps values after success; resubmitting unchanged sends no further payment (balance falls once, one feed item, pay-error absent); changed field = new payment request | One payment after double submit; new key on change | L | H/B |
| S18 | request | request-handle/amount/note/submit and request-error (refused) | Elements; refusal (self, unknown) shows error | L | H |
| S19 | feed | activity-list children newest first in DOM; activity-item-{id} with data-visibility; parties contains both handles; amount exactly formatted; note exactly note and present even when empty; empty-activity instead of list when nothing visible | Seeded feed DOM order/attrs; empty state | L | H |
| S20 | requests | incoming-list/outgoing-list; request-item-{id} data-status; request-amount-{id} exact; pay/decline only on pending incoming; cancel only on pending outgoing; request-error; empty-requests when both empty | Button presence matrix per status/direction | L | H/B |
| S21 | split | split-amount, split-handles (comma separated, ordered), split-note, split-submit, split-preview with one split-share-{handle} per participant (exact formatted), split-error | Elements; preview before submit | L,F | H |
| S22 | split | Preview shows shares the server would compute (§9), identical to submitted split | 1000/3 -> 3.34, 3.33, 3.33; reorder moves the extra unit | F,L | H/B |
| S23 | refresh | After any successful action the balance, feed and request lists on the same page show the new state without manual reload; navigation waits for write success before refresh | No reload; no refresh before 2xx | L | H/B |
| S24 | refresh | `wallet-refresh` on `/` refreshes balance and feed without clearing the pay form; latest refresh wins incl. out-of-order responses | Delay first read, answer second first -> final = newer data | F,L | B |
| S25 | compete | Refused payment (balance spent elsewhere): `pay-error`, balance/feed refreshed, all pay inputs preserved | Spend elsewhere then pay | L | H/B |
| S26 | compete | Request cancelled elsewhere while pay button visible: `request-error` on refused pay, list refreshed, stale pay button gone | Cancel via API then click pay | L | H/B |
| S27 | compete | Lost payment response (also after commit): `pay-uncertain` nonempty, not `pay-error`; unchanged form retryable with SAME key and body; successful retry removes both elements, refreshes, money moves exactly once | Abort response after commit; retry; one payment | F,L | B (+H) |
| S28 | compete | No polling/live sync/reload recovery required; same refresh rules apply to available and held | wallet-available/held refresh with balance | L | B |
| S29 | upgrade | Stage-2 accepts a stage-1 export (import 204) | Real stage-1 export imported | T | G |
| S30 | upgrade | Browser signed in before the upgrade stays signed in (token still valid, no re-login) | Same token valid after import; UI keeps session | T,L | B |
| S31 | upgrade | Existing pending requests remain payable through the request screen | Pay a stage-1 pending request via UI after import | T,L | B |
| S32 | upgrade | Payment whose response was lost before export is retryable after import with same body+key; UI recovers original payment and refreshes imported balance; form and retry identity survive; no reload/new screen | Lost response -> export -> import -> retry -> success, one payment | T,L | B |
| S33 | auth.model | Authorise now, capture later (full or less); hold reserves without moving; capture moves; final capture releases uncaptured remainder; non-final keeps remainder held; open authorisation expires and releases remainder | Lifecycle walk | F | G |
| S34 | auth.inv | Sum of wallet totals always equals seeded total; hold moves no money; payments, settlements, captures transfer between wallets | Sum after storm | F,T | G |
| S35 | auth.inv | available = total - held never negative; held funds cannot fund new payments, authorisations or settlement net debits; captures may spend money reserved for them | Pay over available -> 409; capture of reserved ok | F,T | G |
| S36 | auth.inv | Cumulative captures never exceed authorised amount; each idempotent capture moves money once; closed hold cannot be captured again | Concurrent captures | F | G |
| S37 | api.me | GET /me keeps `balance` == `total`; `available`, `held` added; no holds -> balance=total=available, held 0 | Shape and values | F | H/G |
| S38 | api.pay | POST /payments immediate, no hold, no capture; payments without authorisation carry `authorization_id: null`; request_id semantics unchanged | Payment body | F | G |
| S39 | api.funds | Every 409 insufficient_funds (payments, request pay, settlements) evaluated against `available` | Hold blocks pay, request pay, settlement debit | F,T | G |
| S40 | api.misc | Paying a request stays immediate; authorising a request out of scope; POST /splits unchanged | Split with holds unchanged | F | G |
| S41 | api.idem | Seven idempotent write paths (stage-1 five + authorizations + captures), same replay rules independently | 201/200/409/400 on both new paths; 20-way concurrent identical | T,F | G |
| S42 | model | Fixture `authorization_ttl_seconds` default 600; if supplied must be positive integer (else 422); applies to API-created authorisations; seeded ones carry absolute `expires_at` | ttl 2 -> expires_at = created_at+2; 0/-1/"x"/1.5 -> 422 | T | G |
| S43 | model | Seeded `balance` is total; `available` derived (seeded open holds subtracted); never seeded | /me after reset with hold | T,F | H/G |
| S44 | model | Sum of seeded unexpired open holds > user's balance -> 422 validation_failed from reset, state unchanged | Reset rejected, prior state intact | T | G |
| S45 | model | Seeded status open/captured/voided/expired; only open holds anything; omitted `authorizations` = empty | Each status; omission | T | G |
| S46 | model | `expires_at` at or before now = expired, holds no funds; reads and writes reflect expiry with no request at the deadline; GET /authorizations shows `expired`; /me available includes released remainder | Seed past expiry; short ttl, wait, read | F,T | G |
| S47 | api.auth | POST /authorizations: key required, caller is payer, body/response shape (captured_amount, status open, expires_at = created_at + ttl, payment_id null, created_at); note/visibility defaults | Shape | F | G |
| S48 | api.auth | Errors: available < amount 409; amount <1/>1e9/non-int 422; self 422 self_payment; note>200 or bad visibility 422; unknown handle 404 | Each row | F | G |
| S49 | api.auth | Open authorisation never in GET /activity | Feed excludes it | F | G |
| S50 | api.capture | Capture: key required; only receiver; `amount` optional default remaining; replay must send identical body (`{}` vs `{"amount":2000}` -> 409) | Key/body matrix | T,F | G |
| S51 | api.capture | 201 with payment in POST /payments shape, `authorization_id` set, `request_id` null, amount = captured, note/visibility copied, visible in feed by ordinary rule | Body + feed | F | G |
| S52 | api.capture | Default capture -> status `captured`, `captured_amount`, `payment_id`, releases remainder immediately (1500 of 2000 returns 500 to payer's available same step) | /me before/after | F | G |
| S53 | api.capture | Second capture after a final capture -> 409 authorization_not_open | Replay with new key | F | G |
| S54 | api.capture | Extended mode: `final` boolean default true; `final:false` with remainder keeps status open; later captures up to remainder; capturing whole remainder closes even with final:false; final closes and releases; exceeds compares with remaining; captured_amount cumulative; payment_id latest; payment_ids all in order; `remaining_amount` on every authorization response (0 when closed) | 700 then 1300 etc | F | G |
| S55 | api.capture | Void and expiry may close a partially captured authorisation, release only the remainder, preserve all capture records; new fields do not change idempotency body equality | Partial then void/expire | F,T | G |
| S56 | api.capture | Errors: not open 409 authorization_not_open; expires_at <= now 409 authorization_expired; amount > remaining 422 capture_exceeds_authorization; amount <1 / non-int 422; not receiver 403; unknown 404 | Each row | F | G |
| S57 | api.void | Void: payer only, no key, 200 `voided` and hold released; void twice 200 current state; captured/expired -> 409 authorization_not_open; non-permitted incl. strangers 403; unknown 404 | Each row | F | G |
| S58 | api.list | GET /authorizations only caller's (payer or receiver); newest first; direction outgoing/incoming/absent; status filter, clock-expired matches `expired` never `open`; limit/offset/has_more as /requests (422 on bad values) | Filters + paging | F | G |
| S59 | ui.auth | Wallet gains `wallet-available` (headline, formatted available, data-amount) and `wallet-held` (formatted held, data-amount, absent when zero); `wallet-balance` formatted total | Presence rules | L | H/B |
| S60 | ui.auth | authorize-handle/amount/note/visibility/submit with same input rules as pay; `authorize-error` when refused incl. insufficient available | Elements; refusal | L,F | H/B |
| S61 | ui.auth | `/authorizations`: authorization-list newest first; item data-status; amount exact; captured only when status captured; expires text = RFC3339 expires_at; capture-amount input prefilled with remaining and capture button only on incoming open; void only on outgoing open; authorization-error on refused capture/void; empty-authorizations | Matrix per direction/status | L | H/B |
| S62 | ui.auth | UI reflects seeded and newly created holds; available shown as spending balance incl. immediately after reset with open holds | Reset with hold then load `/` | L | B |
| S63 | concurrent | Concurrent requests behave as some sequential order; requirements hold at every read | Storm + observers (sum, available >= 0, held <= total) | all | G |
| S64 | deploy | stage-2 folder complete: source, Dockerfile, RUN.md; builds, serves from clean container, no outbound at run time; all fonts, scripts, styles inside image | Internal-network drive + no external URLs in served HTML/CSS | L | G/B |
| S65 | user | Stage-1 folder untouched; nothing from stage 3/4; no nested .git | diff stage-1 vs accepted commit; folder scan | route,J | route |
| S66 | user | Visual direction: canvas #030014, surface #060317, raised #10093a, text #f4f0ff, secondary #a8a6b7, one accent #9382ff; DM Sans 500 headings, Inter 400/500 body bundled; no weight above 500; radii 5/16/32; inset rim light not drop shadows; no red/green status; available funds headline; no stock imagery/mascots/large gradients | Computed styles + screenshots | L | B |
