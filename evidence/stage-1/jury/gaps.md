# jury gaps.md - pocketful stage 1, commit 0024598cf4a43b6584171b1f7b8f92523c652c3a

## What the shipped checks show, and what they do not

Shipped run (`--stage 1 --mode isolated`, out `band-work/checks/s1-0024598-a/`):

```
stage 1: pass   stage 2: fail (UI, expected)
highest contiguous stage: 1
claimed stage: 1 on the shipped checks
report: /mnt/d/project/dolphin-tank/band-work/checks/s1-0024598-a/report.json
stage 1: collected 147, passed 147, failed 0, errors 0, skipped 0
  stage_1/test_me_payments.py 24/24   stage_1/test_requests_splits_feed.py 39/39
  stage_1/test_retries_splits_input.py 51/51   stage_1/test_sample.py 19/19   stage_1/test_seeded_state.py 14/14
NOTE: this run only includes a portion of the full tests that are applied before judging
```

The report carries file-level counts only (no per-test names) and says it is a portion of the full suite. The file names cover
me/payments, requests/splits/feed, retries/splits/input and seeded state. Nothing in the visible list is named for **export/import
(spec 10)** or **settlements (spec 11)**, and nothing shows real concurrency with an observer, abandoned-connection retries, a fresh-container
round trip, or a no-outbound-network run. Because I cannot attribute individual tests, I did **not** skip any must-cover group: every
group below was independently executed by me against the same commit.

## Uncovered (or not attributable) requirements -> my check -> result

