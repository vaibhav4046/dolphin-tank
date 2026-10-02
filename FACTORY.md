# Dolphin Tank — the factory

**Track:** Pocketful (WeAreDevelopers × BAND — Dark Factory)
**Submitted room:** `5dd42746-f387-4763-afe0-f96d8f504f71`
**Actual runtime:** Claude Code, model `claude-sonnet-5-5`, five seats
**Document state:** 2026-10-02 20:31 UTC (21:31 BST). Stage 3 acceptance is **still open** —
read §9 before quoting anything from this file.

This document was written by the operator, as the participant guide requires. Every number in
it comes from a command that was run or a file in this repository. Where something is not
proven it says so. Nothing here is a submission-readiness certificate.

---

## 1. The thesis

> **Passing tests is not acceptance. Reproducible evidence is acceptance.**

Every stage ships only a fraction of its checks (Pocketful: 79%, 35%, 9%, 16% for stages 1–4).
A green run on the shipped checks therefore proves almost nothing about the specification. This
factory treats that gap as the actual work, and its answer is a fixed loop:

```text
SPECIFICATION  ->  REQUIREMENT  ->  OBSERVABLE PROPERTY  ->  IS IT COVERED?
                                                            /            \
                                                      YES                NO
                                                       |                  |
                                                  REPRODUCE        DERIVE AN ATTACK
                                                       \                  /
                                                            EVIDENCE
                                                               |
                                                     ACCEPT or REJECT
```

The independent seat may not accept on the strength of the shipped checks. Before accepting, it
must answer in writing: **what does the specification require that the supplied checks never
demonstrated?** — and then write and run checks for exactly that. Those questions and their
answers are in `evidence/stage-*/jury/gaps.md` and `evidence/stage-*/jury/ledger.md`.

## 2. Seat topology

| Seat | Handle | Owns | Harness / model |
|---|---|---|---|
| Coordinator | `@route` | spec read, decomposition, delegation, handoffs, acceptance routing, evidence, stage report | Claude Code / `claude-sonnet-5-5` |
| Backend implementer | `@forge` | domain rules, validation, persistence, service internals | Claude Code / `claude-sonnet-5-5` |
| Interface implementer | `@loom` | browser application, its states, integration, accessibility, packaging | Claude Code / `claude-sonnet-5-5` |
| Systems implementer | `@trace` | concurrency, time, history, migrations, idempotency; attacks work it did not author | Claude Code / `claude-sonnet-5-5` |
| Independent acceptor | `@jury` | verification; the only ACCEPT or REJECT | Claude Code / `claude-sonnet-5-5` |

All five seats ran the same harness and model, which the guide permits. The headers in
`mandates/*.md` state this exactly and were not edited afterwards.

The five mandates in `mandates/` are **generic**. They describe how a seat works — what it owns,
how it takes work, when it rejects, how it reports — and name no endpoint, field, error code or
track term. Another team could point them at a compiler, an ecommerce API or a task manager and
they would still make sense. Track detail lives only in the task the coordinator pastes into the
room, which is where the guide says it belongs.

## 3. Handoff protocol and the evidence contract

Every delegation carries the whole task inline. Pointing a seat at a room message id is not
enough; the coordinator pastes the requirements.

```text
WORK_ITEM              SPECIFICATION_SOURCE      SPECIFICATION_HASH
REQUIREMENTS_INCLUDED  DEPENDENCIES              CURRENT_COMMIT
FILES_OWNED            EXPECTED_INVARIANTS       ACCEPTANCE_CRITERIA
EXECUTION_COMMANDS     TEST_RESULTS              ADDITIONAL_ATTACKS
KNOWN_RISKS            UNPROVEN_ASSUMPTIONS      NEXT_OWNER
```

An implementer returns:

```text
IMPLEMENTATION_COMMIT  FILES_CHANGED  COMMANDS_RUN
RESULTS                LIMITATIONS    EVIDENCE_PATHS
```

Three properties this buys, all visible in the room log:

