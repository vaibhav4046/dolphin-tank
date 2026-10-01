# Dolphin Tank

An evidence-first software factory built around five collaborating BAND seats. The judged application is **Pocketful**; Dolphin Tank is the factory that builds and verifies it.

## Current status

Work in progress, recorded 1 October 2026. **Not submission ready.**

| Deliverable | Evidence / status |
| --- | --- |
| Stage 1 | Jury accepted source commit `0024598cf4a43b6584171b1f7b8f92523c652c3a`; recorded shipped checks: 147/147. See [verdict](evidence/stage-1/jury/verdict.md). |
| Stage 2 | Operator isolated check: Stage 1 147/147, Stage 2 35/35, claimed stage 2 at `dbf467c`. [Evidence](evidence/operator/stage-2-dbf467c/REVIEW.md). Jury acceptance pending. |
| Stages 3–4 | Not implemented. |
| Final room export | Missing; download the full session from BAND when the run ends. |
| Autonomous-run eligibility | Unresolved: Stage 1 received a human recovery message before its final report. See [FACTORY.md](FACTORY.md). |
| Public repository, showcase, video, slides, submission receipt | Not yet delivered. |

These are recorded results, not a claim of passing hidden checks or current end-to-end submission verification.

## Run Pocketful

Stage 1 is the accepted API service:

```sh
cd stage-1
docker build -t pocketful-s1 .
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
```

Then request `http://localhost:8080/health`. See [Stage 1 instructions](stage-1/RUN.md). The running service keeps state in memory; the specification provides reset, export and import endpoints. Building requires the Go base image; the service needs no outbound network at runtime.

The browser application under [stage-2](stage-2/RUN.md) is an unfinished candidate. Do not treat it as accepted or use it to infer a Stage 2 result.

## How the factory works

Route derives observable requirements from the written specification and assigns work. Forge, Loom and Trace implement distinct parts. Jury independently checks the submitted revision and can reject it. A green shipped suite is evidence, not the whole acceptance decision: the reviewer records what it did not prove and exercises the remaining requirements.

- [Generic seat mandates](mandates/)
- [Factory setup, provenance and limitations](FACTORY.md)
- [Stage 1 requirements](evidence/stage-1/requirement-ledger.md)
- [Independent checks and logs](evidence/stage-1/jury/)
- [Recorded rejection history](history/)

The official Pocketful specifications and competition participant guide are authoritative. The submission must eventually include a whole-room BAND export, accurate harness/model declarations, reproducible stage folders, and a fresh-clone isolated check.
