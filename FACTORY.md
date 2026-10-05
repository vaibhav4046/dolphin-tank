# Dolphin Tank — the factory

**Track:** Pocketful (WeAreDevelopers × BAND — Dark Factory)
**Submitted room:** `5dd42746-f387-4763-afe0-f96d8f504f71`
**Actual runtime:** Claude Code, model `claude-sonnet-5-5`, five seats
**Document state:** 2026-10-03 21:30 UTC. All four stages accepted (stage 4 source `1dd5560`);
`room.json` present — read §10 before quoting anything from this file.

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
| 3 | `5e6f83f` | **ACCEPT** | `evidence/stage-3/jury/r3-verdict.md` (`829e053`) |
| 4 | `f2698c2` refunds | **ACCEPT** | `evidence/stage-4/jury/forge-refunds/VERDICT.md` |
| 4 | `1dd5560` batch corrections | **ACCEPT** | `evidence/stage-4/jury/trace-batch/VERDICT.md` (`f2d512b`) |
| 4 | browser UI + Docker + regression | **ACCEPT** | `evidence/stage-4/jury/final/VERDICT.md` (`86bf3a7`) |

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

**Then the factory attacked its own repair.** `@trace`, which wrote the F1 repair but not the F2 one,
cross-attacked `@forge`'s F2 repair `11e76f9` at `ac96360` and found a third defect (`L-F2-1`): an export written by
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
git clone <result repo> /tmp/zeus-fresh-clone      # brand-new directory
python -m harness run --track pocketful --repo /tmp/zeus-fresh-clone \
                      --all --mode isolated --out <new dir>
