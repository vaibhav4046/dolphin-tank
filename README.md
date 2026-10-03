# Dolphin Tank

**An evidence-first autonomous software factory.**
Five BAND seats plan, implement, attack and independently verify each other's work. The judged
application is **Pocketful** — Dolphin Tank is the factory that builds it.

> Passing tests is not acceptance. Reproducible evidence is acceptance.

**Track:** Pocketful (WeAreDevelopers × BAND — Dark Factory)
**Run:** room `5dd42746-f387-4763-afe0-f96d8f504f71`, five seats, Claude Code / `claude-sonnet-5-5`
**Status:** 2026-10-03 20:00 UTC. **All four stages independently accepted**, the last at
`1dd5560` (stage 4 source unchanged since). Stage 4 was cross-attacked clean by the two seats that
did not write each part. `room.json` is the unedited full-session download (7,216 messages, 2026-09-30T23:05Z to
2026-10-03T20:00Z); `harness check` passes.

---

## What the factory built

A four-stage financial service, in Go, one complete buildable folder per stage. Each folder is
the previous accepted folder copied forward and widened — never a final answer pasted backwards.

| Stage | What it adds | Shipped checks | Independent verdict |
|---|---|---|---|
| [`stage-1/`](stage-1/) | accounts, payments, requests, splits, activity feed, idempotency, reset, export/import, atomic settlement | 147/147 | **ACCEPT** — `0024598`, [`verdict`](evidence/stage-1/jury/verdict.md) |
| [`stage-2/`](stage-2/) | payment authorizations and captures, hold/partial/extended capture, void, real-clock expiry, `/me` held-aware funds, fixture seeding, stage-1 upgrade, browser UI | 147 + 35 | **ACCEPT** — `f33035a`, [`verdict`](evidence/stage-2/jury/verdict.md) |
| [`stage-3/`](stage-3/) | history: statements, snapshots, corrections with revisions, the hold timeline over time, import of earlier exports | 147 + 35 + 6 | **ACCEPT** — `5e6f83f`, [`verdict`](evidence/stage-3/jury/r3-verdict.md), evidence `829e053` |
| [`stage-4/`](stage-4/) | refunds and corrected history, batch corrections, the browser refund control | 147 + 35 + 6 + 5 | refunds **ACCEPT** `f2698c2`; batch corrections **ACCEPT** `1dd5560` (697 own checks, 11/11 mutations); UI/Docker/regression item **ACCEPT** (`86bf3a7`) |

Fresh-clone verification of revision `f2d512b`, run with the official harness in **isolated**
mode (internal network, outbound blocked):

```text
stage-1/  147/147  suite2 FAIL        ->  claims stage 1
stage-2/  147/147  35/35   suite3 FAIL ->  claims stage 2
stage-3/  147/147  35/35   6/6    suite4 FAIL ->  claims stage 3
stage-4/  147/147  35/35   6/6    5/5   ->  claims stage 4     exit 0
overshoot: none in any folder
```

Two things to read out of that table. **The chain scores**: `stage-4/` carries all four suites, so
this is a completed four-stage result rather than three stages plus a folder that does not start.
And **nothing overshoots**: every failing "next stage" check is deliberate and correct — a folder
must *not* contain the answer to the stage after it, which is what most entries get wrong by
copying a final answer backwards.

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

The reviewer's own reproduction of F2 now scores 59 pass / 0 fail, and the stage-3 re-review
accepted the repair with the race detector run (`go test -count=1 -race ./...`, 363 s) and every
stage-1/2 regression suite at 0 fail.

Stage 4 then followed the same loop: three implementers wrote disjoint parts, each attacked the
other's work (**forge 297 PASS / 0 FAIL** on batch corrections, **trace 83 black-box checks all
pass** on refunds), and the acceptor ran 697 of its own checks plus **11 deliberate mutations,
all 11 caught**, importing real exports built from the accepted stage-1, stage-2 and stage-3
commits.

## Run it

Every stage is a self-contained service. Judges build the Dockerfile and talk HTTP only; the
service needs **no outbound network** at run time — fonts, scripts and styles are inside the
image.

```sh
cd stage-4
docker build -t pocketful-s4 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
curl http://localhost:8080/health          # {"status":"ok"}
```

Then open <http://localhost:8080/> for the browser application. Full instructions:
[`stage-1/RUN.md`](stage-1/RUN.md) · [`stage-2/RUN.md`](stage-2/RUN.md) ·
[`stage-3/RUN.md`](stage-3/RUN.md) · [`stage-4/RUN.md`](stage-4/RUN.md)

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

All four stages are independently accepted; stage 4's three items (refunds `f2698c2`, batch
corrections `1dd5560`, browser/Docker/regression `86bf3a7`) were accepted after the provider
usage limit had interrupted the acceptor once. The provider
usage limit ended seat turns several times across the run; recovery meant restarting the affected
runtimes so Band would redeliver the queued handoffs, which is a daemon operation and added
**nothing** to the room. Disclosed in [`FACTORY.md`](FACTORY.md) §8, together with the measured
fact that of 7,004 room messages exactly **seven are human** — four legitimate stage dispatches
and three provider-quota resumes — and that **no seat ever asked the operator for anything**:
every seat→operator message is a status report, not a question. `go test -race` cannot run on the operator host (no cgo); the reviewer ran
it inside a container. All commits share one Git identity, so distribution is evidenced by the
room log and [`PROVENANCE.md`](evidence/operator/PROVENANCE.md) rather than by authorship.
`room.json` was downloaded from the Band console as **Download full session** and committed
byte-for-byte unchanged (SHA-256 `e9b69df9...62f97e`). It was read for credential shapes before
commit; none were found.

Two accessibility findings are known and disclosed rather than patched, because the code is
band-owned: the wallet route `/` has no `h1` (it renders four `h2` sections; every other route
has a proper `h1`), and one "Log in" link on `/signup` is 40 × 44 px at a 390 px viewport. Both are
low severity; the reasoning is in [`FACTORY.md`](FACTORY.md) §10. An independent pass over the
same build found zero horizontal overflow and zero clipped elements at all five viewports, an
accessible name on every interactive element, a visible focus ring on every tab stop, a skip link
first in the tab order, and no console errors — see
[`PRODUCT-QUALITY.md`](evidence/operator/PRODUCT-QUALITY.md).

The official Pocketful specifications and the competition participant guide are authoritative.
Nothing here claims a result against withheld tests.