| Requirement group (ledger ids) | Property that would fail if violated | My check | Result |
|---|---|---|---|
| J01-J03, J53 conservation, never negative (incl. transiently), one payment per request | 50 concurrent 100-unit payments vs balance 1000 (exactly 10 win); observers polling GET /me in both read orders never see negative or torn (credit-before-debit) state; 30 concurrent pays of one request; pay/decline/cancel race x15; 4 s sustained churn | c01_conservation.py | PASS |
| J47, J57-J59 concurrent identical idempotent requests on all five write paths; replay after state change; claimed key beats validation; {} vs {"visibility":"public"} | x20 identical concurrent per path x3 rounds (exactly one 201, 19 x 200, identical bodies, one effect); replay after change; invalid body same key -> 409; different valid body -> 409 | c02_idempotency.py (144 checks, run x3) | PASS |
| J43-J46, J48-J49 key scoped per user, same key other path, JSON-value equality, failed 4xx key reusable | two users same key on payments/requests/splits/settlements; payments+requests same key+body -> both 201; key order/whitespace/1000 vs 1000.0 vs 1e3 vs 1E3 vs \u escape -> 200; 1001 / extra field / omitted note -> 409; 409/422/404 keys reusable incl. pay and settlement | c02_idempotency.py | PASS |
| J16, J25, J35-J37, J54 amount forms, boundaries, limit/offset forms, key length, note verbatim | amount table (1, 1e9, 1e9+1, 0, true, "1000", null, 1e400, 2^53+1, 1e-1 ...) on four paths; 200 vs 201 chars incl. 200 emoji (code points, not bytes); verbatim round trip of leading/trailing spaces, `<`, `&`, emoji, quotes, newline; limit/offset 1e9, 4.0, +4, %2B4, 0, 201, -1, empty; key 255 vs 256 | c03_validation.py (195 checks) | PASS |
| J18, J40, J19 handle derivation; handle_taken leaves no account | `é`, `éé`, emoji, 25-char truncation, `+`/`.`/`-`; handle_taken x3 then login 401 and retry still handle_taken; 10 concurrent signups with one derived handle -> one account; same email x10 -> one | c04_auth.py (88 checks, run x3) | PASS |
| J22-J23, J21, J20 visibility, requests never in feed, request above balance pending then payable | private hidden from third party, visible to both parties with identical body; requests never in any feed; 1e9 request on a 5000 payer created pending; pay 409 leaves state; payable after funding | c05_requests_feed.py | PASS |
| J62-J68 split rounding table, zero share, caller first/middle/absent/only, conservation | table incl. 1000/3, 1/3, 10/3, 999/3, 5/5, reorder, 10 participants, 1e9/3; zero-share requests created; caller-only split -> `requests: []`; every split request paid -> sum == seeded total | c07_splits.py | PASS |
| J28-J29, J11, J27 negative-balance reset, JPY/BHD, reset clears everything, id collisions, reset under load | 422 leaves tokens/balances/feed/idempotency intact; JPY(0)/BHD(3) currency in every body; signups, tokens, keys cleared; fixture ids p_1,p_3 / rq_1,rq_7,rq_9 never collided by generated ids; 1000-user reset in time; 8 resets under 12 hammering threads | c06_reset_fixture.py | PASS |
| J69-J77, J87-J88 export/import | fresh container (`docker rm`/`run` per run) import of an unchanged export; tokens, logins, every replay (all five paths), ids, timestamps, operators, failed-key reuse preserved; repeat import restores without duplicates; import removes prior data/credentials; reset clears imported state; garbage imports leave state intact; blind corruption fuzz (63 mutated states, 0 x 5xx); export atomic under 12 concurrent writers (25 snapshots imported, ledger == balances, sum == total, none negative); import racing 8 writers; 3000-payment state in time | c08_export_import.py (run x3, fresh dst each) | PASS |
| J78-J88 settlements | 401/403/400 gates; net affordability (chain both orders, zero-balance cycle, send>balance but net positive); all-or-none; entry errors in input order before funds; 0/33/32 transfers; receipts in input order, settlement_id on members and null on non-members, created_at == committed_at; private member hidden from third party; operator gains no access to others' requests/private feed; replay 200 original; claimed key beats validation; 30 concurrent identical -> one effect; 30 distinct + 10 direct payments vs balance 1000 -> exactly 10 wins | c11_settlements.py (run x3) | PASS |
| J38, J08, J30, J12, J13, J15, J33, J10 no 5xx, envelope, content type | 3 x (50 threads x 40 mixed valid/invalid ops) + 253 malformed-body requests across 11 POST endpoints (2 MB body, 100000-deep nesting, NUL, invalid UTF-8, BOM) + 30 odd routes/methods + query fuzz; every 4xx has envelope + application/json; charset=utf-8; max latency << 5 s; conservation after each round | c09_no5xx_envelope.py (run x3) | PASS (see deviations) |
| Lost responses / retries (spec 7, "retries, lost responses") | client closes the socket right after sending (response lost) on all five paths x20 concurrently, then retries twice: every retry 201-or-200 never 409/5xx, second retry identical 200, each key took effect exactly once; concurrent same key with two different bodies -> exactly one winner | c12_retries_edges.py (run x3) | PASS |
| J05-J07, J09 image, RUN.md, no outbound network, PORT | clean clone at exact commit, RUN.md `docker build`/`docker run -e PORT` as written (tag differs), health in ~0.02 s, `docker network create --internal` + sibling container (outbound to 1.1.1.1/8.8.8.8 blocked) drives register/payment; PORT=80/9999/default, `--read-only --cap-drop ALL --cpus 2 -m 2g`, arbitrary uid | d2_smoke.py, rt.sh | PASS |
| go test -race (never run by authors; no gcc on host) | data races in the store/handlers | `go vet ./... && go test -race -count=1 ./...` in golang:1.24 | see verdict.md |

## Deviations found (not rejectable on the written spec) - details in verdict.md
- Transport-level requests that net/http rejects before any handler (invalid `%ZZ` URL escape, control byte in a header value) get net/http's plain-text `400 Bad Request`, without the JSON envelope.
- Unknown routes and wrong methods return `404 not_found` with the envelope (no 405); HEAD /health is 404.
- Accepts an import whose opaque `state` lacks `minor_units`/`seq`/`splits`/`sys`/`tokens` (204) - state format is implementation-defined, envelope fields and gross corruption are rejected with 422.