```

`--mode isolated` is the grading configuration: an internal network with outbound traffic
blocked, so the result also proves the service needs no network at run time. Revision `f2d512b`,
exit 0.

| Folder | suite 1 | suite 2 | suite 3 | suite 4 | claimed | overshoot |
|---|---|---|---|---|:-:|:-:|
| `stage-1/` | 147/147 | **fail** | – | – | **1** | none |
| `stage-2/` | 147/147 | 35/35 | **fail** | – | **2** | none |
| `stage-3/` | 147/147 | 35/35 | 6/6 | **fail** | **3** | none |
| `stage-4/` | 147/147 | 35/35 | 6/6 | 5/5 | **4** | none |

Every negative check is correct: no folder contains a later stage's answer, which is what the
guide requires and what most teams get wrong by copying a final answer backwards. Because
`stage-4/` passes all four suites, the chain scores as a completed four-stage result rather than
three stages plus a folder that does not start.

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

The room log contains **7,216 messages. Exactly seven are human text** (plus one system
"participant joined" event, which carries no instruction). All seven were extracted and read in
full, and the count was re-verified from the raw room pages on 2026-10-03 rather than assumed:

| # | Time (UTC) | To | Nature |
|---|---|---|---|
| 1 | 2026-09-30T23:05:20 | `@route` | **Stage 1 dispatch** |
| 2 | 2026-10-01T05:21:28 | `@jury` | "your turn was cut off by a provider usage limit … resume … no new requirements" |
| 3 | 2026-10-01T05:34:01 | `@route` | **Stage 2 dispatch** |
| 4 | 2026-10-01T15:49:08 | `@route` | "the usage limit window has reset … resume … no change of scope" |
| 5 | 2026-10-01T21:57:54 | `@route` | **Stage 3 dispatch** |
| 6 | 2026-10-02T17:42:15 | `@route` | "your last turn ended before you answered trace's report … resume … no scope change" |
| 7 | 2026-10-02T22:48:17 | `@route` | **Stage 4 dispatch** |

In words: the four dispatches are 322, 537, 543 and 538 words (the task for each stage), and the
three resumes are 41, 44 and 42 words (127 in total), none containing a requirement. Seats wrote
about 103,000 words of text in the room against 2,067 from the human.

So: **four legitimate stage dispatches** — exactly what the guide allows ("you may dispatch each
stage separately or all four at once") — and **three mid-stage resumes**, all caused by the model
provider's usage limit, all explicitly adding no requirement and changing no scope. The first
resume is the weakest point: it addressed `@jury` directly rather than going through the
coordinator.

**What is true and verified:** no seat ever asked the human for anything. Of the messages the
seats sent back to the operator, **every one is a status report; none is a question**, and no seat
surfaced a blocker as a request for a decision. No requirement, scope or acceptance decision ever
changed because of a human intervention. On the substance of autonomy — the seats resolved their
own problems and never stopped to ask — the run holds.

**What is not true:** the guide's letter says to send nothing between dispatches. Three messages
were sent. Calling that crash recovery does not create an exemption the guide grants.

### The three resume messages and the limit event behind each

Every resume follows a provider usage-limit error recorded in the same export. Two limits are
reported per row: the nearest one before the resume, and the last one belonging to the seat the
resume actually addressed. They are not always the same event, so both are given.

| # | Resume time (UTC) | Addressed | Nearest usage-limit error before it | Gap | Last limit for the addressed seat | Gap |
|---|---|---|---|---|---|---|
| R1 | 2026-10-01T05:21:28 | `@jury` | 2026-09-30T23:57:20.140Z, sender Jury, "You've hit your session limit · resets 5am (Europe/London)" | 5h 24m | same event (Jury) | 5h 24m |
| R2 | 2026-10-01T15:49:08 | `@route` | 2026-10-01T10:32:35.817Z, sender Loom, "You've hit your session limit · resets 4:10pm (Europe/London)" | 5h 16m | 2026-10-01T05:43:08.252Z, sender Route, "You've hit your session limit · resets 11:10am (Europe/London)" | 10h 06m |
| R3 | 2026-10-02T17:42:15 | `@route` | 2026-10-02T12:25:25.213Z, sender Forge, "You've hit your session limit · resets 5:40pm (Europe/London)" | 5h 16m | 2026-10-02T07:55:39.858Z, sender Route, "You've hit your session limit · resets 12:40pm (Europe/London)" | 9h 46m |

Each of the three came after a provider limit had stopped a seat, and each added no requirement.
The room text says so in its own words: R1 ends "No new requirements."; R2 ends "No new
requirements and no change of scope."; R3 ends "No new requirements, no scope change."

R1 is the one that addressed `@jury` directly. In R2 and R3 the nearest limit error belongs to a
different seat (Loom, then Forge) while the resume went to `@route`, because Route was the
coordinator and had itself also hit limits. All 30 usage-limit events by seat: Trace 9, Forge 7,
Loom 6, Jury 4, Route 4. The export holds 32 `error` events in total; the other two are Claude Code
background-task failures, not provider limits.

Reproduce with:

```sh
python tools/room_stats.py room.json
```

**Operator runtime restarts are not messages.** The room export holds 30 usage-limit error events
(session and weekly limits) and the room does not resume on its own. Recovering meant restarting the
affected seat runtimes so Band would redeliver the queued handoffs. That is a daemon
operation and it was done many times; the restarts were not counted, so no number is claimed.
The human message count above is 7, measured from the raw export after all of them, so none of
the restarts added anything to the room. Apart from those seven, the operator sent no message to
any seat.

We are not claiming this run is unambiguously compliant on that point. It is stated here so a
judge reads it from us first.

### Operator activity during the run

Disclosed as a count, with no argument attached.

Method. The run window is the first and last timestamp in `room.json`:
2026-09-30T23:05:19.754Z to 2026-10-03T20:00:36.066Z. Every commit in the repository was taken
by **author** time. A commit counts as referenced when its SHA appears as a hex token in the
`content` or `metadata` of any room message, at full length or as a 7-character prefix.

| Measure | Count |
|---|---:|
| Commits in the repository | 98 |
| Commits with author time inside the run window | 82 |
| Of those, referenced by SHA in a room message | **82 (100%)** |
| Of those, **not** referenced by SHA in any room message | **0** |
| Commits with author time outside the window | 16 |
| Outside-window commits that touch `stage-1/` .. `stage-4/` | **0** |
| Commits anywhere in history that touch `stage-1/` .. `stage-4/` | 40 |
| Distinct Git author identities in the whole repository | 1 |

So there is no commit inside the run window without a room message naming it, and no commit
outside the window that touches stage code.

The 16 outside the window are one commit before the run and fifteen after it:

| SHA | Author time | Side | Subject | Files | Touches `stage-*/` |
|---|---|---|---|---:|---|
| `f190358` | 2026-10-01T00:05:01 | before | chore: freeze generic seat mandates | 7 | no |
| `b1919d1` | 2026-10-03T21:08:15 | after | docs: record stage 4 fully accepted at 1dd5560 | 3 | no |
| `8aaf697` | 2026-10-03T21:22:34 | after | evidence: add room.json (unedited full-session export) | 4 | no |
| `e07ad9c` | 2026-10-03T22:25:38 | after | docs: final measured figures | 3 | no |
| `5abdc13` | 2026-10-03T22:43:56 | after | evidence: final fresh-clone verification at e79ea48 | 9 | no |
| `15dd391` | 2026-10-03T22:50:34 | after | docs: correct elapsed time and cross-attack summary | 2 | no |
| `359531a` | 2026-10-03T23:55:09 | after | docs: final measured figures and release scoreboard | 3 | no |
| `e7ea0b6` | 2026-10-04T00:22:05 | after | docs: link the showcase, demo video and deck | 2 | no |
| `87762c4` | 2026-10-04T01:03:56 | after | docs: replace the restarts count with the measured figure | 2 | no |
| `153ff39` | 2026-10-04T09:00:15 | after | docs: measured active room time, human word counts, MIT licence | 4 | no |
| `4c2273c` | 2026-10-04T17:35:01 | after | docs: concrete stand-up runbook, what failed | 4 | no |
| `8392d23` | 2026-10-04T20:32:35 | after | evidence(operator): verification of the public anonymous clone | 2 | no |
| `2b470df` | 2026-10-04T22:12:55 | after | docs: README opens with the problem and the proof | 2 | no |
| `fbe4ece` | 2026-10-05T01:03:36 | after | evidence(operator): re-verify the published head anonymously | 2 | no |
| `3f5b6e6` | 2026-10-05T12:19:58 | after | evidence(operator): record the run 1 vs run 2 swap decision | 2 | no |
| `424a3af` | 2026-10-05T21:15:05 | after | evidence, tools: machine count of who edited stage code | 5 | no |

`f190358` is the freeze of the five seat mandates, written before the first dispatch so the
mandates could not be tailored to what the seats were about to build. The fifteen after the run
are operator documentation and verification evidence. None of the sixteen touches stage code.

Two limits on this disclosure:

- It is scoped to commits. A file change made and never committed would not appear. The separate
  machine count in `evidence/operator/PROVENANCE.md` covers the tool calls, and reports that the
  coordinator seat made zero stage-code edits.
- `evidence/operator/PROVENANCE.md` was generated at an earlier revision and its coverage counts
  (80 commits, 64 announced) are stale against the 98 commits above. Its per-commit index is
  unaffected, because each row is keyed by SHA.

## 9. Measured cost and elapsed time

From `band usage rooms`, which reports catalog **estimates at list prices, not provider
billing**:

```text
room 5dd42746 (submitted run)   55 sessions   487,800,071 tokens   $196.92
   @jury   $59.37   (30.1%)
   @trace  $50.31   (25.5%)
   @forge  $35.95   (18.3%)
   @route  $27.35   (13.9%)
   @loom   $23.94   (12.2%)
