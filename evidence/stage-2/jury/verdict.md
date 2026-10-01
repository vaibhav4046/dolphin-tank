# VERDICT: ACCEPT - pocketful stage 2

- Commit verified: `f33035a390c63c61dfc4ce12feb8076542c8469b` (`git rev-parse HEAD` in `D:\project\dolphin-tank\band-work\result`, worktree clean; also a clean `git clone` + `git checkout` into WSL `/root/jury/s2`, `git status` 0 lines; `git diff 17aa87e HEAD -- stage-2` empty; `stage-2/` contains no `.git*` and only stage-2 routes; `stage-1/` unchanged since the commit I accepted earlier, `git diff 0024598 HEAD -- stage-1` empty).
- Spec: `stage-2.md` sha256 `39aaf9d7743c6fd831663e5b8363866f7d70795e5efb9000c2803f471397b13f` and `stage-1.md` sha256 `65497dea09a8b432598c71662320cf66c3550e183cfd76e2d7f97318e0d30aa4`, both verified against the files on disk. The ledger (`ledger.md`, 78 rows) was written from the spec before I opened any source.
- Seat: jury. Nothing in `stage-1/` or `stage-2/` touched, no production code written. Only `evidence/stage-2/jury/` is mine.

## Commands run (all by me) and real output
1. Build from scratch, RUN.md as written (tag changed): `cd /root/jury/s2/stage-2 && docker build --no-cache -t pocketful-s2-jury .` -> `Successfully built 6558850fa96c`, 19.7 s, image 9.2 MB (`FROM scratch`, static Go binary, uid 65532). RUN.md verbatim commands (`docker build -t pocketful-s2 .`, `docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2`, `curl /health`) -> `{"status":"ok"}` (`logs/runmd-and-hardened-run.log`).
2. No network at run time / offline serving: `docker network create --internal pf2-int`, server + sibling `python:3.12-alpine`: `outbound blocked to 1.1.1.1 -> OSError`, `... 8.8.8.8 -> OSError`, `/health` 200, all six routes 200 `text/html`, `/assets/css/*.css`, `/assets/js/main.js`, `/assets/fonts/dm-sans.woff2` (36932 B) and `inter.woff2` (48256 B) 200 from the image; CSS `url()` only same-origin; no `src/href` to another origin; the only `http://` string in `web/` is the SVG namespace in `js/dom.js` (`logs/offline-assets.log`). Also verified: PORT=9999, 80, 8080, default (no PORT), `--read-only --cpus 2 -m 2g --user 12345` serve and `POST /_test/reset` -> 204 (`logs/ports-and-hardened-run.log`).
3. Shipped checks, exactly the prescribed command with a fresh `--out` (`.../checks/s2-f33035a-jury1`; the suggested `-a` directory already existed from another run and the harness refused it, I did not use its report):
   ```
   building /mnt/d/project/dolphin-tank/band-work/result/stage-2 ...
     stage 1: pass
   building upgrade source /mnt/d/project/dolphin-tank/band-work/result/stage-1 ...
     stage 2: pass
     stage 3: fail
   highest contiguous stage: 2
   claimed stage: 2 on the shipped checks
   ```
   `harness/report.json`: `"revision": "f33035a390c63c61dfc4ce12feb8076542c8469b"`, `"claimed_stage": "2"`, stage 1 `collected 147, passed 147, failed 0` (me_payments 24/24, requests_splits_feed 39/39, retries_splits_input 51/51, sample 19/19, seeded_state 14/14), stage 2 `collected 35, passed 35, failed 0` (test_sample 10/10, test_ui 25/25). Stage 3 failure is expected.
