# loom decisions, stage 4 (refund handler, refund control, Dockerfile, RUN.md)

Spec states no browser control for refunds (ledger B12 is a route decision). Where the spec is silent I chose the reading with least new behaviour.

1. **Where the Refund action lives.** On the wallet activity feed only, because that is the only place payments are listed. It is offered when the signed-in user is the receiver (`to_user_id`) and the payment is not itself a refund. The service stays the authority: the page never hides a refusal by guessing, it only avoids offering an action that is certain to be refused (refund of a refund, sender's own payment).
2. **Default amount, never invented.** Default = the payment's amount shown in the feed minus the refunds of it present in the loaded feed pages. A corrected amount is not in the feed (the feed shows originals), so it is learned only after the service answers `refund_exceeds_payment`, by reading `GET /payments/{id}/revisions` (an endpoint the receiver may read); the typed text is kept and the limit sentence updates. Known limit: if earlier refunds sit on feed pages not loaded yet, or the payment was corrected upward elsewhere, the shown remainder can be off; the service decides and the refusal text says so.
3. **Idempotent attempt identity.** Same tracker as pay/capture: scope `refund:<payment id>`, fingerprint = the typed amount text. Unchanged text keeps the key whatever the last outcome was (lost response, refusal); changed text mints a new key. The key is kept in page memory only, so a full reload mints a new one (same as stages 2/3).
4. **Uncertain vs refused.** Network failure, timeout or 5xx/unparseable 2xx = "Unconfirmed" dashed notice (role status) with a retry that re-sends the same key and body; any 4xx = "Not completed" notice (role alert) with a reason. Messages: insufficient_funds, refund_exceeds_payment, invalid_refund_target, forbidden, not_found, validation_failed (messages.js `refundRefusalText`; unknown codes fall back to the server message).
5. **Input preserved.** Draft text, open/closed state and the last notice are kept per payment across feed re-renders; success clears the draft only. After a success the learned corrected amount is kept (resetting it would offer a stale remainder again).
6. **Refund payments in the feed.** Row text "You refunded @x" / "@x refunded you", a "Refund of <payment id>" chip with a return glyph. The id is shown because it is the only name a payment has.
7. **Handler.** `handlers_refund.go` registers via `subActions["/payments/"]["refunds"]` (routes.go untouched) and mirrors `handleCorrect`: key header, JSON object body, `ReqAmount` (integer 1..1e9; unknown fields ignored), then `st.Refund`. Error order is forge's domain order. 201 first time, 200 replay from the store.
8. **Visual.** Refund block uses existing tokens only (raised surface, rim light, radii 5/16); no new colours, weights or shadows. Skip link got `min-height: 44px` (a 40 px target found by the touch-target check).
9. **Image.** `pocketful-s4`; `.dockerignore` unchanged from the baseline; no network at run time (fonts/scripts/styles are `go:embed`ded).

## Not done / limits
- No browser screen for `POST /correction-batches` (operator-only API; brief says none).
- 403 / 404 / invalid_refund_target refusal texts were exercised with mocked response envelopes in the browser (the page cannot reach those states against a real server without a stale tab); the handler-level codes are covered by `handlers_refund_test.go` through the real router.
- Firefox/WebKit not run; Chromium 145 only.
