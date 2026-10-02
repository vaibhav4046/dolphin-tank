# Operator verification — fresh clone, isolated mode, RUN.md executed literally

Recorded by ZEUS (the OpenCode orchestration layer, not a BAND seat) on 2026-10-02, against
revision `1a3d864`. Nothing in this file was produced by the band; it is the operator checking
the band's work the way a judge would, using only the official harness and the repository's own
instructions.

## 1. Offline gate check

```text
cd D:\project\dolphin-tank\dark-factory-wearedevs
python -m harness check ../band-work/result --track pocketful
```

```text
room.json is missing; open the room in the Band console …
1 problem(s)
```

One problem, and it is `room.json`. Layout, the `Dockerfile` and `RUN.md` in every stage folder,
mandate presence, harness/model headers, mandate genericity against the harness's own generated
track vocabulary, and the credential scan all pass.

## 2. Fresh clone, grading mode

```text
git clone <result repo> /tmp/zeus-fresh-clone      # brand-new directory, clean status
python -m harness run --track pocketful --repo /tmp/zeus-fresh-clone \
                      --all --mode isolated --out …/checks/zeus-freshclone-5e6f83f
```

`--mode isolated` is the grading configuration: an internal Docker network with outbound traffic
blocked.

| Folder | suite 1 | suite 2 | suite 3 | suite 4 | claimed | overshoot |
|---|---|---|---|---|:-:|:-:|
| `stage-1/` | 147/147 | **fail** | – | – | **1** | none |
| `stage-2/` | 147/147 | 35/35 | **fail** | – | **2** | none |
| `stage-3/` | 147/147 | 35/35 | 6/6 | **fail** | **3** | none |

Every next-stage check correctly **fails**: no folder carries a later stage's answer. Raw output:
`band-work/checks/zeus-freshclone-5e6f83f/`.

## 3. `RUN.md` executed literally, from a fresh clone

Every command below is copied from `stage-3/RUN.md`. Because the final image is `FROM scratch`
it has no shell, and because a Docker `--internal` network does not support published ports, the
service was probed from a **sibling container on the same internal network** — the same technique
the reviewer used.

| RUN.md promise | Result |
|---|---|
| `docker build -t pocketful-s3 .` | `Successfully built` |
| `curl -s http://localhost:8080/health` | `{"status":"ok"}` |
| UI routes `/`, `/requests`, `/split`, `/authorizations`, `/login`, `/signup` | **200** each |
| `/requests`, `/authorizations` share the URL with the JSON API | 200 HTML / 401 JSON |
| `/me`, `/requests`, `/activity`, `/authorizations` without a token | **401** |
| `/statement` without a token | **401** |
| `GET /_test/export` | **200**, `{"track":"pocketful","format_version":1,"state":{…}}` |
| `POST /_test/reset` | **204** |
| unknown path | `{"error":{"code":"not_found","message":"no such route"}}` |
| static files under `/assets/`, no token needed | `/assets/js/main.js`, `/assets/css/base.css`, `/assets/css/components.css`, `/assets/css/tokens.css` — **200** each |
| DM Sans + Inter bundled, not linked | `/assets/fonts/dm-sans.woff2`, `/assets/fonts/inter.woff2` — **200** each, OFL licences alongside |
| "Nothing is requested from a CDN" | **0 external URLs** in the served HTML |
| "The running container needs no network" | `https://example.com` and `telnet 1.1.1.1:53` both unreachable from the container's network |

## 4. Two codes that looked wrong and were not

Recorded because a verification that hides its own false alarms is not a verification.

- `GET /assets/main.js` → **404**. The operator's probe used the wrong path. The page references
  `/assets/js/main.js` and three stylesheets under `/assets/css/`, and all four return 200.
  Not a defect.
- `POST /_test/reset` with a hand-written fixture → **422**. The service answered
  `{"error":{"code":"validation_failed","message":"user u_a: password is required"}}`, which is
  correct: stage 3 requires a password on a seeded user. Re-posting the exact state the export
  endpoint returns gives **204**. Not a defect.

## 5. What this does not prove

The shipped stage-3 suite is 6 checks — 9% of the graded suite. A green run proves only what it
covers, and cannot stand in for `@jury`'s acceptance, which is still open. See `FACTORY.md` §10.
