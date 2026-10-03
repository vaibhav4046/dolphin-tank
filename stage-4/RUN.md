# Pocketful — build and run

Build the image (needs network once, for the Go base image) and start it:

```sh
docker build -t pocketful-s4 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
```

The running container needs no network and no setup. State is in memory. The browser UI, its
scripts, stylesheets and fonts are embedded in the single binary: nothing is fetched at run time.

Health check:

```sh
curl -s http://localhost:8080/health
# {"status":"ok"}
```

Test-control endpoints (no authentication):

- `POST /_test/reset` — replace all state with the fixture in the body; `204`. A seeded payment may
  carry `created_at`; a future or malformed one is `422` and changes nothing. Dropping state also
  drops every statement snapshot token.
- `GET /_test/export` — `200` with `{"track":"pocketful","format_version":1,"state":{...}}`; the
  state includes every revision, every opening balance and every authorization's `closed_at`.
- `POST /_test/import` — replace all state with a previously exported object; `204`. Exports from
  the stage-1, stage-2 and stage-3 services are accepted and upgraded (revision 1 per payment, opening
  balances derived, `closed_at` filled in, settlement membership, corrections and snapshots kept;
  payments without `refund_of` read as `null`).

## Routes

Browser UI (`GET`, HTML, `Cache-Control: no-store`): `/` wallet, `/requests`, `/split`,
`/authorizations`, `/login`, `/signup`. `/requests` and `/authorizations` share their URL with
the JSON API: a request with `Accept: text/html` gets the UI, anything else gets JSON (and a
`401` error envelope without a bearer token). `/`, `/split`, `/login`, `/signup` always get the UI.

JSON API: `GET /me`, `POST /payments`, `POST /requests`, `GET /requests`, `POST /requests/{id}/pay|decline|cancel`,
`POST /splits`, `GET /activity`, `POST /settlements`, `POST /authorizations`, `GET /authorizations`,
`POST /authorizations/{id}/capture|void`, `POST /auth/signup`, `POST /auth/login`, `GET /health`,
the four stage-3 routes and the two stage-4 routes (all need a bearer token; unrecognized query
parameters are ignored):

- `GET /me?as_of=<instant>&known_at=<instant>` — the stage-2 wallet fields as of an instant, from
  what was known at another. Both optional; each supplied one is echoed back verbatim. Without
  either, the current corrected values.
- `GET /statement?from=&to=&known_at=&limit=&offset=` — the caller's money movements in `[from, to)`,
  oldest first by effective time, each with `delta` and running `balance_after`; the first read also
  returns an opaque `snapshot` token, and `GET /statement?snapshot=<token>&limit=&offset=` pages that
  exact result (only `limit` and `offset` may accompany it).
- `POST /payments/{id}/corrections` — sender only, `Idempotency-Key` required; body
  `{"expected_revision","amount","effective_at","reason"}`; `201` with the new revision, `200` on replay.
- `GET /payments/{id}/revisions` — `{"revisions":[...]}`, sender and receiver only.
- `POST /payments/{id}/refunds` — original receiver only, `Idempotency-Key` required; body `{"amount": n}`
  (integer 1..1000000000); `201` with the new refund payment (`refund_of` names the target,
  `request_id` and `authorization_id` null), `200` on replay. Refunds together may not exceed the
  payment's current corrected amount (`422 refund_exceeds_payment`); a refund cannot be refunded
  (`422 invalid_refund_target`); the money comes from the receiver's available funds
  (`409 insufficient_funds`). Every payment carries `refund_of` (`null` unless it is a refund).
- `POST /correction-batches` — settlement operator only, `Idempotency-Key` required; body
  `{"corrections":[{"payment_id","expected_revision","amount","effective_at","reason"}, ...]}` (1..32
  items, distinct payment ids); `201` with `correction_batch_id`, `recorded_at` and `revisions`, `200` on replay.

The browser wallet offers a Refund action on every payment the signed-in person received (amount
defaults to what the page knows is left; refused and unconfirmed outcomes are shown apart, and a retry
re-sends the same key). Batch corrections have no browser screen: they are an operator-only API.

Instants are RFC 3339 with an offset (`Z`, `z` or `+hh:mm`); a naive time, a bare date, an empty value,
or an offset whose `+` was not percent-encoded (`%2B`) is `422 validation_failed`.
Unknown paths and wrong methods return a JSON `404` envelope.

## Assets and fonts

Static files are served from `/assets/` (embedded from `web/`, `Cache-Control: no-cache`, no token
needed). The fonts are bundled, not linked: DM Sans (headings) and Inter (body), variable
`latin` subsets from the Fontsource distribution of the SIL OFL fonts, in `web/fonts/`
with their licences (`OFL-DM-Sans.txt`, `OFL-Inter.txt`). Nothing is requested from a CDN.

## Development

Go 1.24+, standard library only: `go vet ./... && go build ./... && go test ./...`.
Browser logic modules (Node 20+, no dependencies): `node --test jstest`.
