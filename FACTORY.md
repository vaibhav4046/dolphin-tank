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
| 1 | `evidence/stage-1/requirement-ledger.md` | R01–R90 (90 rows) |
| 2 | `evidence/stage-2/requirement-ledger.md` | S01–S66 (66 rows) |
| 3 | `evidence/stage-3/requirement-ledger.md` | T01–T65 (65 rows) |
| 4 | `evidence/stage-4/requirement-ledger.md` | U01–U43 and B01–B12 (52 rows) |

Stage 4 is the awkward one and the ledger says so itself. The `U` rows are the written stage-4
specification: `pocketful/spec/stage-4.md` is 71 lines and adds refund and batch-correction
behaviour, but **no written UI rule at all**. The `B` rows are therefore not derived from the
specification — they come from the operator's run brief for stage 4, and the ledger heads that
section "operator brief; no new spec rule". The `U` numbering is also not contiguous: 40 of the
43 ids are present (`U17`, `U18` and `U19` are absent). Stating that here rather than rounding it
to "43 requirements".

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

Official harness, unmodified, from the official kickoff checkout.

**Correction to this section (2026-10-06).** It previously headed the block below with
`band-work/checks/zeus-freshclone-5e6f83f/`. That path **is not in this repository** — it lives
in the operator's own workspace — and the run it names does not support the table. Its
`summary.json` on disk covers **folders 1 to 3 only** and carries `"preview": true`; it has no
row for `stage-4/`, and it does not name revision `f2d512b` at all. Quoting it as the evidence
for a four-stage result was wrong. Everything below is now cited to files that are committed
here, so a judge can open them.

```text
git clone <result repo> /tmp/zeus-fresh-clone      # brand-new directory
python -m harness run --track pocketful --repo /tmp/zeus-fresh-clone \
                      --all --mode isolated --out <new dir>
```

`--mode isolated` is the grading configuration: an internal network with outbound traffic
blocked, so the result also proves the service needs no network at run time.

| Committed evidence | What it is | Revision |
|---|---|---|
| `evidence/operator/FRESH-CLONE-VERIFICATION.md` | operator fresh clone, `--all --mode isolated`, exit 0. Source of the per-folder table below | `f2d512b` |
| `evidence/operator/PUBLIC-CLONE-VERIFICATION.md` | **anonymous** `git clone --depth 1` of the public GitHub URL with `GIT_TERMINAL_PROMPT=0`; `harness check` exit 0 and `harness run --all --mode isolated` exit 0 | `4c2273c`, re-verified from scratch at `2b470df` |
| `evidence/operator/final-fresh-e79ea48/report.json` | the machine-readable harness report (147/35/6/5, `claimed_stage` 4, `overshoot` null, `mode` isolated) | `e79ea48` |

The anonymous public clone is the stronger of these, because it exercises the exact path a judge
without Band Desktop membership or a GitHub account takes. It is the primary release evidence;
the per-folder table below is quoted from the operator fresh-clone note, which is the only
committed file that records those four rows.

| Folder | suite 1 | suite 2 | suite 3 | suite 4 | claimed | overshoot |
|---|---|---|---|---|:-:|:-:|
| `stage-1/` | 147/147 | **fail** | – | – | **1** | none |
| `stage-2/` | 147/147 | 35/35 | **fail** | – | **2** | none |
| `stage-3/` | 147/147 | 35/35 | 6/6 | **fail** | **3** | none |
| `stage-4/` | 147/147 | 35/35 | 6/6 | 5/5 | **4** | none |

**This result still applies to the current head.** `git diff f2d512b HEAD -- stage-1 stage-2
stage-3 stage-4` is empty: stage code is byte-identical between the revision that was verified
and this revision, across every commit in between. Likewise
`git diff 2b470df HEAD -- stage-1 stage-2 stage-3 stage-4` is empty, and every commit after the
anonymous re-verification touched only `README.md`, `FACTORY.md`, `JUDGE-GUIDE.md`,
`history/`, `tools/` and `evidence/operator/`. None of them can have changed what the harness
measures.

The fresh-clone verification runs that *are* committed live at
`evidence/operator/final-fresh-e79ea48/` (all four stages),
`evidence/operator/fresh-c1b8416/` (stages 1 and 2) and
`evidence/operator/stage-2-dbf467c/` (stages 1 and 2, the external review in section 8.2).
Those three directories are the complete list; there is no `evidence/operator/evidence/`
directory in this repository.

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
| Commits in the repository | 100 |
| Commits with author time inside the run window | 82 |
| Of those, referenced by SHA in a room message | **82 (100%)** |
| Of those, **not** referenced by SHA in any room message | **0** |
| **Of those 82, written by the operator** | **14** (section 8.2) |
| Commits with author time outside the window | 18 |
| Outside-window commits that touch `stage-1/` .. `stage-4/` | **0** |
| Commits anywhere in history that touch `stage-1/` .. `stage-4/` | 40 |
| Distinct Git author identities in the whole repository | 1 |