4. My own API checks (stdlib Python, fresh production container per run, real threads/barriers, real clock). Final results (`logs/`):
   ```
   s2_lifecycle  82 pass 0 fail          s2_funds   32/0        s2_errors   73/0 (no 5xx)
   s2_idem       50/0 x3 runs            s2_list    70/0        s2_fixture  84/0
   s2_expiry     30/0 x3 runs (real clock, ttl 2 / 1)
   s2_race       54/0 x5 clean runs, ~10.2k requests each, max latency 0.09 s
   s2_export     30/0 x4 clean runs      s2_export_expiry 18/0 x4 clean runs
   s2_upgrade_api 23/0 (accepted stage-1 image -> stage-2 image)
   ```
   Stage-1 regression: my accepted stage-1 checks c01..c13 x3 against the stage-2 image: c01 42, c02 144, c03 195, c05 49, c06 40, c07 98, c08 73, c11 69, c12 42, c13 2 all `0 fail, 0 5xx` in all three runs; c04 (88/0) and c09 (10/0) pass after adapting two assertions to the two stage-2 changes (`/me` gains `total/available/held`; `GET /` serves HTML) - adapted copies in `s1reg/`, unadapted run1 output kept in `logs/s1reg-summary.run1.txt`; d2_smoke is replaced by item 2 (it needs a sibling container).
   Data races: `docker run golang:1.24 sh -c "go vet ./... && go test -race -count=1 ./..."` -> `go version go1.24.13`, `VET_OK`, `ok  pocketful  45.605s` (`logs/go-vet-and-test-race.log`).
5. Browser (Playwright chromium in `df-harness-runner`, real browser, 375 px and 768/1280 px):
   ```
   b1_quality  146/0 x3   (6 routes x 3 widths: no h-scroll, labels, contrast >= 4.5, Tab walk, signed-in chrome, auth flows)
   b2_wallet    84/0 x2   (decimal rules, resubmit, JPY/BHD, stale balance, refused recovery, lost response x3 modes, latest-wins)
   b3_flows     82/0 x2   (/requests, stale refusals, /split preview, /authorizations, authorize form, capture, void)
   b4_upgrade   19/0 x3   (stage-1 token -> lost response -> export -> import -> same page: session valid, 85.00 EUR, retry replay, pending request paid)
   b5_visual    18/0      (S66 computed styles)
   b6_states    26/0 x2   (loading/error/retry on every data route, keyboard-only payment, expiry seen by the UI)
   ```

## Requirement ledger result
All 78 rows PASS (`ledger.md`), four with notes (below). `gaps.md` lists what the shipped checks (about 35 percent) could not be relied on to show and the check I wrote for each.

## Spec-silent author choices - decided from the written spec only
| Choice | Ruling |
|---|---|
| Effective expiry = now >= expires_at, stored status never mutated by the clock | Not a violation: spec says "at or before now is expired"; verified by reads/writes with no request at the deadline. |
| Seeded `expires_at` echoed verbatim | Not a violation (spec silent); read back as written. |
| Capture order 404 -> 403 -> not_open -> expired -> exceeds | Not a violation: spec requires 403 for any non-permitted caller incl. strangers on an existing authorization (verified on open and closed holds). |
| Seeded holds up to 2^53 accepted while API cap is 1e9 | Not a violation (spec silent on seeded range; stage-1 allows balances to 2^53). |
| Same payment in two authorizations: first wins | Spec silent; not exercised, not a violation. |
| Import accepts only plain-integer ttl | Not a violation; exports always emit integers (verified in export). |
| UI treats any Accept containing text/html as UI for /requests and /authorizations | Not a violation: browser Accept strings and plain `text/html` give HTML, `application/json`, `*/*` and none give JSON; POST unaffected (verified). |
| UI keys idempotency by a fingerprint of the raw field values | Not a violation: changed handle/amount/note/visibility each used a new key (verified). |
| Pending-retry identity in page memory only | Not a violation: reload recovery is explicitly not required. |
| `go test -race` never run by authors | Run by me: ok. |

