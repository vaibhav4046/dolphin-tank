# Stage 4 route summary

- Accepted source commit: `1dd55604328167f20af96d6c69989289381bbf47`. `git diff 1dd5560 HEAD -- stage-4` is empty at 86bf3a7 (later commits are evidence, docs and history only). Three jury verdicts, all ACCEPT, all on this tree: S4-FORGE-REFUNDS (f2698c2), S4-TRACE-BATCH (`evidence/stage-4/jury/trace-batch/VERDICT.md`, committed f2d512b), S4-LOOM-UI-AND-STAGE-REGRESSION (`evidence/stage-4/jury/final/VERDICT.md`, committed 86bf3a7).
- Spec: `stage-4.md` sha256 `1894b002f8827fd36623df4ecf3deb204e20d7fafbbfa671894a114db80e6df1`, 4449 bytes, 71 lines; ledger `evidence/stage-4/requirement-ledger.md` (U01-U43, B01-B12).
- Seats (commit attribution in `evidence/operator/PROVENANCE.md`): forge = refund domain API and limits in Correct (ada0ac3, 53fdc42), correction-vs-held-funds tests (f2698c2), attack on batch corrections (2eba3ac); loom = refund route, wallet refund control, UI tests, RUN.md (3a61608, 620e5df); trace = `POST /correction-batches`, `Revision.correction_batch_id`, real stage-3 export fixture (e3eb44c), tests-only fix (1dd5560, edit by forge), attack on refunds x batches (5a951db); jury = the only accept decision, three verdicts; route = ledger, handoffs, decisions.
- Rejections: none in stage 4. No jury REJECT and no cross-attack defect. The one repair after the first batch commit was test expectations only (1dd5560: stage-3 tests follow `correction_batch_id` null); no production code changed.

## Verification the jury ran at 1dd5560 (real output in the two verdict files)
- `gofmt -l .` empty; `go vet ./...` exit 0; `go test -count=1 ./...` ok (49.5 s and 43.1 s on two clean worktrees); `node --test jstest` 21 pass 0 fail.
- Batch path: 697 own HTTP checks 0 fail, 11 of 11 deliberate faults caught, 26 stage-1/2/3 scripts re-run on the stage-4 image 0 fail 0 5xx, real stage-1/2/3 exports imported.
- Image: `docker build` and `--no-cache --network none` OK, 9.44 MB scratch image; `docker run --network none` only `lo`, no DNS, all routes and assets served from the binary; RUN.md commands as written.
- Shipped harness, isolated mode: highest contiguous stage 4; stage-4 folder passes stages 1-4.
- Browser (Chromium, image): earlier-stage UI scripts all 0 fail; b7_stage4 128/0; b8_upgrade34 25/0; b10_targets 20/0; UI mutation check 11 of 11 caught. U42 on the exact image binary: 143/0, all ten write paths replay 200 identical, key reuse 409, 12 concurrent same-key calls one effect.

## Route decisions the jury accepted
D-B8 (no snapshot tokens in export; accepted stage-3 binary 5e6f83f behaves the same), D-B1, D-B2, `correction_batch_id` null on non-batch revisions.

## Demanded by the spec but not exercised by the shipped checks, and how it was covered
The shipped harness carries 5 stage-4 checks (16%). Everything else came from seat-written checks: refund limits and the refund-of-settlement-member case (forge domain tests, trace 83 black-box checks, jury forge-refunds script); batch atomicity, precedence of the four existing codes, net-effect affordability, strictly later `recorded_at`, snapshot stability, replay and race (jury_batch_1..6); stage-1/2/3 export import with membership and corrections retained; refund control states, labels, contrast, palette, type, radii and shadows in the browser (b1..b10); no-network image (b11).

## Not run / limitations
- `go test -race` unrun at stage 4 (no cgo on the operator host or the jury's); it ran in a container at stage 3 only.
- Chromium only; 320 px and 200% zoom not run; docker ran in WSL. Four refusal texts (403, 404, `invalid_refund_target`, `validation_failed`) cannot be provoked from the UI and were checked with mocked envelopes only.
- D-B8 residual: a grader that expects a statement token to keep paging after export/import of the same service would fail stage 3 and stage 4 alike; the spec text does not require it.
- Observations, not rejections: wallet route `/` has four h2 and no h1; "Log in" link is 40x44 px (both already disclosed in `FACTORY.md`); after a refund whose response was lost but committed, a refresh shows "Nothing left to refund" under the still-visible "Unconfirmed ... retry" notice (cosmetic, money correct); `expected_revision` 1e30 -> 409 `stale_revision`; `effective_at` of year 0000/0001 accepted.
- Cost: route did not instrument per-seat spend; `FACTORY.md` carries the operator's whole-chain figure.

## Stale text to correct
`FACTORY.md` (header state line, §10 item 1) and `README.md` (status line, stage table row, closing paragraph) were written while the UI/Docker item was in review and still say stage 4 is not fully accepted. The operator owns those files; this summary supersedes them.
