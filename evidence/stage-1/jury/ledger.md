# jury ledger - pocketful stage 1 (own, written from spec before reading code)

Columns: id | spec § | normative statement | property implied | demonstrating check | verdict (filled at end)

Check key: SH = shipped harness report; Cnn = my script in evidence/stage-1/jury/checks/

| id | § | statement | property | check | verdict |
|----|---|-----------|----------|-------|---------|
| J01 | 1.1 | Sum of balances == seeded total at all times, incl. concurrent + retries | conservation under 50 concurrent mixed ops | C01, C09 | PASS |
| J02 | 1.2 | No balance negative, even transiently | concurrent observer polling GET /me never sees <0 | C01 | PASS |
| J03 | 1.3 | A request moves money at most once | N concurrent pay of one request -> 1 payment | C01 | PASS |
| J04 | 1 | Amounts exact integers of minor units; only between existing wallets | no float drift | C03 | PASS |
| J05 | 2 | Image builds from Dockerfile; RUN.md one command builds+starts | clean build, start as written | D1 | PASS |
| J06 | 2 | Runs with only -e PORT + port mapping; no outbound at run time | works on --internal network | D2 | PASS |
| J07 | 2 | Start to first healthy <= 60 s | measure | D1 | PASS |
| J08 | 2 | 50 concurrent in flight, per-request 5 s (10 s reset) | no timeouts under 50 | C09 | PASS |
| J09 | 3.1 | Listen 0.0.0.0, PORT env, default 8080 | run with no PORT | D2 | PASS |
| J10 | 3.2 | GET /health -> 200 {"status":"ok"} | exact body | C09 | PASS |
| J11 | 3.3 | POST /_test/reset fixture -> 204, no auth, repeatable, replaces all state | state after reset only fixture | SH, C06 | PASS |
| J12 | 3.4 | application/json; charset=utf-8 on req/resp | header on success + error | C09 | PASS (API responses; net/http transport-level 400s are plain text - see verdict deviations) |
| J13 | 3.4 | Timestamps RFC3339 with explicit offset | regex on all timestamps | C09 | PASS |
| J14 | 3.4 | Unknown body fields ignored; unknown query params ignored | extra fields on every endpoint | C03 | PASS |
| J15 | 3.4 | IDs opaque strings <= 64 chars | len check | C09 | PASS |
| J16 | 4 | Amounts: 1000, 1000.0, 1e3 all valid; bool/string not numbers | amount form table | C03 | PASS |
| J17 | 4 | Handle ^[a-z0-9_]{1,20}$ unique, immutable | | C06 | PASS |
| J18 | 4 | Signup handle derived: local part lowercase, non [a-z0-9_] -> _, trunc 20 | table | C04 | PASS |
| J19 | 4 | New users balance 0; can receive/be asked immediately | | C04 | PASS |
| J20 | 4 | Request may exceed payer balance: pending; pay short -> 409 no change; payable after funded | | C05 | PASS |
| J21 | 4 | Visibility belongs to payment, chosen by payer on pay; request has no visibility, never in feed | | C05 | PASS |
| J22 | 4 | Feed: visible iff public or caller is sender/receiver; private hidden from third party, visible to both parties | | C05 | PASS |
| J23 | 4 | GET /requests only requester/payer rows | third party sees none | C05 | PASS |
| J24 | 4 | Split not a feed item; its requests visible only to their 2 parties | | C07 | PASS |
| J25 | 4 | |amount|<=1e9 per request; balances exact to 2^53 | boundary 1e9, 1e9+1 | C03 | PASS |
| J26 | 4 | Fixture: login with given password immediately | | SH, C06 | PASS |
| J27 | 4 | Fixture balance is post-payments; no replay | seeded payments don't alter balances | C06 | PASS |
| J28 | 4 | Fixture balance < 0 -> reset 422, state unchanged | | C06 | PASS |
| J29 | 4 | minor_units 0/2/3; EUR JPY BHD fixtures work | /me currency+minor_units | C06 | PASS |
| J30 | 5 | Every 4xx/5xx has {"error":{"code","message"}} | every 4xx sampled | C09 | PASS (same transport-level exception) |
| J31 | 5 | 400 malformed_request: unparseable body / wrong-type field | | C03 | PASS |
| J32 | 5 | 400 missing_idempotency_key: absent or empty | | C02 | PASS |
| J33 | 5 | 401 unauthenticated: missing/malformed/unknown bearer | | C09 | PASS |
| J34 | 5 | 403 forbidden / 404 not_found / 409 idempotency_key_reuse / 422 validation_failed | | C02, C05 | PASS |
| J35 | 5 | amount invalid (incl strings, bools), note non-string incl null, visibility other -> 422 | | C03 | PASS |
| J36 | 5 | Query ints plain decimal: 1e9, 4.0, +4 -> 422 | | C03 | PASS |
| J37 | 5 | Idempotency-Key 1..255 chars else 422; limit 1..200; offset >=0 | 255 ok, 256 -> 422 | C03 | PASS |
| J38 | 5 | No 5xx incl concurrent load | 50 concurrent mixed + malformed sweep | C09 | PASS |
| J39 | 6 | signup 201 {user_id,display_name,token}; login 200 same | | SH, C04 | PASS |
| J40 | 6 | email_taken 409; pw<8 422; bad email 422; bad login 401; handle_taken 409 and no account created | handle_taken leaves no account (login fails, email re-usable) | C04 | PASS |
| J41 | 6 | Bearer required on all but health/reset/signup/login; tokens no expiry, multiple concurrent | | C04 | PASS |
| J42 | 6 | Passwords hashed, not plaintext | export inspection | C08 | PASS |
| J43 | 7 | Keys scoped per authenticated user | 2 users same key no interaction | C02 | PASS |
| J44 | 7 | Replay = same method+path+body; same key other path is new request | | C02 | PASS |
| J45 | 7 | Header absent/empty 400; first 201; replay 200 identical body; diff body 409; failed 4xx key reusable | | C02 | PASS |
| J46 | 7 | Body equality as JSON value: key order, whitespace, 1000 vs 1000.0 vs 1e3 | | C02 | PASS |
| J47 | 7 | Concurrent identical: exactly one 201, rest 200 same body, one effect | on all 5 paths | C02 | PASS |
| J48 | 7 | Replay returns original after resource changes / cancelled; no further changes | | C02 | PASS |
| J49 | 7 | Claimed key resolved before field validation/current-resource checks (after JSON object parse + auth) | invalid body same key -> 409 | C02 | PASS |
| J50 | 8 | /me fields exact | | SH, C04 | PASS |
| J51 | 8 | POST /payments body/response shape; defaults note "" visibility public | | SH, C03 | PASS |
| J52 | 8 | payments errors: insufficient 409, amount 422, self_payment 422, note>200 422, visibility 422, unknown handle 404 | | SH, C03 | PASS |
| J53 | 8 | Debit+credit atomic; failed leaves no trace | | C01 | PASS |
| J54 | 8 | note verbatim (emoji, <, &, spaces); 200 chars ok 201 -> 422 | | C03 | PASS |
| J55 | 8 | POST /requests shape; caller=requester; payer balance not checked; self_request 422; errors | | SH, C05 | PASS |
| J56 | 8 | pay: only payer; 201 payment w/ request_id; request paid + payment_id; errors 409 not_pending / insufficient / 403 / 404 | | C05 | PASS |
| J57 | 8 | pay replay 200 original even when request already paid; no 409 request_not_pending; no extra money | | C02 | PASS |
| J58 | 8 | pay body {} vs {"visibility":"public"} different values -> 409 reuse | | C02 | PASS |
| J59 | 8 | decline: payer only, 200, idempotent on declined; paid/cancelled -> 409; non-payer 403 | no key needed | C05 | PASS |
| J60 | 8 | cancel: requester only, 200, idempotent; paid/declined -> 409; non-requester 403 | | C05 | PASS |
| J61 | 8 | GET /requests direction/status filter, newest first, limit/offset/has_more, 422 bad values | | C05 | PASS |
| J62 | 8 | POST /splits shape, caller incl/omitted, request per non-caller, shares sum | | C07 | PASS |
| J63 | 8 | splits errors: amount 422, empty/dup handles 422, note 422, unknown handle 404 | | C07 | PASS |
| J64 | 8 | split only participant = caller: valid, zero requests, requests [] ; no balance check | | C07 | PASS |
| J65 | 8 | GET /activity shape, limit/offset as /requests | | C05 | PASS |
| J66 | 9 | Shares whole units, sum exact, differ <=1, larger first in order; table 1000/3, 1/3, 10/3, 999/3, 5/5 | | C07 | PASS |
| J67 | 9 | Zero share legal, still produces request | | C07 | PASS |
| J68 | 9 | After splits paid in full, balances still sum to seeded total | | C07 | PASS |
| J69 | 10 | GET /_test/export 200 {track:"pocketful",format_version:1,state} | | C08 | PASS |
| J70 | 10 | POST /_test/import whole object -> 204, atomic replace; accepted unchanged | | C08 | PASS |
| J71 | 10 | Import works into fresh container (no dependency on source process/files) | | C08 | PASS |
| J72 | 10 | Import replacement not merge; repeat restores, no dup | | C08 | PASS |
| J73 | 10 | Invalid JSON -> 400; missing fields/wrong track/version/invalid state -> 422 without changing destination | | C08 | PASS |
| J74 | 10 | Export atomic read-only snapshot; later writes don't change it | export under concurrent writers: sum == total | C08 | PASS |
| J75 | 10 | Preserve accounts, logins, tokens, currency, balances, payments, requests, idempotency bodies+responses, ids, timestamps | | C08 | PASS |
| J76 | 10 | Failed request keys remain reusable after import | | C08 | PASS |
| J77 | 10 | Import removes prior destination data and credentials; reset clears imported state | | C08 | PASS |
| J78 | 11 | settlement_operator_ids fixture field; operator may settle any wallets; no access to others' requests/private feed | | C09s | PASS |
| J79 | 11 | POST /settlements: no token 401; non-operator 403; key required | | C09s | PASS |
| J80 | 11 | transfers 1..32; 0/33 -> 422; unknown handle 404; self 422 self_payment; shape 422; unknown fields ignored | | C09s | PASS |
| J81 | 11 | Entry errors in input order before insufficient funds | | C09s | PASS |
| J82 | 11 | Affordable iff every wallet net-nonnegative after all transfers (chain ada->bob->cy with bob empty) | | C09s | PASS |
| J83 | 11 | All-or-none; failed validation claims no key, no payments | | C09s | PASS |
| J84 | 11 | 201 settlement_id, committed_at, payments in input order; settlement_id on members, null on nonmembers | | C09s | PASS |
| J85 | 11 | Members null request_id, created_at == committed_at | | C09s | PASS |
| J86 | 11 | Constituents follow feed visibility; private member hidden from third party | | C09s | PASS |
| J87 | 11 | Replay 200 original; after import too; concurrent identical settlements -> one effect | | C09s, C08 | PASS |
| J88 | 11 | Operator perms, payments, requests, membership, retry responses preserved by import | | C08 | PASS |

## Verdict notes (jury, 2026-10-01, commit 0024598cf4a43b6584171b1f7b8f92523c652c3a)

- Every row above: PASS on the production image built from the clean clone; evidence logs in `logs/` (final runs `*.runN.log`, summary `logs/final-summary.txt`), scripts in `checks/`.
- J12/J30 carry one documented exception: requests net/http rejects before routing (invalid `%ZZ` percent-escape in the path, control byte in a header value) get net/http's plain-text `400 Bad Request` (observed in c09). See verdict.md "Deviations".
- J42 (hashed passwords): export shows `pbkdf2-sha256$60000$<salt>$<key>`, no plaintext anywhere in the export (c08 asserts neither fixture nor signup password appears).
- J05/J06/J07/J09: clean clone, `docker build` from RUN.md (17.8 s), health 200 in 0.02 s, default PORT, PORT=80/9999, `--read-only --cpus 2 -m 2g`, arbitrary uid, and `docker network create --internal` sibling-container drive (outbound blocked) - all OK.