1. **Self-contained.** A seat can act on one message without reading room history.
2. **Falsifiable.** Every claim names a command and an evidence path.
3. **Asymmetric authority.** `@jury` is the only seat that may accept, and it never fixes what
   it rejects — it reports a defect with a reproduction and stops.

## 4. Requirement ledger

Each stage gets `evidence/stage-N/requirement-ledger.md`, written from the specification
**before** any source was read, so the ledger cannot be reverse-engineered from the code.

```text
id · source_section · requirement · observable_property · owner
implementation_location · public_check_coverage · additional_check_coverage
evidence · status
```

| Stage | Ledger | Requirements |
|---|---|---|
| 1 | `evidence/stage-1/requirement-ledger.md` | R01–R90 |
| 2 | `evidence/stage-2/requirement-ledger.md` | S01–S66 |
| 3 | `evidence/stage-3/requirement-ledger.md` | T01–T65 |

## 5. Independent acceptance

`@jury` builds the exact candidate revision from a clean checkout, runs the official harness in
isolated mode, writes its **own** checks against the gaps it identified, runs browser and
offline passes, and only then returns ACCEPT or REJECT with counts and paths. It records the
flaws in its own early test scripts too, and keeps the failed runs — a rejection count is only
worth something if the reviewer is also fallible and shows it.

| Stage | Candidate | Verdict | Evidence |
|---|---|---|---|
| 1 | `0024598` | **ACCEPT** | `evidence/stage-1/jury/verdict.md` (`2c9a5d4`) |
| 2 | `f33035a` | **ACCEPT** | `evidence/stage-2/jury/verdict.md` (`9111851`) |
| 3 | `3c7c411` | **REJECT** | `evidence/stage-3/jury/verdict.md` (`54cbd0b`) |
| 3 | `5e6f83f` | **OPEN** | repairs landed; re-review not yet performed |

## 6. A real rejected candidate, and the repair path

This is the part of the factory worth reading, because it is the part that cannot be staged.

**JURY rejected stage 3 at `3c7c411` with two defects, each reproduced deterministically.**

**F1 — a seeded value ratcheted the service's clock into the future.** A fixture
authorization with `status: expired` and a *future* `expires_at` had that future value adopted
as its close time, which fed the monotonic stamp source. After a single reset, every later
payment was stamped about two hours ahead, a seeded open hold counted as expired immediately,
and a payment of 8001 against 8000 available was **accepted (201)** instead of refused (409).
JURY proved it was a regression by running its own accepted-stage-2 script against both images:
84/84 on stage 2, 79/5 on stage 3.
→ repaired in `ac96360`: seeded and imported values never move the clock.

**F2 — historical views showed impossible balances.** Authorizations carried a whole-second
`created_at` while payments carried microseconds, so a hold could be placed *after* the payment
that funded it. `GET /me?as_of=…` then returned `available = -4000` and `held > total`, 25 times
out of 25, for any back-to-back client. The authors had recorded this as an accepted risk; JURY
ruled it a specification violation, not a taste question.
→ repaired in `11e76f9`: one clock and one precision for every timestamp that orders money and
holds.

**Then the factory attacked its own repair.** `@trace`, which did not write either fix,
cross-attacked `11e76f9` at `ac96360` and found a third defect (`L-F2-1`): an export written by
the rejected build carries `created_exact`, and on import that field was ignored, so a hold could
still land before its funding payment. `@forge` repaired it in `5e6f83f`. JURY's own F2
reproduction, `t3_holds.py`, now scores **59 pass / 0 fail** against `5e6f83f`.

Four things are worth noticing:

- The rejection **changed the work**. It is not decoration.
- The fix for F2 removed a decision the authors had explicitly made and written down
  (`evidence/stage-3/decisions.md` revokes `D-HOLD-TIME`).
- A seat attacked a fix it did not write, and the attack found a real third bug.
- The run also **declined** work on the record: `D-IMPORT-FUTURE` was considered and rejected as
  out of specification (`71d08d4`), rather than every idea being implemented.