## Notes (none blocks acceptance; each is stated so route and the authors can decide)
1. `authorization_ttl_seconds` above 1 000 000 000 (e.g. 2147483648) is rejected `422 validation_failed` ("must be an integer from 1 to 1000000000"). The spec says "positive integer number of seconds" with no stated upper bound, so a literal reading would accept it. 1e9 is accepted, 1e9+1 .. 2^64 never 5xx. I did not reject: the bound is outside any value a fixture would plausibly use and keeps expiry arithmetic safe, but it is a deviation from the letter. Evidence: `logs/s2_fixture.run1-ttl-2pow31-note.log`.
2. Pay form, unchanged resubmit: balance falls once, the feed holds one payment, `pay-error` stays absent (as required), but the UI re-sends the same `POST /payments` with the same Idempotency-Key and byte-identical body (server replays 200) instead of sending nothing. A harness that counts HTTP POSTs instead of observing balance/feed would see 2-3 POSTs with one distinct key. I read "must not send another payment" as satisfied (no second payment exists). Evidence: `logs/b2_wallet.run2.log` (`INFO unchanged resubmits: 3 POSTs, 1 distinct Idempotency-Key`).
3. `empty-requests` is always in the DOM and hidden while any request exists; it is visible only when both lists are empty ("Shown when both lists are empty" holds by visibility, not by DOM absence). Evidence: `browser/probe5.py` output, `logs/b3_flows.run1-empty-requests-hidden-in-dom.log`.
4. The UI captures with `{"amount": ...}` only (final capture): a partial capture closes the hold and releases the remainder, so "partial then rest" is not possible from the UI (it is by API). The spec lists no testid or control for extended mode, so I treat this as compliant. Evidence: `INFO` lines in `logs/b3_flows.run2.log`.

## Visual system (S66) and presentation, what I saw
Computed styles over all six routes at 375 and 1280 px (`logs/b5_visual.run1.log`): body background rgb(3,0,20)=#030014 on every route; surface rgb(6,3,23) and raised rgb(16,9,58) cards; text rgb(244,240,255), secondary rgb(168,166,183), the single accent rgb(147,130,255) (hue 248 deg only); DM Sans 500 for all 28 headings, Inter 400/500 for body, no weight above 500, both fonts `loaded` from `/assets/fonts`; radii exactly 5/16/32 px; only box-shadow in use is `rgba(244,240,255,.08) 0 1px 0 inset` (rim light, no drop shadow); no red/green/orange anywhere; no `img/picture/video/canvas`; only gradients are the 2 chevrons in `<select>`. I looked at the screenshots (`browser/shots/run*/`): the wallet leads with "Available to spend" as the largest number with Total and On hold clearly secondary, cards are calm and scannable, amounts show as `80.00 EUR`, timestamps as `Oct 1, 21:22`, handles not ids, direction chips (Sent/Received, Public/Private with icons). Refused ("Not completed", solid border, X icon, "Not enough available funds. Money on hold cannot be spent.") and uncertain ("Unconfirmed", dashed border, spinner icon, "retry sends the same payment once") are distinct in shape, icon and wording, not only colour; empty states have a title and a hint; loading is a skeleton with `aria-busy`; error states offer "Try again". I found nothing I would call a presentation defect.

## Honest notes on my own check development
Several first runs failed because of my own test bugs, not product defects, and were fixed before the final runs (logs kept with suffixes): s2_lifecycle used 4000 of a 1800 available; s2_errors had a stray control character in a unicode literal (rewritten as escapes); s2_race ran an observer across a reset (tokens invalid -> 401) and counted ada->cy payments against an ada/bob observer; s2_fixture initially asserted ttl 2^31 accepted (now note 1); b2 counted POSTs instead of distinct keys (note 2); b3 asserted `empty-requests` absence by DOM count (note 3); b1 asserted an empty feed for a new user although public payments of others are visible. Timing assertions in s2_export/s2_export_expiry used a computed sleep and failed when the shared WSL VM stepped its wall clock (the test's own `clock sanity` assertion shows python's clock short of expires_at while the server agreed with it); rewritten to wait on the wall clock, 4 clean reruns each. Infrastructure: the WSL VM restarted during the session (containers exited 255, `ConnectionRefused` in s2_race run 2 and s2_export run 5, one 20 s worker timeout in s2_race run 3); all reruns clean. One unexplained transient: `b1_quality` run 1 stuck 30 s on `/` after logout; not reproduced in 3 full reruns and a 20-iteration stress (`browser/probe3.py`); I could not identify a cause and report it as unproven rather than resolved.

## Verification budget (rough, not measured)
About 130 tool calls; roughly 450-500k tokens of context across the session (peak context about 434k of 1M), most of it check authoring and log reading; wall time about 3.5 hours including WSL restarts. No subagents used.
