# Dolphin Tank

**An evidence-first autonomous software factory.**
Five BAND seats plan, implement, attack and independently verify each other's work. The judged
application is **Pocketful** — Dolphin Tank is the factory that builds it.

> Passing tests is not acceptance. Reproducible evidence is acceptance.

**Track:** Pocketful (WeAreDevelopers × BAND — Dark Factory)
**Run:** room `5dd42746-f387-4763-afe0-f96d8f504f71`, five seats, Claude Code / `claude-sonnet-5-5`
**Status:** 2026-10-02 20:35 UTC. Stage 1 and Stage 2 independently accepted; Stage 3 implemented
and repaired but **not yet accepted**; Stage 4 not started. **Not submission ready.**

---

## What the factory built

A four-stage financial service, in Go, one complete buildable folder per stage. Each folder is
the previous accepted folder copied forward and widened — never a final answer pasted backwards.

| Stage | What it adds | Shipped checks | Independent verdict |
|---|---|---|---|
| [`stage-1/`](stage-1/) | accounts, payments, requests, splits, activity feed, idempotency, reset, export/import, atomic settlement | 147/147 | **ACCEPT** — `0024598`, [`verdict`](evidence/stage-1/jury/verdict.md) |
| [`stage-2/`](stage-2/) | payment authorizations and captures, hold/partial/extended capture, void, real-clock expiry, `/me` held-aware funds, fixture seeding, stage-1 upgrade, browser UI | 147 + 35 | **ACCEPT** — `f33035a`, [`verdict`](evidence/stage-2/jury/verdict.md) |
| [`stage-3/`](stage-3/) | history: statements, snapshots, corrections with revisions, the hold timeline over time, import of earlier exports | 147 + 35 + 6 | **REJECT** at `3c7c411`, repaired to `5e6f83f`, **re-review open** — [`verdict`](evidence/stage-3/jury/verdict.md) |
| `stage-4/` | — | — | not started |

Fresh-clone verification of the current revision, run with the official harness in **isolated**
mode (internal network, outbound blocked):

```text
stage-1/  147/147  suite2 FAIL   ->  claims stage 1
stage-2/  147/147  35/35  suite3 FAIL ->  claims stage 2
stage-3/  147/147  35/35  6/6    suite4 FAIL ->  claims stage 3
overshoot: none in any folder
```

Each failing "next stage" check is deliberate and correct: a folder must **not** contain the
answer to the stage after it.

## The rejection that changed the work

Stage 3 was rejected with two reproducible defects, then cross-attacked into a third.

- **F1** — a seeded authorization with `status: expired` and a future `expires_at` pushed the
  service's clock two hours into the future. After one reset, an overdraft payment of 8001
  against 8000 available was **accepted**. Proved to be a stage-2 regression by running the same
  script against both images: 84/84 on stage 2, 79/5 on stage 3. → fixed in `ac96360`.
- **F2** — authorizations used a whole-second `created_at` while payments used microseconds, so
  a hold could be placed *after* the payment funding it. `GET /me?as_of=…` returned
  `available = -4000`, 25 times out of 25. The authors had accepted this as a risk; the reviewer
  ruled it a specification violation. → fixed in `11e76f9`.
- **L-F2-1** — found afterwards by the systems seat attacking a fix it did not write: an export
  from the rejected build carries `created_exact`, which import ignored. → fixed in `5e6f83f`.

The reviewer's own reproduction of F2 now scores 59 pass / 0 fail.

## Run it

Every stage is a self-contained service. Judges build the Dockerfile and talk HTTP only; the
service needs **no outbound network** at run time — fonts, scripts and styles are inside the
image.

```sh
cd stage-3
docker build -t pocketful-s3 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s3
curl http://localhost:8080/health          # {"status":"ok"}
```

Then open <http://localhost:8080/> for the browser application. Full instructions:
[`stage-1/RUN.md`](stage-1/RUN.md) · [`stage-2/RUN.md`](stage-2/RUN.md) ·
[`stage-3/RUN.md`](stage-3/RUN.md)

Verify a revision the way the competition does:

```sh
python -m harness run --track pocketful --repo <path-to-clone> --all --mode isolated --out <new-dir>
python -m harness check <path-to-clone> --track pocketful
```

## Where everything is

| Question | Path |
|---|---|
| How does each seat work? | [`mandates/`](mandates/) — five generic mandates, each naming its real harness and model |
| How was the factory designed, what did it cost, what failed? | [`FACTORY.md`](FACTORY.md) |
| The whole run, as Band recorded it | `room.json` |
| What did each stage require? | [`evidence/stage-1/`](evidence/stage-1/) · [`stage-2/`](evidence/stage-2/) · [`stage-3/`](evidence/stage-3/) |
| What did the shipped checks never ask? | [`evidence/stage-N/jury/gaps.md`](evidence/stage-3/jury/gaps.md) |
| What did each seat attack? | [`evidence/stage-3/trace/`](evidence/stage-3/trace/) |
| Which seat announced which commit? | [`evidence/operator/PROVENANCE.md`](evidence/operator/PROVENANCE.md) |
| Rejections and repairs | [`history/`](history/) and [`evidence/stage-3/decisions.md`](evidence/stage-3/decisions.md) |
| Measured cost and elapsed time | [`FACTORY.md`](FACTORY.md) §9 |
| Live demo and video | not yet produced |

## Honest limitations

Stage 3 is implemented, repaired and independently re-checked against the shipped checks, but
only the acceptor can accept it and that has not happened. Stage 4 is absent. The model
provider's usage limit ended three seat turns mid-task; the operator's recovery of those turns is
disclosed in [`FACTORY.md`](FACTORY.md) §8, together with the fact that **no seat ever asked the
operator for anything** — all six operator messages were three stage dispatches and three
provider-quota resumes. `go test -race` cannot run on the operator host; concurrency evidence
comes from the reviewer's race runs in WSL. All commits share one Git identity, so distribution
is evidenced by the room log and [`PROVENANCE.md`](evidence/operator/PROVENANCE.md) rather than
by authorship.

The official Pocketful specifications and the competition participant guide are authoritative.
Nothing here claims a result against withheld tests.