room 7e2f1aa9 (earlier Codex attempt)  $94.16
room a4b60871 (toy rehearsal)         $15.26
```

Measured 2026-10-03 22:48 UTC, after the coordinator's final report, so these are final rather
than interim. `band usage agents` attributes the same work slightly differently ($70.53 jury,
$55.24 trace, $37.74 forge, $30.91 route, $26.47 loom) because it attributes by live binding
before the session ledger; the room-scoped figures above are the ones published because they
cover exactly the submitted run.

The per-seat split matters more than the total: no seat carried the run, which is what the
rubric actually reads.

Elapsed, first Stage-1 dispatch to the last room message: **68.9 hours wall clock**
(2026-09-30T23:05:20Z to 2026-10-03T20:00:27Z). Most of that is waiting, not working.

**Measured active room time: about 10 hours.** Method: sort all 7,216 room events by timestamp
and add up the gaps between consecutive events that are no longer than a threshold; longer gaps
count as idle. The result barely moves with the threshold, so it is not a tuning artefact:

```text
gap threshold    active    idle
  3 min           8.7 h    60.2 h
  5 min           9.3 h    59.7 h
 10 min          10.2 h    58.7 h
 15 min          10.2 h    58.7 h
 30 min          10.6 h    58.3 h
```

The idle time is the provider's usage-limit windows (30 usage-limit error events in the room
export). The eight longest gaps run 4.3 to 5.4 hours, which is the length of a five-hour
session window, plus one 10.7-hour gap on 2026-10-03 (a weekly limit, then the operator
restarting the seats). This is room-activity time, not billed model time, and the active
figure is the one to compare with a run that never hit a limit. Reproduce it from `room.json`.

For scale: the full four-stage chain reached, with one rejection/repair cycle, one cross-attack that found a
third defect and four further cross-attacks that found nothing, cost about **$197 of model spend** (estimate at list prices).

## 10. Known limitations

1. **Stage 4 is fully accepted** (all three items, source `1dd5560`). Batch corrections were accepted
   on 697 independent checks plus 11 deliberate mutations, all 11 caught, with real exports built
   from the accepted stage-1/2/3 commits and imported; the browser/Docker/regression item was
   accepted afterwards (`86bf3a7`) once the acceptor's turn was re-delivered.
2. **The provider usage limit is a real operational hazard.** It ended seat turns repeatedly
   (30 usage-limit error events in the room export) and cost wall-clock time. It is the reason for
   every resume in §8.
3. **`go test -race` cannot run on the operator host** (needs cgo; no gcc). It was run inside a
   container by the reviewer — `go test -count=1 -race ./...` ok in 363 s at stage 3.
4. **All commits share one Git identity**, so authorship alone cannot show distribution. The
   bridge is `evidence/operator/PROVENANCE.md`, which maps each commit to the room message that
   announced it. `room.json` is the authoritative record (full-session download, unedited).
5. **Shipped-check coverage is thin at the top end** — stage 3 ships 6 checks (9% of its graded
   suite) and stage 4 ships 5 (16%). A stage judged mostly on withheld tests is exactly why this
   document leans on independent checks rather than green runs.
6. **True provider billing is unknown.** The dollar figure is a list-price estimate from
   `band usage rooms`. Active room time is measured (about 10 hours, §9); it is room activity,
   not model-seconds.
7. **`room.json` was downloaded after the work was complete**, so it holds the whole run but
   not any later activity; it is the unedited Band export (7,216 messages) and `harness check`
   passes with it present.
8. **Two known accessibility findings, disclosed rather than quietly fixed.** An independent
   product-quality pass (`evidence/operator/PRODUCT-QUALITY.md`, 134 checks) found that the wallet
   route `/` renders four `h2` sections and **no `h1`**, while all five other routes have a
   proper `h1`; and that one link on `/signup` measures 40 × 44 px at a 390 px viewport, 4 px
   short on width. Both are low severity. They sit in `stage-4/`, which is band-owned code, so
   they were **not patched by the operator** — anything an operator commits under `stage-N/` is
   code the band did not write — and they were **not injected into the room** either, because a
   "fix the h1" message between a stage dispatch and the coordinator's final report is exactly
   the steering the guide prohibits. Recording them here costs two minor findings and saves the
   autonomy evidence. The same pass found zero horizontal overflow, zero clipped elements, an
   accessible name on every interactive element across all 30 route × viewport combinations, a
   visible focus indicator on every tab stop, a skip link first in the tab order, and no console
   errors.

## 11. Standing up this factory on a different problem

Everything here ran on Windows 11 with Band Desktop 0.4.12 and the `band` CLI, with Docker inside
WSL2. Only commands and incidents that actually happened are listed.

**Setup**

1. Install Band Desktop, sign in, run `band preflight`. Install Docker inside WSL2 and the
   official harness in a venv there (the harness needs Docker).
2. Create one Band agent per seat. Each seat is a persistent agent with a parked runtime:

   ```text
   band agent create --name <Name> --description "<one line>" \
       --cwd <ABSOLUTE path of the shared result repository> \
       --session seat-<name> --transport <runtime> --runtime-model <model> \
       --instructions "$(cat mandates/<name>.md)"
   ```

   The five Claude Code seats used `--transport claude-code-cli` with the parked template pointed
   at the native `claude.exe`. The abandoned OpenCode run (section 11a) used `--transport opencode
   --runtime-model opencode/space-bunny-free`. Seats may share a runtime and a model.
3. Give every seat the same **absolute** path to the result repository. A seat in its own sandbox
   cannot resolve a relative path and will create a repository only it sees.
4. Freeze the mandates. Copy `mandates/` and change only the handle table and the two header lines
   (`Harness:`, `Model:`), which must state what the seat really runs. Keep them generic.
5. Rehearse on the unscored practice track in a **separate** room and repository.

**Run**

6. Create the room and add the seats: `band chat new --session seat-<coordinator> --with
   <owner>/<seat>`. The CLI prints a harmless decode error and adds only the first participant, so
   add the rest one at a time with `band chat add <room-id> <owner>/<seat>` and check
   `band room participants <room-id>`.
7. Dispatch from Git Bash (PowerShell mangles quotes): `band room send <room-id> "$(cat
   dispatch.txt)" --mention <coordinator-id>`. `dispatch/dispatch-template.md` is the generic
   shape of the four dispatches in `room.json`: track, specification path, absolute repository
   path, the harness command, rules. The coordinator pastes the full requirement set into every
   delegated handoff.
