# Dolphin Tank factory

Working evidence record, 1 October 2026. This document describes what exists and what remains unproved. It is not a submission-readiness certificate.

## Design and ownership

The factory separates implementation from acceptance. Each handoff carries the requirements, specification hash, owned files, revision, invariants, commands, results, risks and next owner. Requirements lead to observable properties and then concrete checks. The standing mandates stay generic so another team can reuse them for a different application.

| Seat | Responsibility | Recorded contribution |
| --- | --- | --- |
| Route | Decomposition, assignment, handoffs and stage report | Stage 1 requirement ledger and acceptance summary; Stage 2 ledger |
| Forge | Domain rules, validation, authentication and storage | Stage 1 domain `be0f7de`; Stage 2 authorization domain `fbe4573` |
| Loom | HTTP/UI integration, usability and packaging | Stage 1 HTTP/package `9cb0bc3`; Stage 2 UI `42fef7a` and refresh repair `dbf467c` |
| Trace | Concurrency, retry semantics and state transitions | Stage 1 state operations `36c4914`; Stage 2 state/upgrade work `a16ad67` |
| Jury | Independent acceptance, additional checks and verdict | Stage 1 evidence `2c9a5d4`, accepted source `0024598` |

All seats currently declare `Harness: Claude Code` and `Model: claude-sonnet-5-5`. These declarations must match the runtime used; any future change needs accurate provenance and declarations. The Git commits share an operator identity, so commit authors alone cannot establish which seat did the work. The room log and seat handoffs are needed alongside the file history.

## Reproduction procedure

1. Install BAND and authenticate the operator and model provider. Configure five separate seats using the files in `mandates/`, retaining their literal handles and actual runtime/model declarations.
2. Give all seats access to the official specifications, one shared absolute result-repository path, Git and a container runtime. This run uses native Windows BAND/Claude processes and Docker in WSL Ubuntu 24.04. The harness environment is `/root/dfv` in WSL.
3. Rehearse in a separate practice room/repository. For the submitted run, create a fresh room and result repository and freeze the mandates before dispatch.
4. Dispatch one stage specification to Route. Include the full requirements in delegated handoffs. Do not send further human messages before Route's final report. Advance stages by copying the accepted folder forward and changing only the new folder.
5. Jury checks the exact candidate revision, records uncovered requirements, runs proportionate additional checks, and returns ACCEPT or REJECT. An implementer repairs rejected work; Jury rechecks the changed candidate.
6. At completion, download BAND's **full session**, unchanged, as `room.json`. A CLI page or filtered text log is not a substitute. Review it for credentials and follow the guide's redaction/rotation procedure if needed.
7. Run the official offline check, then verify every claimed stage from a fresh clone in isolated mode and follow each `RUN.md`. Publish only evidence-supported claims.

Example commands from the official kickoff checkout, with paths adapted to the operator's environment:

```sh
python -m harness check /absolute/path/result --track pocketful
python -m harness run --track pocketful --repo /absolute/path/fresh-clone --all --mode isolated --out /absolute/path/new-check-output
```

The output directory must be new. These commands describe the procedure; they are not evidence that the unfinished four-stage result passed it.

## Recorded verification

Jury accepted Stage 1 source `0024598cf4a43b6584171b1f7b8f92523c652c3a`. Its [verdict](evidence/stage-1/jury/verdict.md) links the clean-checkout build, isolated-network checks, 147/147 shipped checks, additional API/concurrency/state checks and race-detector output. It also records flaws in early reviewer scripts, corrected before final runs. Those script bugs are not product rejections.

A separate operator harness report at `band-work/checks/s1-human-verify-1/report.json` records revision `cb2af8b83ea8f7ce87d4fb6da27fc86a030f357d`, isolated mode, 147/147 checks and claimed stage 1. It ran from 05:33:10.872358 to 05:33:46.369041 UTC on 1 October 2026. This is a local report, not yet a portable committed evidence artifact. A comparison of `stage-1/` between the accepted source and `dbf467c` showed no changes.

Stage 2 is not accepted. Route is waiting for Trace's supplied-value validation follow-up and Loom's integration/browser evidence before Jury review. Stages 3 and 4 have not been dispatched.

## Failures, limitations and autonomy

- **No demonstrated product rejection yet.** The committed history says Jury accepted Stage 1 on its first submission. Do not fabricate a rejection/repair story for the demo.
- **Autonomy is unresolved.** Final-room text history contains a human message at `2026-10-01T05:21:28.149217Z` asking Jury to resume Stage 1 after a provider limit. The participant guide prohibits human input between stage dispatch and the coordinator's final report, including continue messages. Calling this quota recovery does not establish an exemption. This run must not be advertised as proven compliant; a fresh autonomous run may be required.
- **Quota interruptions are real.** Stage 2 was dispatched at `2026-10-01T05:34:01.751419Z`. Trace and Loom were interrupted at about 10:32 UTC. Exact final-room runtimes were restarted at about 10:41 UTC, queued work redelivered, and both again reported a provider limit resetting at 16:10 Europe/London. No human room message or stage-source edit was made during that recovery.
- **Monitoring paths drifted.** The old watcher references `AppData/Local/Band/band.exe`; the installed command is now `AppData/Local/Programs/jam/bin/band.exe`. Recovery must resolve the installed CLI rather than assume the old location.
- **Reviewer acceptance has residual risks.** Stage 1's verdict records transport-level plain-text 400 responses, permissive interpretation of some imported state, and zero-share payment semantics. Acceptance by a seat does not establish hidden-suite success. Preserve those observations for later review.
- **Submission evidence is incomplete.** No full-room `room.json`, fresh-clone all-stage result, public repository, deployment, final media or receipt is present at this checkpoint.

Current room identifier: `5dd42746-f387-4763-afe0-f96d8f504f71`. Preserve this room's history even if a fresh submitted run becomes necessary.

## Measured time and cost

The current room's first Stage 1 dispatch is timestamped `2026-09-30T23:05:20.477357Z`. Stage 2 dispatch was `2026-10-01T05:34:01.751419Z`. Their difference includes verification and quota downtime; it is not active model time.

`band usage rooms --since 2026-09-30 --until 2026-10-01 --json`, inspected on 1 October, attributed **$15.0948856 estimated equivalent** and **33,967,803 reported tokens** across five sessions to the current room. BAND describes these as catalog estimates, not provider billing. Runtime restart warnings report missing session attribution; the same report includes unrelated/unattributed usage. Consequently **complete factory spend is UNKNOWN**. Do not present the attributed estimate as a complete cost or reconcile it by guessing. Route's earlier approximately $10.1 coordinator estimate is a separately reported figure, not a verified total.

Refresh and preserve the final attribution evidence before publishing measured economics. End-to-end completion time is UNKNOWN while the run remains unfinished.