## 7. Verification actually performed

Official harness, unmodified, from the official kickoff checkout. Evidence:
`band-work/checks/zeus-freshclone-5e6f83f/` (operator workspace).

```text
git clone <result repo> /tmp/zeus-fresh-clone          # brand-new directory
python -m harness run --track pocketful --repo /tmp/zeus-fresh-clone \
                      --all --mode isolated --out <new dir>
```

`--mode isolated` is the grading configuration: an internal network with outbound traffic
blocked, so the result also proves the service needs no network at run time.

| Folder | suite 1 | suite 2 | suite 3 | suite 4 | claimed | overshoot |
|---|---|---|---|---|:-:|:-:|
| `stage-1/` | 147/147 | **fail** | – | – | **1** | none |
| `stage-2/` | 147/147 | 35/35 | **fail** | – | **2** | none |
| `stage-3/` | 147/147 | 35/35 | 6/6 | **fail** | **3** | none |

Every negative check is correct: no folder contains a later stage's answer, which is what the
guide requires and what most teams get wrong by copying a final answer backwards.

Independent JURY evidence, at `3c7c411`, before the repairs:

- own checks: `t3_time 46/0` ×3, `t3_fixture 67/0` ×3, `t3_statement 72/0`, `t3_corr 97/0` ×3,
  `t3_snap 52/0` ×3 (688 snapshot reads under six writers), `t3_import 57/0` against **real**
  stage-1 and stage-2 exports, `t3_race 48/0` ×3 (~11k requests each), `t3_scale 20/0`
  (20,000 seeded payments, 50-way burst under 5 s);
- stage-1 and stage-2 regression suites re-run against the stage-3 image;
- browser (Playwright chromium, 375/768/1280): `b1_quality 146/0`, `b2_wallet 84/0`,
  `b3_flows 82/0`, `b4_upgrade 19/0`, `b5_visual 18/0`, `b6_states 26/0`;
- offline: `docker network create --internal`, a sibling container unable to reach 1.1.1.1 or
  8.8.8.8, all six routes, three stylesheets, `main.js` and both woff2 fonts served from the
  image, no external URL anywhere.

## 8. Final autonomy — read this honestly

The guide requires that, from a stage dispatch until the coordinator's final report, **the
dispatched task is the only human input**, and that an implementer never pauses waiting for a
reply.

The room log contains **4,864 messages. Exactly six are from the human.** All six were extracted
and read in full:

| Time (UTC) | To | Nature |
|---|---|---|
| 2026-09-30T23:05:20 | `@route` | **Stage 1 dispatch** |
| 2026-10-01T05:21:28 | `@jury` | "your turn was cut off by a provider usage limit … resume … no new requirements" |
| 2026-10-01T05:34:01 | `@route` | **Stage 2 dispatch** |
| 2026-10-01T15:49:08 | `@route` | "the usage limit window has reset … resume … no change of scope" |
| 2026-10-01T21:57:54 | `@route` | **Stage 3 dispatch** |
| 2026-10-02T17:42:15 | `@route` | "your last turn ended before you answered trace's report … resume … no scope change" |