So there is no commit inside the run window without a room message naming it, and no commit
outside the window that touches stage code.

Read the "referenced" row with its own weakness in view, because it is the weakest number in
this document. The rule counts a commit SHA appearing **anywhere** in the export, including
inside the `tool_result` echo of a `git log` a seat ran itself. Applying the stricter rule —
the SHA must appear in a seat's own `text`, `thought` or `task` message — **12** of the 82 drop
out, and **11** of those 12 are operator commits (the twelfth is Forge's `6e35abc`). So
"82 (100%)" is not evidence that a human or a seat discussed each commit. It is evidence that
each commit is *traceable inside the export*. The stronger statement is in 8.2.

The 18 outside the window are one commit before the run and seventeen after it. Author times are
**UTC**, matching the run window above; an earlier version of this table printed local time
(+01:00) under a UTC heading, which was off by an hour on every row.

| SHA | Author time (UTC) | Side | Subject | Files | Touches `stage-*/` |
|---|---|---|---|---:|---|
| `f190358` | 2026-09-30T23:05:01 | before | chore: freeze generic seat mandates | 6 | no |
| `b1919d1` | 2026-10-03T20:08:15 | after | docs: record stage 4 fully accepted at 1dd5560 | 2 | no |
| `8aaf697` | 2026-10-03T20:22:34 | after | evidence: add room.json (unedited full-session export) | 3 | no |
| `e07ad9c` | 2026-10-03T21:25:38 | after | docs: final measured figures | 2 | no |
| `5abdc13` | 2026-10-03T21:43:56 | after | evidence: final fresh-clone verification at e79ea48 | 12 | no |
| `15dd391` | 2026-10-03T21:50:34 | after | docs: correct elapsed time and cross-attack summary | 1 | no |
| `359531a` | 2026-10-03T22:55:09 | after | docs: final measured figures and release scoreboard | 2 | no |
| `e7ea0b6` | 2026-10-03T23:22:05 | after | docs: link the showcase, demo video and deck | 1 | no |
| `87762c4` | 2026-10-04T00:03:56 | after | docs: replace the restarts count with the measured figure | 1 | no |
| `153ff39` | 2026-10-04T08:00:15 | after | docs: measured active room time, human word counts, MIT licence | 3 | no |
| `4c2273c` | 2026-10-04T16:35:01 | after | docs: concrete stand-up runbook, what failed | 3 | no |
| `8392d23` | 2026-10-04T19:32:35 | after | evidence(operator): verification of the public anonymous clone | 1 | no |
| `2b470df` | 2026-10-04T21:12:55 | after | docs: README opens with the problem and the proof | 1 | no |
| `fbe4ece` | 2026-10-05T00:03:36 | after | evidence(operator): re-verify the published head anonymously | 1 | no |
| `3f5b6e6` | 2026-10-05T11:19:58 | after | evidence(operator): record the run 1 vs run 2 swap decision | 1 | no |
| `424a3af` | 2026-10-05T20:15:05 | after | evidence, tools: machine count of who edited stage code | 4 | no |
| `7b611f4` | 2026-10-05T21:48:18 | after | docs: operator activity disclosure, judge guide, stand-up block | 2 | no |
| `d984122` | 2026-10-05T21:58:15 | after | docs: judge map at the top, exact commit count, verified identity claim | 1 | no |

`f190358` is the freeze of the five seat mandates, written before the first dispatch so the
mandates could not be tailored to what the seats were about to build. The seventeen after the run
are operator documentation and verification evidence. None of the eighteen touches stage code.

### 8.2 Fourteen operator commits **inside** the run window

**This subsection did not exist before 2026-10-06 and the omission was ours.** Section 8 above
originally disclosed only the commits outside the window and left the impression that all 82
in-window commits were band output. They were not. Fourteen of them are operator commits, made
while the room was live, and one of those fourteen contains work produced by an **AI outside the
Band room entirely**. Every claim below is checkable, and the check is named.

| SHA | Author time (UTC) | Open stage at that moment | Subject |
|---|---|---|---|
| `c1b8416` | 2026-10-01T10:53:02 | **2** (dispatched 05:34Z, not yet accepted) | docs: record factory provenance and independent stage 2 review |
| `cc952b8` | 2026-10-01T11:07:37 | **2** | evidence: preserve fresh clone isolated stage 1 and 2 results |
| `c830f82` | 2026-10-02T20:30:50 | **3** (stage 4 not dispatched until 22:48:17Z) | evidence(operator): provenance index |
| `2e76ca0` | 2026-10-02T20:32:33 | **3** | docs: rewrite FACTORY.md against verified evidence |
| `66b45bb` | 2026-10-02T20:33:33 | **3** | docs: rewrite README.md against verified evidence |
| `1a3d864` | 2026-10-02T20:34:22 | **3** | docs(history): cross-attack finding L-F2-1 and declined D-IMPORT-FUTURE |
| `8654d93` | 2026-10-02T20:42:58 | **3** | evidence(operator): fresh-clone verification and literal RUN.md execution |
| `c6af733` | 2026-10-02T20:58:33 | **3** | evidence(operator): spec-literal conformance probe for stage 3 |
| `4c20e6c` | 2026-10-03T08:49:15 | **4** (dispatched 10-02T22:48Z) | evidence(operator): fresh-clone verification of all four stages |
| `85a3ee6` | 2026-10-03T08:52:03 | **4** | docs: bring README.md and FACTORY.md up to date with stage 4 |
| `fd8bdc2` | 2026-10-03T09:21:17 | **4** | evidence(operator): product-quality gate for the stage-4 browser product |
| `1296181` | 2026-10-03T09:22:02 | **4** | docs: disclose the two accessibility findings |
| `ec466fb` | 2026-10-03T09:24:42 | **4** | docs: correct the measured autonomy figures |
| `2a49cf2` | 2026-10-03T09:26:26 | **4** | evidence(operator): regenerate the provenance index |

Open stage is derived from the four dispatch times (2026-09-30T23:05:20Z stage 1,
2026-10-01T05:34:01Z stage 2, 2026-10-01T21:57:54Z stage 3, 2026-10-02T22:48:17Z stage 4).

Four defences, each with the command that proves it.

**1. None of them was ever sent as a room message to a seat, and the seven human text messages
are still the only human input.** `python tools/room_stats.py room.json` prints the seven, and
none of their bodies contains any of these SHAs. The only commit SHAs that appear in any human
message are `11e76f9` and `849b017`, both in the third resume, and both are **band** commits
(Forge's stage-3 F2 repair, and Trace's cross-attack of it). Eleven of the fourteen operator
commits are named nowhere in any seat's narrative at all.

Of the three that are named, two were named **by the coordinator, explicitly as operator
commits**: at 2026-10-01T15:57Z Route wrote *"Two operator commits (`c1b8416`, `cc952b8`) landed
on top of mine… I'm not treating the operator evidence commits (c1b8416, cc952b8) as
acceptance."* That is a seat inside the room independently identifying operator work and
refusing to treat it as its own acceptance — the opposite of the risk this subsection is about.
The third, `2a49cf2`, appears once in Jury's final status line as the then-current HEAD, with no
comment on it.

**2. None of them touched stage code.** `git show --name-only --format= <sha>` for all
fourteen touches only `FACTORY.md`, `README.md`, `JUDGE-GUIDE.md`, `history/rejections.md`,
`tools/` and `evidence/operator/`. Stated as a machine result instead:

```text
git log --format=%H -- stage-1 stage-2 stage-3 stage-4 | sort -u | wc -l   ->  40
python -c "...cross-join those 40 against provenance.json"
   ->  Counter({'band': 39, 'band-unannounced': 1})     # operator: 0
```

**3. `c1b8416` carries an external AI review, and it was never fed back into the room.**
`evidence/operator/stage-2-dbf467c/REVIEW.md` was written by **Codex acting as the operator**,
outside the Band room, and committed 22 minutes after the stage-2 candidate `dbf467c`
(10:30:56Z → 10:53:02Z) while stage 2 was still open. Stating what it found, plainly: **it found
no defect in the stage-2 implementation.** Its harness run passed stage 1 147/147 and stage 2
35/35 with stage 3 failing as expected; its browser pass recorded seven observations with no
anomalies. Its only finding was a submission-packaging gap — `harness check` reported
`room.json` missing — which was later closed by commit `8aaf697`. It also reported one review
container that exited once with no application error, and explicitly declined to characterise
that as a crash. **None of its findings were injected into the room as a requirement**, and that
is checkable from the log itself: after the stage-2 dispatch at 2026-10-01T05:34:01Z every human
message is one of the four remaining dispatches or the three provider-limit resumes, and no
message from any source outside the room enters at any point. This is an external AI reviewing
the band, in the same direction the band reviews itself, and never steering it.

**4. The stage-3 probe scored the candidate and no stage-3 code changed afterwards.**
`c6af733` ran 38 spec-literal checks against the stage-3 tree and reported `38 pass, 0 fail`,
with all five defects it found being defects **in the probe itself**. Two commands:

```text
git show -s --format=%aI 5e6f83f   ->  2026-10-02T17:49:22Z   (the accepted stage 3)
git show -s --format=%aI c6af733   ->  2026-10-02T20:58:33Z   (the probe)
git merge-base --is-ancestor 5e6f83f c6af733   ->  exit 0     (probe postdates the candidate)
git diff c6af733 HEAD -- stage-3               ->  empty, 0 lines
```

So the probe postdated the accepted candidate by 3 hours 9 minutes and 6 commits, and from the
probe to the current head — 42 commits — **`stage-3/` has not changed by one byte.** The probe
could not have influenced the code, because the code it looked at was already frozen.

**The honest caveat, which no count can remove.** The operator wrote all fourteen of these files,
so the room log does not attest to them. Their existence is a fact about the host, not about the
room. What a judge can do is audit them independently, and that is why they are here in the
repository rather than described from memory: every path is committed, every claim above names a
command, and `git diff c6af733 HEAD -- stage-3` being empty is checkable in one line. What a
judge cannot do is derive them from `room.json`, and we are not claiming they can.

Two limits on the disclosure as a whole:

- It is scoped to commits. A file change made and never committed would not appear. The separate
  machine count in `evidence/operator/PROVENANCE.md` covers the tool calls, and reports that the
  coordinator seat made zero stage-code edits.
- `evidence/operator/provenance.json` was generated at revision `ec466fb` and covers the 80
  commits that existed then, so its totals (64 announced, 5 band-unannounced, 11 operator) are
  stale against the 100 commits above and against the 14 operator commits in 8.2. Its per-commit
  index is unaffected, because each row is keyed by SHA. Its `origin` field also disagrees with
  8.2 on three commits, and the disagreement is instructive: it labels `c1b8416` and `cc952b8`
  as `band`, because its rule keys on which seat *named* the SHA — and Route named them
  precisely in order to say they were the operator's — and it has no row for `2a49cf2` at all,
  which was committed after it was generated. Its 11 `operator` rows are 11 of the 14 in 8.2, and
  the three that differ are exactly those three. Where the two disagree, this section is the
  authority on which commits the operator wrote, because it is the statement the operator is
  making about their own work.

## 9. Measured cost and elapsed time

From `band usage rooms`, which reports catalog **estimates at list prices, not provider
billing**. The full record of how that figure was obtained, including the fact that the raw CLI
output was never captured to a file, is `evidence/operator/USAGE.md`:

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
9. **The acceptor broke the "do not read the tests or the harness" rule — four tool calls, six
   forbidden-path operations.** All four dispatches said, verbatim: *"Do not read or copy files
   under D:\project\dolphin-tank\dark-factory-wearedevs\pocketful\test or anything in the harness
   folder."* Scanning every one of the 3,184 `tool_call` arguments in the export, the **Jury** seat
   is the only seat that ever did. All four calls, quoted from `room.json`:

   ```text
   2026-10-02T22:30:18Z  Jury  "Look at harness folder and previous report"
     ls dark-factory-wearedevs/harness | head -20 ;  grep -rn "python.*run\|\.sh" dark-factory-wearedevs/harness/README.md

   2026-10-02T22:30:26Z  Jury  "Read harness CLI usage"
     sed -n 1,80p harness/cli.py | cut -c1-200

   2026-10-03T08:26:20Z  Jury  "Inspect supplied harness and earlier harness runs"
     ls pocketful/test pocketful/test/* | head -40 ;  ls harness | head -20

   2026-10-03T08:26:27Z  Jury  "Find how the supplied harness was invoked before"
     sed -n 1,60p D:/project/dolphin-tank/dark-factory-wearedevs/harness/cli.py | cut -c1-200
   ```

   What that amounts to, itemised: **two directory listings** of the `harness/` folder, **one
   `grep` over `harness/README.md`**, **one `ls` of `pocketful/test` and its contents**, and **two
   reads of `harness/cli.py`** (its first 80 lines, then its first 60). No file under
   `pocketful/test` was opened, no test body or assertion was read, and nothing was copied into
   the repository or into a seat prompt. The tool-call descriptions make the purpose explicit —
   *"Read harness CLI usage"*, *"Find how the supplied harness was invoked before"* — which is
   consistent with what the commands do: learning the runner's invocation, not its assertions.

   **No implementer seat ever did this, in any form.** Across the whole export the string
   `pocketful/test` appears in exactly **one** command, and `harness/cli.py`, `harness/README.md`
   or a listing of the `harness/` folder in exactly **four** — all four Jury. Forge, Loom and
   Trace, the three seats that wrote the code, never touched either. So the failure mode the rule
   exists to prevent, code shaped to the tests, is confined to the seat that writes no code and
   whose only power is to reject. That is a mitigation, not an absolution: the acceptor did see
   the harness's shape and the test tree's names, and a determined acceptor could in principle
   have inferred an answer from a directory listing. Disclosed because it is in the export and a
   judge will find it; we would rather they read it here first. Reproduce it by scanning the
   `tool_call` arguments of `room.json` for `pocketful/test`, `harness/cli.py` and
   `harness/README.md`.

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
