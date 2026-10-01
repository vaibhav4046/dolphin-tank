# VERDICT: ACCEPT - pocketful stage 1

- Commit verified: `0024598cf4a43b6584171b1f7b8f92523c652c3a` (clean `git clone` + `git checkout` in WSL `/root/jury/s1`, `git status` 0 lines, `stage-1/` holds only the stage's files, no `.git*` inside it).
- Spec: `stage-1.md` (sha256 65497dea09a8b432598c71662320cf66c3550e183cfd76e2d7f97318e0d30aa4), parts 2/3 + 3/3 as delivered.
- Seat: jury. Written 2026-10-01. Nothing in `stage-1/` touched; no production code written.

## Commands run (all by me) and real output

1. Build per RUN.md in the clean checkout (tag changed to `pocketful-s1-jury` so I do not overwrite a peer's image):
   `cd /root/jury/s1/stage-1 && docker build -t pocketful-s1-jury .` -> `Successfully built 3ec06cf6cd51`, 17.8 s, image 2.65 MB (`FROM scratch`, static Go binary, user 65532).
   `docker run --rm -e PORT=8080 -p 18080:8080 pocketful-s1-jury` -> `GET /health` 200 `{"status":"ok"}`, `Content-Type: application/json; charset=utf-8`, first healthy response after 0.02 s. Default port (no `-e PORT`) also serves. PORT=80 and PORT=9999 serve. Runs with `--read-only --cpus 2 -m 2g` and with an arbitrary `--user 12345`.
2. No outbound network at run time: `docker network create --internal pf-int`, server container + sibling `python:3.12-alpine` on it. Sibling output:
   ```
   outbound blocked to 1.1.1.1 -> OSError
   outbound blocked to 8.8.8.8 -> OSError
   PASS health 200 on internal net
   PASS payment 201 on internal net
   == d2_smoke: 4 pass, 0 fail, 9 requests, 0 5xx
   ```
3. Shipped checks, exactly the prescribed command (`--out .../checks/s1-0024598-a`), output (`harness/harness-stdout.log`, `harness/report.json`):
   ```
   building /mnt/d/project/dolphin-tank/band-work/result/stage-1 ...
     stage 1: pass  (log: .../s1-0024598-a/stage-1.log)
     stage 2: fail  (log: .../s1-0024598-a/stage-2.log)
   highest contiguous stage: 1
   claimed stage: 1 on the shipped checks
   report: /mnt/d/project/dolphin-tank/band-work/checks/s1-0024598-a/report.json
   ```
   report.json: `"revision": "0024598cf4a43b6584171b1f7b8f92523c652c3a"`, `"claimed_stage": "1"`, stage 1 `collected 147, passed 147, failed 0, errors 0, skipped 0` (me_payments 24/24, requests_splits_feed 39/39, retries_splits_input 51/51, sample 19/19, seeded_state 14/14). The stage-2 failure is the UI test (`page.fill ... login-email` timeout) and is expected for a stage-1 service. The report itself says it is only a portion of the full suite.
4. My own checks (`checks/*.py`, stdlib Python 3.12 from `/root/dfv`, real threads + barrier, real abandoned-socket retries), each on a freshly started production container, race-type checks run 3 times. Final results (`logs/final-summary.txt`):
   ```
   c01_conservation run1..3  42 pass, 0 fail, ~10.6k requests, 0 5xx
   c02_idempotency  run1..3  144 pass, 0 fail, 742 requests, 0 5xx
   c03_validation           195 pass, 0 fail, 218 requests, 0 5xx
   c04_auth         run1..3  88 pass, 0 fail, 144 requests, 0 5xx
   c05_requests_feed         49 pass, 0 fail
   c06_reset_fixture         40 pass, 0 fail, 1226 requests, 0 5xx
   c07_splits                98 pass, 0 fail
   c08_export_import run1..3 73 pass, 0 fail, ~7.9k requests, 0 5xx   (fresh destination container each run)
   c09_no5xx_envelope run1..3 10 pass, 0 fail, ~8.9k requests, 0 5xx
   c11_settlements  run1..3  69 pass, 0 fail, ~630 requests, 0 5xx
   c12_retries_edges run1..3 42 pass, 0 fail, 1266 requests, 0 5xx
   c13_reset_vs_me  run1..3  2 pass, 0 fail, 27501/15235/18615 requests, 0 5xx  (731/449/557 resets under 16 hammer threads)
   ```
5. Data races: `docker run golang:1.24 sh -c "go vet ./... && go test -race -count=1 ./..."` (Go 1.24.13, gcc present in that image) -> `VET_OK`, `ok  pocketful  31.301s` (`logs/go-vet-and-test-race.log`). I also built the server with `go build -race` in that image and drove it with my concurrency checks (c01, c02, c03, c04, c05, c07, c08, c09, c11 x3 rerun, c12; `logs/race-*.log`): all pass, `DATA RACE warnings: 0` in the server log (`logs/race-server.log`, `logs/race-server-c11rerun.log`).

## Honest notes on my own check development
Several of my first runs failed because of my own test bugs, not product defects, and were fixed in the check before the final runs (all recorded in `checks/`): c02 (a funding amount too small for the scenario), c03 (miscounted accepted payments), c04 (email collision between my own cases), c08 (a login against the wrong container, and an always-true assertion I deleted), c09 (my reset sweep wiped state mid-run; a HEAD assertion for something the spec does not require), c11 (replay assertion compared against the wrong balances; fails identically on the race build until fixed). The final-summary runs above are all from the corrected scripts on the unchanged commit.

## What the spec demands that the shipped checks never demonstrated (also in gaps.md)
The report only has file-level counts, so I treated every must-cover group as uncovered and ran it. Groups and the check that would fail if violated: concurrency + concurrent observer (c01); idempotency x5 paths concurrent, replay after change, claimed key beats validation, `{}` vs `{"visibility":"public"}`, per-user scope, other path, JSON-value equality, failed-key reuse (c02); amount/limit/offset/key-length/note boundaries (c03); handle derivation and `handle_taken` leaves no account, signup races (c04); visibility, requests never in feed, request above balance (c05); reset/fixtures/JPY/BHD/negative balance/id collisions/reset under load (c06, c13); split rounding table and conservation (c07); export/import into a FRESH container incl. tokens, logins, every replay, ids, timestamps, operators, garbage imports, atomic export under 12 concurrent writers, import racing writers, corruption fuzz (c08); no 5xx under 50 concurrent mixed requests + malformed sweep + envelope/content type (c09); settlements (c11); lost-response retries and concurrent same-key-different-body (c12); no outbound network (d2_smoke).

## Spec-silent choices - decided from the written spec only
| Choice | Ruling |
|---|---|
| Reset hashes each distinct seeded password once (shared salt); PBKDF2-SHA256, 60000 iterations, random salt per distinct password, signup uses its own salt | Not a violation. Spec requires "a password-hashing function ... or an equivalent", plaintext forbidden; export shows `pbkdf2-sha256$60000$salt$key`, no plaintext. |
| Fixture leniency (absent currency -> EUR, absent id generated, absent handle derived) | Not a violation; spec constrains only invalid balances. Verified: fixture without currency -> 204, `/me` EUR/2. |
| Pay-request payment copies the request's note | Not a violation; spec silent. |
| 0-amount request (zero split share) is payable (201, payment amount 0, request `paid`) | Not a violation. Spec says a zero share "still produces a request"; the "amount below 1" rule is listed only for POST /payments. Recorded as a spec ambiguity, not a defect. |
| Non-payer on pay (incl. strangers) -> 403; precedence 403 before 409 `request_not_pending` | Matches the pay table ("caller is not the request's payer -> 403"). |
| Non-matching handle (empty, uppercase, spaces, 1000 chars) -> 404 | Matches "No user has that handle -> 404". |
| display_name rejected only when exactly `""` | Spec silent. Signup without display_name -> 422 observed; fine. |
| Newest-first = reverse insertion order | Matches (verified deterministic even within one second). |
| `GET /me` for a user removed by a concurrent reset returns 200 null | Could not reproduce: c13 raced ~1,737 resets against 16 threads x 3 runs plus 8 earlier resets under load; every `/me` was 200 object or 401, 0 x 200-null, 0 x 5xx. Not a demonstrated violation. |
| stdlib-level malformed HTTP (invalid `%ZZ` escape in path, control byte in header value) gets net/http's plain-text `400 Bad Request` | Literal deviation from §5 "every 4xx carries the envelope", but only for requests net/http rejects before any handler/route exists; no API endpoint behaviour is involved, all API-level 4xx carry the envelope (c09 asserts it on ~8.9k responses incl. 253 malformed bodies, 30 odd routes, query fuzz). Accepted as residual risk (see below). |
| Body > 1 MiB -> 400 `malformed_request` (256 MiB cap for reset/import) | Spec silent on size. Observed: 2 MiB payments body -> 400 `malformed_request`; 900 KiB note -> 422 `validation_failed`. Fine. |
| Empty `?status=` / `?direction=` -> 422 | Consistent with "unknown direction or status value is also 422" (observed 422). |
| Empty body on pay/decline/cancel means `{}` | Spec silent; pay with empty body -> 201 public; replay of the same key with `{}` -> 200 (treated as the same body). Fine. |
| Reset of a JSON non-object -> 400; Import of a JSON non-object -> 422 | Observed 400 / 422. Reset: body of the wrong JSON type -> 400 per §5; import: "missing fields ... invalid state -> 422" per §10. Defensible both ways, not rejected. |
| `go test -race` never run by authors | Run by me: clean (above). |

Error-precedence observations (spec silent, recorded, none contradicts the written text): no token -> 401 even without a key; unparseable JSON with no key -> 400 `missing_idempotency_key`, with a key -> 400 `malformed_request`; unknown request id with no key -> 400, with key -> 404; non-payer on a declined request -> 403, payer -> 409; non-operator settlement without key -> 403; claimed key resolves before field validation (409), per §7.

## Deviations / residual risks (none rejectable on the written spec)
1. Plain-text `400 Bad Request` for requests net/http cannot parse (invalid percent-escape in the path, control bytes in a header). Literal §5 wording says "every 4xx"; unreachable by a well-formed JSON API client. Evidence: `logs/c09_no5xx_envelope.run1.log` ("OBS transport-level plain-text 4xx").
2. Unknown routes and wrong methods return `404 not_found` with the envelope (no 405); `HEAD /health` is 404. Spec requires only `GET /health`.
3. Import accepts an opaque `state` that lacks `minor_units`/`seq`/`splits`/`sys`/`tokens` (204) and rejects missing `currency`/`payments`/`requests`/`users` and 53 of 63 type-corrupted variants with 422, never 5xx, and rejected imports never change state (c08). State format is implementation-defined; the spec requires 422 for missing envelope fields, wrong track/version and "invalid state", all of which are enforced.
4. The harness report is a portion of the full hidden suite; my checks cover export/import and settlements, which the visible portion does not name. A hidden test could still probe behaviour neither of us thought of.
5. Zero-share payment (see table) and the `/me`-vs-reset 200-null path were judged spec-silent / unreproduced.

## Acceptance criteria
- Image builds from clean checkout: yes. Serves per RUN.md: yes. Nothing at run time needs network: yes (internal-network drive).
- Shipped report "claimed stage: 1" with every stage-1 check passing (147/147): yes.
- Every uncovered requirement has a check that passes: yes (ledger.md all PASS, gaps.md).
- No 5xx anywhere: ~154k requests across the final runs on the production image (sum of the per-run counts above), 0 x 5xx (every script asserts it).
- Race-type checks pass repeatedly (3 runs on production image, plus once on the -race binary, 0 data races): yes.

## Folder check
`stage-1/` at the commit contains only Go sources, tests, `Dockerfile`, `.dockerignore`, `RUN.md`, `go.mod`; no repository metadata inside it (`find stage-1 -name '.git*'` empty).

## Evidence index (all under `evidence/stage-1/jury/`)
`ledger.md` (88-row own ledger with verdicts), `gaps.md`, `verdict.md`, `progress.md` (working notes), `checks/` (scripts), `logs/` (final runs, race run, summaries), `harness/` (copy of the shipped report and stdout).
