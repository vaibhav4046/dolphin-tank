# Pocketful — build and run

Build the image (needs network once, for the Go base image) and start it:

```sh
docker build -t pocketful-s2 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2
```

The running container needs no network and no setup. State is in memory. The browser UI, its
scripts, stylesheets and fonts are embedded in the single binary: nothing is fetched at run time.

Health check:

```sh
curl -s http://localhost:8080/health
# {"status":"ok"}
```

Test-control endpoints (no authentication):

- `POST /_test/reset` — replace all state with the fixture in the body; `204`.
- `GET /_test/export` — `200` with `{"track":"pocketful","format_version":1,"state":{...}}`.
- `POST /_test/import` — replace all state with a previously exported object; `204`.

## Routes

Browser UI (`GET`, HTML, `Cache-Control: no-store`): `/` wallet, `/requests`, `/split`,
`/authorizations`, `/login`, `/signup`. `/requests` and `/authorizations` share their URL with
the JSON API: a request with `Accept: text/html` gets the UI, anything else gets JSON (and a
`401` error envelope without a bearer token). `/`, `/split`, `/login`, `/signup` always get the UI.

JSON API: `GET /me`, `POST /payments`, `POST /requests`, `GET /requests`, `POST /requests/{id}/pay|decline|cancel`,
`POST /splits`, `GET /activity`, `POST /settlements`, `POST /authorizations`, `GET /authorizations`,
`POST /authorizations/{id}/capture|void`, `POST /auth/signup`, `POST /auth/login`, `GET /health`.
Unknown paths and wrong methods return a JSON `404` envelope.

## Assets and fonts

Static files are served from `/assets/` (embedded from `web/`, `Cache-Control: no-cache`, no token
needed). The fonts are bundled, not linked: DM Sans (headings) and Inter (body), variable
`latin` subsets from the Fontsource distribution of the SIL OFL fonts, in `web/fonts/`
with their licences (`OFL-DM-Sans.txt`, `OFL-Inter.txt`). Nothing is requested from a CDN.

## Development

Go 1.24+, standard library only: `go vet ./... && go build ./... && go test ./...`.
Browser logic modules (Node 20+, no dependencies): `node --test jstest`.
