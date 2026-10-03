# Operator verification — fresh clone, all four stages, grading mode

Recorded by ZEUS (the OpenCode orchestration layer, not a BAND seat) on 2026-10-03 against
revision `f2d512b`. Nothing here was produced by the band; it is the operator checking the band's
work the way a judge would, using only the official harness and the repository's own instructions.

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

## 2. Fresh clone, grading mode, all four stages

```text
git clone <result repo> /tmp/zeus-fresh-clone-s4      # brand-new directory, clean status
python -m harness run --track pocketful --repo /tmp/zeus-fresh-clone-s4 \
                      --all --mode isolated --out …/checks/zeus-freshclone-f2d512b
```

`--mode isolated` is the grading configuration: an internal Docker network with outbound traffic
blocked, so this also proves the result needs no network at run time.

| Folder | tracked files | suite 1 | suite 2 | suite 3 | suite 4 | claimed | overshoot |
|---|---:|---|---|---|---|:-:|:-:|
| `stage-1/` | 34 | 147/147 | **fail** | – | – | **1** | none |
| `stage-2/` | 87 | 147/147 | 35/35 | **fail** | – | **2** | none |
| `stage-3/` | 116 | 147/147 | 35/35 | 6/6 | **fail** | **3** | none |
| `stage-4/` | 130 | 147/147 | 35/35 | 6/6 | 5/5 | **4** | none |

```text
  stage-1/: claims stage 1 on the shipped checks
  stage-2/: claims stage 2 on the shipped checks
  stage-3/: claims stage 3 on the shipped checks
  stage-4/: claims stage 4 on the shipped checks
exit 0
```

Two properties matter here and both hold:

1. **The chain scores.** Every folder claims its stage, and `stage-4/` carries all four suites,
   so the submission is a completed four-stage result rather than three stages plus a folder that
   does not start.
2. **Nothing overshoots.** Every next-stage check correctly **fails** — `stage-1/` cannot pass
   suite 2, `stage-2/` cannot pass suite 3, `stage-3/` cannot pass suite 4 — and `overshoot` is
   `null` on all four. This is what the guide requires and what most entries get wrong by copying
   a final answer backwards.

Also verified: no nested `.git` directory inside any stage folder (the guide records that a
folder which is its own repository builds for you and arrives empty for a judge), and every stage
folder has both a `Dockerfile` and a `RUN.md`.

Raw output: `band-work/checks/zeus-freshclone-f2d512b/summary.json` and the per-stage
`report.json` / `*.counts.json`.

## 3. `RUN.md` executed literally, offline (stage 3)

Because the final image is `FROM scratch` it has no shell, and Docker does not support published
ports on an `--internal` network, the service was probed from a **sibling container on the same
internal network** — the technique the reviewer used.

| `RUN.md` promise | Result |
|---|---|
| `docker build -t pocketful-s3 .` | `Successfully built` |
| `curl -s http://localhost:8080/health` | `{"status":"ok"}` |
| `/`, `/requests`, `/split`, `/authorizations`, `/login`, `/signup` | **200** each |
| `/me`, `/requests`, `/activity`, `/authorizations`, `/statement` without a token | **401** |
| `GET /_test/export` | **200**, `{"track":"pocketful","format_version":1,"state":{…}}` |
| `POST /_test/reset` | **204** |
| unknown path | `{"error":{"code":"not_found","message":"no such route"}}` |
| `/assets/js/main.js`, `/assets/css/{base,components,tokens}.css` | **200** each |
| `/assets/fonts/dm-sans.woff2`, `/assets/fonts/inter.woff2` | **200** each |
| "Nothing is requested from a CDN" | **0 external URLs** in the served HTML |
| "The running container needs no network" | `example.com` and `1.1.1.1:53` both unreachable |

## 4. Independent spec-literal probe (stage 3)

38 checks written from the words of `stage-3.md` rather than from the implementation — inclusive
`as_of` bounds, verbatim echo, tie-break ordering, `opening + Σdelta = closing`, pagination
stability, statement privacy, revision visibility, all four correction error codes, zero-amount
reversal counted once, and the snapshot rules.

```text
== ZEUS spec-literal probe: 38 pass, 0 fail, 38 checks ==
```

Details and the five defects this probe found in itself: `SPEC-PROBE.md`.

## 5. Independence of the review, measured

- All commits share **one** Git identity, so authorship cannot show distribution. The bridge is
  \PROVENANCE.md\, which maps each commit to the room message that announced it.
- Model spend for the submitted room, \and usage rooms\, measured 2026-10-03 22:48 UTC after the
  coordinator's final report: **\.92 estimated** at list prices (an equivalent, not a bill),
  55 sessions, 487,800,071 tokens. Per seat: jury \.37 (30.1%), trace \.31 (25.5%),
  forge \.95 (18.3%), route \.35 (13.9%), loom \.94 (12.2%). No seat carried the run.
- Elapsed wall clock, first Stage-1 dispatch 2026-09-30T23:05:20Z to the coordinator's final
  report, is **68.9 hours**, and that includes four provider usage-limit outages and long idle
  gaps. Active model time is not measured and is not claimed.

## 6. What this does not prove

The shipped stage-3 and stage-4 suites are 6 and 5 checks — 9% and 16% of the graded suites. A
green run proves only what it covers. It cannot stand in for the acceptor's judgement, it says
nothing about the withheld tests, and `evidence/operator/PROVENANCE.md` is derived evidence that
does not replace `room.json`. See `FACTORY.md` §10.