8. Advance by **copying the accepted folder forward** and widening only the new folder. Delete any
   nested `.git` in the copy, or the folder will build for you and arrive empty for a judge.
9. Let the acceptor reject freely. A rejection that changes the work is the most valuable artefact
   this factory produces.
10. When a seat stalls on a provider limit or a crashed runtime, restart the runtime, not the
    conversation: `band restart --session seat-<name> --host-session default-<room-id>`. That is a
    daemon operation and adds no room message; Band redelivers the queued handoff.

**Close**

11. Open the room in the Band console (an account that owns the room), choose Download, then
    **Download full session**. Check the message count equals the room total: a first attempt can
    export only the messages the page had loaded. Save it unchanged as `room.json`.
12. Run `python -m harness check --track <track> <repo>`, then verify every claimed stage from a
    fresh clone of the public repository with `harness run --all --mode isolated`.
13. Measure active time rather than quoting wall clock: `python tools/active_time.py room.json`.

What this costs: five seats, one coordinator, about **$197 of model spend** (list-price estimate,
not a bill) and about 10 hours of measured active room time for an accepted four-stage financial
service, including one full rejection/repair cycle and one cross-attack that found a third defect.

### Minimum stand-up

Ten commands, all of them already shown above, for standing this factory up on a new problem.
Nothing here is new and nothing here was not run.

