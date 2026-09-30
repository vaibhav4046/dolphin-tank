# Stage 1 requirement ledger (pocketful)

Spec: D:\project\dolphin-tank\dark-factory-wearedevs\pocketful\spec\stage-1.md
SPECIFICATION_HASH (sha256 of exact file bytes read): 65497dea09a8b432598c71662320cf66c3550e183cfd76e2d7f97318e0d30aa4 (25082 bytes)

Owners: F=forge (domain core, validators, auth), T=trace (store/lock, idempotency, settlements, reset/fixture, export/import), L=loom (HTTP layer, Dockerfile, RUN.md), J=jury (verification).
Check: H=shipped harness (report read by jury), G=jury gap check (written from this ledger, run against exact commit), U=implementer runnable check.

| ID | § | Normative statement | Observable property | Owner | Check |
|---|---|---|---|---|---|
| R01 | 1.1 | Sum of balances always equals total seeded by last reset | After any mix of concurrent payments/pays/splits/settlements/retries, sum of GET /me over all users == seeded sum | F,T | G concurrent storm + sum |
| R02 | 1.2 | No balance negative, even transiently | Balance 100, 20 concurrent payments of 100 -> exactly 1 succeeds, rest 409; polling /me never sees <0 | F,T | G race |
| R03 | 1.3 | A request moves money at most once | N concurrent pays of one request (same key and distinct keys) -> one payment, one debit | F,T | G race |
| R04 | 1 | Exact integer minor units; money only between existing wallets; no deposits/top-ups/withdrawals/cards/banks | No such endpoints; amounts never rounded | F | H/G |
| R05 | 2 | Deliver HTTP service, Dockerfile, RUN.md with command that builds and starts without manual setup | RUN.md commands work verbatim | L | G |
| R06 | 2 | Image runs alone with -e PORT and port mapping; no outbound network at run time; single container | Runs with no external calls; no compose needed | L | G |
| R07 | 2 | Start to first healthy response <= 60 s | Health 200 within 60 s of start | L | H |
| R08 | 2 | Up to 50 requests in flight within 2 vCPU / 2 GiB | 50 concurrent requests, no 5xx, no timeout | L,T | G |
| R09 | 2 | Per-request timeout 5 s (10 s reset) | Every call incl. reset/export/import returns in time | all | G |
| R10 | 2 | Runtime assets/dependencies inside image | No runtime downloads | L | G |
| R11 | 3.1 | Listen 0.0.0.0 on PORT, default 8080 | Reachable via mapped port; default 8080 when PORT unset | L | G |
| R12 | 3.2 | GET /health -> 200 {"status":"ok"} | Exact body | L | H |
| R13 | 3.3 | POST /_test/reset -> 204, replaces all state, repeatable, unauthenticated, enabled | Post-reset only fixture visible; second reset fully replaces | T | H |
| R14 | 3.4 | Requests/responses application/json; charset=utf-8 | Content-Type header on all JSON responses | L | G |
| R15 | 3.4 | Timestamps RFC 3339 with explicit offset | created_at parses, has +hh:mm offset | F | H/G |
| R16 | 3.4 | Unknown body fields and unknown query params ignored | Extra fields/params give same result as without | L,F | G |
| R17 | 3.4 | IDs opaque strings <= 64 chars | len(id) <= 64 | F | G |
| R18 | 4 | One currency from fixture; amounts are integer minor units | /me currency,minor_units from fixture; JPY/BHD work | F,T | H |
| R19 | 4 | Amount integral numeric: 1000, 1000.0, 1e3 valid; booleans, strings not numbers | 1000.0 and 1e3 accepted as 1000; "1000", true -> 422 | F | G |
| R20 | 4 | Handle unique, ^[a-z0-9_]{1,20}$, never changes | Unique; no mutate endpoint | F | G |
| R21 | 4 | Seeded handle from fixture; signup handle derived: local part, lowercase, non [a-z0-9_] -> _, truncate 20 | "A.B-c@x.com" -> "a_b_c"; 25-char local -> 20 chars | F | G |
| R22 | 4,6 | Derived handle taken -> 409 handle_taken, no account created | Second signup same derived handle: 409; email still unregistered (login 401) | F | G |
| R23 | 4 | New users balance 0; can receive and be requested at once | /me balance 0; pay to/request from new user works | F | H/G |
| R24 | 4 | Payment moves money immediately and atomically | Both balances change in one step | F | H |
| R25 | 4 | Request pending then exactly one of paid/declined/cancelled; only payer pays/declines; only requester cancels | State machine transitions; wrong party 403 | F | H |
| R26 | 4 | Request may exceed payer balance; pay while short 409 insufficient_funds changes nothing; payable once funded | Create ok; pay 409 no change; top up by payment; pay 201 | F | H/G |
| R27 | 4 | Visibility belongs to the payment (payer chooses); request has no visibility and never in others' feeds | Request JSON has no visibility; feed has payments only | F | G |
| R28 | 4 | GET /activity returns payments only; visible iff public OR caller is sender/receiver; no other rule | Third party sees public only; parties see private | F | H |
| R29 | 4 | GET /requests only requests where caller is requester or payer | Third party sees none | F | H |
| R30 | 4 | Split is not a feed item; its requests visible to their two parties | Split creates no feed item | F | G |
| R31 | 4 | Visibility one value seen identically by both parties; private hidden from third parties not from receiver | Sender and receiver both see private payment | F | G |
| R32 | 4 | amount <= 1e9 per request; no balance outside +-2^53; exact arithmetic | 1e9 ok, 1e9+1 -> 422; balances up to 2^53 exact (no float) | F | G |
| R33 | 4 | Fixture: users, payments, requests; seeded users log in at once; balance taken as given (no replay) | Login with fixture password; /me balance == fixture | T | H |
| R34 | 4 | Fixture balance < 0 -> 422 validation_failed from reset, nothing changed | Prior state intact after rejected reset | T | G |
| R35 | 4 | minor_units 0/2/3 (EUR, JPY, BHD) | /me reflects each | T,F | H/G |
| R36 | 5 | Every 4xx/5xx has {"error":{"code","message"}} with specified status/code | Shape on every error incl. 404 unknown route, 405, 401 | L | H |
| R37 | 5 | 400 malformed_request: unparseable body or wrong-type field | Non-JSON body, array body, to_handle:123 -> 400 | L,F | G |
| R38 | 5,7 | 400 missing_idempotency_key when header absent or empty | Absent and empty header -> 400 on all five paths | L,T | H |
| R39 | 5 | 401 unauthenticated for missing/malformed/unknown token | Three variants -> 401 | L | H |
| R40 | 5 | 403 forbidden (authenticated, not permitted); 404 not_found (absent or not visible) | Third party pay/decline/cancel -> 403; unknown id -> 404 | F | H |
| R41 | 5,7 | 409 idempotency_key_reuse: key used by caller with different body | Same key, different body -> 409 | T | H |
| R42 | 5 | 422 validation_failed for missing required field/param or violated rule; bad format/range of right type -> 422 | Missing amount, to_handle, etc. -> 422 | F,L | G |
| R43 | 5 | Invalid amount (incl strings, booleans), non-string note (incl null), visibility not public/private -> 422; omission selects defaults | Each -> 422; omitted note=="" visibility=="public" | F | G |
| R44 | 5 | Integer query params plain decimal digits; 1e9, 4.0, +4 -> 422 | limit=1e9/4.0/+4 -> 422 | L | G |
| R45 | 5 | Idempotency-Key 1..255 else 422; limit 1..200; offset >=0 else 422 on every endpoint that takes them | 256-char key, limit 0/201, offset -1 -> 422; boundary values ok | L,T | G |
| R46 | 5 | Requests must not produce 5xx, including under concurrent load | 0 x 5xx over storm and malformed-input sweep | all | G |
| R47 | 6 | POST /auth/signup 201 {user_id,display_name,token}; POST /auth/login 200 same shape | Shapes | F | H |
| R48 | 6 | email_taken 409; password <8 422; bad email 422; wrong password/unknown email 401 | Each row of table | F | H |
| R49 | 6 | All other endpoints require bearer except /health, /_test/*, signup, login | Every other route 401 without token | L | G |
| R50 | 6 | Tokens never expire; multiple valid tokens and sessions per account | Two logins -> both tokens valid | F | G |
| R51 | 6 | Passwords stored with password-hashing function (bcrypt/scrypt/Argon2/equivalent); no plaintext | Export shows no plaintext password; hash is salted KDF | F | G |
| R52 | 7 | Five write paths need idempotency key: POST /payments, /requests, /requests/{id}/pay, /splits, /settlements | Absent key -> 400 on each of five | T,L | H/G |
| R53 | 7 | Key scoped to authenticated user; two users may share key string | Same key by two users: both 201 independent | T | G |
| R54 | 7 | Replay = same user, method, path, body; same key+body on a different path is a different request and succeeds | Same key on /payments then /requests: both 201 | T | G |
| R55 | 7 | First use 201; replay 200 with body identical JSON value; different body 409; key reused after 4xx = first use | Four rows | T | H |
| R56 | 7 | Same body = same JSON value after parsing (key order, whitespace irrelevant) | Reordered keys + whitespace replay -> 200 | T | G |
| R57 | 7 | Concurrent identical requests with unused key: exactly one 201, others 200 same body, effect once | 20 parallel identical -> one 201, 19 x 200, one debit | T | G |
| R58 | 7 | Successful replay returns original response even after resource changes/cancelled; no further state change | Replay after cancel/balance change returns original | T | G |
| R59 | 7 | Claimed key resolved before endpoint field validation/current-resource checks | Success then same key with invalid body -> 409 idempotency_key_reuse | T,L | G |
| R60 | 8 | GET /me {user_id,display_name,handle,balance,currency,minor_units} | Shape | F | H |
| R61 | 8 | POST /payments 201 full payment body; note default "", visibility default public | Shape incl request_id null, settlement_id null | F | H |
| R62 | 8 | Payment errors: insufficient 409; amount 422; self_payment 422; note >200 422; visibility 422; unknown handle 404 | Each row; note 200 ok, 201 -> 422 | F | H/G |
| R63 | 8 | Debit and credit atomic; failed payment leaves no trace in either wallet | After failure balances and feed unchanged | F,T | G |
| R64 | 8 | note stored/returned verbatim (no trim/escape/normalise); unicode/emoji byte-exact | Round trip " <b>é😀 " | F,L | G |
| R65 | 8 | POST /requests 201 request body; caller is requester; errors amount 422, self_request 422, note 422, unknown handle 404; payer balance not checked | Request above payer balance created pending | F | H |
| R66 | 8 | POST /requests/{id}/pay: only payer; body visibility only, default public; 201 payment with request_id; request becomes paid with payment_id | Payment shape; GET /requests shows paid + payment_id | F | H |
| R67 | 8 | pay errors: not pending 409 request_not_pending; insufficient 409; not payer 403; unknown 404 | Each row | F | H |
| R68 | 8,7 | Replay of successful pay -> 200 original payment even when request paid; no more money; never request_not_pending; {} vs {"visibility":"public"} are different bodies (409) | Replay + body-variant | T | G |
| R69 | 8 | decline: payer only, 200 declined, twice 200, paid/cancelled 409 request_not_pending, not payer 403, no idem key | Each row | F | H |
| R70 | 8 | cancel: requester only, 200 cancelled, twice 200, paid/declined 409 request_not_pending, not requester 403, no idem key | Each row | F | H |
| R71 | 8 | GET /requests: direction incoming/outgoing/absent; status filter; limit default 50 (1..200), offset; bad direction/status 422; newest first; has_more; {requests,has_more} | Filters, paging, has_more boundary | F,L | H/G |
| R72 | 8 | POST /splits 201 {split_id,amount,currency,note,shares,requests,created_at}; errors amount 422, empty/dup handles 422, note 422, unknown handle 404 | Shape and each row | F | H |
| R73 | 8 | shares cover every participant in order and sum to amount; requests cover all except caller in same order, caller requester; caller-only split valid with requests [] | Caller first/middle/absent/only | F | G |
| R74 | 8 | Nothing about a split checks anyone's balance | Split with zero-balance participants -> 201 | F | G |
| R75 | 8 | GET /activity {payments,has_more} newest first; limit/offset as /requests | Shape, paging | F | H |
| R76 | 9 | Shares whole units, sum exactly, differ <=1, larger shares to first participants; table (1000/3,1/3,10/3,999/3,5/5); zero share legal and still yields a request; order changes who gets the extra | Table values, reorder | F | G |
| R77 | 9 | Shares independent of previous splits; after splits paid in full balances sum to seeded total | Repeat splits, pay all, sum | F | G |
| R78 | 10 | GET /_test/export 200 {track:"pocketful",format_version:1,state}, unauthenticated | Shape | T | G |
| R79 | 10 | POST /_test/import takes whole export, atomically replaces state, 204; accepts unchanged export; replacement not merge; repeatable without duplication; no dependency on source process/files/port | Export A, mutate, import A -> equals A; twice -> same; import into fresh container | T | G |
| R80 | 10,5 | Invalid JSON -> 400; missing fields/wrong track/version/invalid state -> 422, destination unchanged | Each variant, state intact | T | G |
| R81 | 10 | Export atomic read-only snapshot; later writes don't change it; 10 s timeout | Export during writes is self-consistent (sum invariant) | T | G |
| R82 | 10 | Preserve accounts+hashed login, tokens, currency, balances, payments, requests, permissions, completed idempotent bodies and responses; ids/timestamps not regenerated; failed keys reusable; receipts/tokens/retries valid after import | Post-import: old token works, login works, replay -> 200 identical, ids/created_at equal, failed key reusable | T | G |
| R83 | 10 | Import removes all previous destination data and credentials; reset clears imported state | Destination-only user/token gone after import; reset clears | T | G |
| R84 | 11 | Fixture settlement_operator_ids (default []); operator may settle across any wallets; no access to others' requests/private items | Operator GET /requests and /activity not widened | T,F | G |
| R85 | 11 | POST /settlements: no token 401; authenticated non-operator 403; requires idempotency key | Each | T | G |
| R86 | 11 | transfers 1..32 objects; ordinary amount/note/visibility rules and defaults; unknown handle 404; self_payment 422; malformed batch 422; entry errors in input order before insufficient funds; unknown fields ignored | 0 and 33 transfers 422; entry 2 invalid + entry 1 unaffordable -> entry error wins | T | G |
| R87 | 11 | Affordable iff every wallet balance after all incoming and outgoing >= 0; else 409 insufficient_funds; all-or-none; failed validation claims no key, creates no payment or revision | Chain A->B->C with B net >=0 passes; failure leaves state + key reusable | T | G |
| R88 | 11 | 201 {settlement_id,committed_at,payments in input order}; members are ordinary payments with settlement_id; non-members settlement_id null; members request_id null and created_at == committed_at | Shape; all members share created_at | T,F | G |
| R89 | 11 | Constituents follow ordinary feed visibility; response has every member receipt; replay 200 original complete response | Private member hidden from third party; replay identical | T | G |
| R90 | 11 | Reset/import preserve operator permissions, original payments, requests, settlement membership, retry responses | Import then settle as operator; replay settlement after import | T | G |