So: three legitimate stage dispatches, exactly as the guide allows ("you may dispatch each
stage separately or all four at once"), and **three mid-stage resumes**, all caused by the model
provider's usage limit, all explicitly adding no requirement and changing no scope. The first
resume is the weakest point: it addressed `@jury` directly rather than going through the
coordinator.

**What is true and verified:** no seat ever asked the human for anything. Of the six messages
the seats sent back to the operator, **all six are status reports; zero are questions**, and no
seat surfaced a blocker as a request for a decision. No requirement, scope or acceptance
decision ever changed because of a human intervention. On the substance of autonomy — the seats
resolved their own problems and never stopped to ask — the run holds.

**What is not true:** the guide's letter says to send nothing between dispatches. Three
messages were sent. Calling that crash recovery does not create an exemption the guide grants.

We are not claiming this run is unambiguously compliant on that point. It is stated here so a
judge reads it from us first.

## 9. Measured cost and elapsed time

From `band usage rooms`, which reports catalog **estimates at list prices, not provider
billing**:

```text
room 5dd42746 (submitted run)   27 sessions   292,591,022 tokens   $120.75
   @jury   $32.16   (26.6%)
   @trace  $31.52   (26.1%)
   @forge  $21.06   (17.4%)
   @route  $18.56   (15.4%)
   @loom   $17.44   (14.4%)
room 7e2f1aa9 (earlier Codex attempt)  $47.08
room a4b60871 (toy rehearsal)         $15.26
```

The per-seat split matters more than the total: no seat carried the run, which is what the
rubric actually reads.

Elapsed, first Stage-1 dispatch to now: **≈45.4 hours wall clock**
(2026-09-30T23:05:20Z → 2026-10-02T20:31Z). That figure **includes three provider quota
outages and long idle gaps, so it is not active model time** — active model time is not measured
and is not claimed.

## 10. Known limitations

1. **Stage 3 is not accepted.** The shipped checks pass and JURY's own F2 reproduction passes,
   but only `@jury` can accept, and it has not re-reviewed since rejecting `3c7c411`.
2. **Stage 4 does not exist.** The guide treats a missing folder as claiming nothing, so the
   chain still scores stage 3 — but stage 4 is unfinished, not skipped by choice.
3. **The provider usage limit is a real operational hazard.** It ended three seat turns
   mid-task. It is the reason for every resume in §8.
4. **`go test -race` cannot run on the operator host** (needs cgo; no gcc). Concurrency evidence
   comes from JURY's race runs in WSL and from non-race stress runs.
5. **All commits share one Git identity**, so authorship alone cannot show distribution. The
   bridge is `evidence/operator/PROVENANCE.md`, which maps 50 of 53 commits to the room message
   that announced them.
6. **Shipped-check coverage for stage 3 is 9%.** Six checks. A stage judged mostly on withheld
   tests is exactly why this document leans on independent checks rather than green runs.
7. **Elapsed active time and true provider billing are unknown** and are not estimated.

## 11. Standing up this factory on a different problem

1. Install BAND, authenticate the operator and the model provider, and configure **at least
   three** seats — each its own identity, each with a mandate naming its real harness and model.
2. Give every seat the same **absolute** path to the result repository. A seat working in its own
   sandbox cannot resolve a relative path and will otherwise create a repository only it sees.
3. Rehearse on the unscored practice track in a **separate** room and repository.
4. Freeze the mandates. Copy `mandates/` verbatim; keep them generic.
5. Dispatch one stage to the coordinator. It pastes the full requirement set into every delegated
   handoff and sends nothing further until the coordinator's final report.
6. Advance by **copying the accepted folder forward** and widening only the new folder. Delete
   any nested `.git` in the copy, or the folder will build for you and arrive empty for a judge.
7. Let the acceptor reject freely. A rejection that changes the work is the most valuable
   artefact this factory produces.
8. At the end, download the **full** room session as `room.json`, run `harness check`, then
   verify every claimed stage from a fresh clone in isolated mode.

What this costs: five seats, one coordinator, and roughly **$120 of model spend** to reach
accepted stage 2 and a working stage 3 for a four-stage financial service — including one full
rejection/repair cycle and one cross-attack that found a third defect.

## 12. Where to look

| Question | File |
|---|---|
| What did each stage require, and is it met? | `evidence/stage-N/requirement-ledger.md` |
| What did the shipped checks never ask? | `evidence/stage-N/jury/gaps.md` |
| What did the acceptor decide, and why? | `evidence/stage-N/jury/verdict.md` |
| What did the systems seat attack? | `evidence/stage-3/trace/` |
| Which seat announced which commit? | `evidence/operator/PROVENANCE.md` |
| What did decisions get revoked? | `evidence/stage-3/decisions.md` |
| How does each seat work? | `mandates/` |
| What is the whole room? | `room.json` |