```sh
band preflight                                   # readiness: Docker, agent runtime, login
band agent create --name <Name> --description "<one line>" \
  --cwd <ABSOLUTE result repo> --session seat-<name> \
  --transport <runtime> --runtime-model <model> \
  --instructions "$(cat mandates/<name>.md)"    # one seat per role
band chat new --session seat-<coordinator> --with <owner>/<seat>
band chat add <room-id> <owner>/<seat>           # one at a time, then verify
band room participants <room-id>                # confirm all five joined
band room send <room-id> "$(cat dispatch.txt)" --mention <coordinator-id>
band restart --session seat-<name> --host-session default-<room-id>   # on a provider limit
python -m harness check --track <track> <repo>                        # eligibility
python -m harness run --track <track> --repo <fresh clone> --all --mode isolated
python tools/room_stats.py room.json             # proof the room log backs the claims
```

Before the first dispatch, copy `mandates/` out of git and change only the handle table and the
two header lines. Keep them generic. Dispatch from Git Bash, not PowerShell.

## 11a. What we tried that failed

Judges asked what failed. These are the real incidents, in the order they cost time.

1. **Setup.** The operator's standalone Claude login had expired, so every seat failed with an
   expired-session error until the login was redone. The npm `claude` shim timed out under the
   runtime, so the templates were pointed at the native `claude.exe`. The bare context mode needs an
   API key, so the seats use the local-config context mode. A careless `taskkill /IM claude.exe`
   would have killed the host session; processes are killed by PID only. Docker was not installed
   on the host and went into WSL2 (3 GB memory cap).
2. **A parallel Codex run.** A separate room with five `codex-app-server` seats built a stage 1
   candidate and its own evidence, then every seat stopped on 2026-10-02T15:48Z with "You've hit
   your usage limit". It was never used for the submission.
3. **Provider usage limits on the submitted run.** The room export holds 30 usage-limit error events
   (session and weekly). They produced the 58.7 hours of idle time in section 9 and the three
   resume messages in section 8. A seat that is restarted after a limit does not always wake on its
   own; one seat needed a human message to resume, which is disclosed.
4. **A second, clean run on OpenCode with the `space-bunny-free` model (2026-10-04).** Five new
   seats, one single dispatch for all four stages, no usage limit. Both the dispatch and the seats
   worked at first: a 97-row requirement ledger, a container surface and a service core were
   committed. Then the OpenCode runtimes died twice ("runtime exited before the ACP handshake", at
   09:24Z and 11:55Z), the coordinator closed stage 1 as unaccepted because the acceptor's turn had
   been cut off, and it stood the band down for good. The host had 2.8 GB of 15.7 GB free with five
   OpenCode runtimes, Docker in WSL2, a browser and the operator's own session running together.
   We stopped the seats and kept the first run as the submission, because resuming would have added
   human messages and there was not enough time to finish four stages. Lesson: leave headroom for
   concurrent seats and do not run an unattended factory on a memory-starved host.
5. **Early wrong claims in our own write-up.** FACTORY.md once said "Trace wrote neither fix"
   (Trace wrote the F1 repair and attacked Forge's F2 repair), once said usage-limit restarts
   happened "four times" (the room holds 30 limit events and the restarts were not counted), and
   once said active time was not measured. All three were corrected against `room.json`.

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
