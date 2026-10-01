# Stage 2 route summary
- Accepted source commit: f33035a390c63c61dfc4ce12feb8076542c8469b (stage-2/ source byte-identical to trace's 17aa87e; later commits are evidence and .gitignore only). Jury verdict: ACCEPT, evidence at 9111851 (evidence/stage-2/jury/). Spec sha256 39aaf9d7743c6fd831663e5b8363866f7d70795e5efb9000c2803f471397b13f. stage-1/ unchanged since the accepted cb2af8b.
- Seats: forge = authorization domain, validators, funds rule, JS money/attempt/latest/outcome + jstest (fbe4573, 950f272); trace = fixture/import/export upgrade, held-aware settlement, idempotency/time/concurrency tests, stage-1 export fixture (a16ad67, strict ttl null follow-up 17aa87e); loom = HTTP routes, browser UI, fonts, Dockerfile, RUN.md, own browser evidence (42fef7a, 7875bf1, dbf467c, bcf386b); jury = independent acceptance (9111851); route = ledger S01-S66 (2ad9306), handoffs, .gitignore for go build executables (f33035a).
- Shipped harness (jury, out s2-f33035a-jury1, mode isolated): claimed stage 2; stage 1 147/147, stage 2 35/35; stage 3 fails as expected. Report: evidence/stage-2/jury/harness/report.json.
- Jury own checks: API lifecycle/funds/errors/list/fixture/idem/expiry/race/export/upgrade, stage-1 regression x3, go test -race clean, real-browser b1-b6 at 375/768/1280 including stale-state, lost-response, refused-payment recovery and stage-1 export -> stage-2 import upgrade, visual system check. All 0 fail, no 5xx.
- Route change from its own review: explicit authorization_ttl_seconds null is "supplied" -> 422 (trace, 17aa87e). Operator (Codex) evidence in evidence/operator/ is not seat work and not acceptance.
- Cost seen by route: about $12.8 coordinator session total at acceptance (stage 1 + stage 2 sessions). Jury reported ~450-500k tokens of context, ~130 tool calls, ~3.5 h wall, no subagents. Other seats' cost not visible to route.
Residual risks the jury accepted, usable as attack input for later stages:
- authorization_ttl_seconds above 1e9 is rejected 422; spec states no upper bound.
- Unchanged pay-form resubmit re-sends the same POST with the same Idempotency-Key and body (server replays 200); a checker counting POST requests would see more than one.
- empty-requests is always in the DOM and hidden while requests exist.
- UI capture always sends {"amount":...} (final); extended mode (final:false) is API-only because the spec lists no control.
- Seeded expires_at echoed verbatim; seeded holds up to 2^53 accepted; capture error order 404 -> 403 -> not_open -> expired -> exceeds.
- Import accepts only plain-integer ttl; retry identity in page memory only; chromium only, no screen-reader pass.
- One unexplained 30 s transient in jury b1_quality run 1 (/ after logout), not reproduced in 3 reruns and a 20-iteration stress.
