# Pocketful — build and run

Build the image (needs network once, for the Go base image) and start it:

```sh
docker build -t pocketful-s1 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
```

The running container needs no network and no setup. State is in memory.

Health check:

```sh
curl -s http://localhost:8080/health
# {"status":"ok"}
```

Test-control endpoints (no authentication):

- `POST /_test/reset` — replace all state with the fixture in the body; `204`.
- `GET /_test/export` — `200` with `{"track":"pocketful","format_version":1,"state":{...}}`.
- `POST /_test/import` — replace all state with a previously exported object; `204`.

Local development (Go 1.24+, standard library only): `go vet ./... && go build ./... && go test ./...`.
