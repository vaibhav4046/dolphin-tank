# Judge guide: where each claim is proved

One page. Every assertion in this repository can be checked against a file, a commit, or a
timestamp in the room log. This is the map. Nothing here needs a claim of trust.

Room: `5dd42746-f387-4763-afe0-f96d8f504f71`, exported `2026-10-03T20:16:49.392Z`, scope `full`,
7,216 messages. Run window 2026-09-30T23:05:19.754Z to 2026-10-03T20:00:36.066Z.

## Factory, 50%

| Judging question | Evidence |
|---|---|
| Generic: another team could point the mandates at a different problem | `mandates/` (5 files). Verified free of track vocabulary by a 146-term scan of `room.json`; 0 hits. `FACTORY.md` section 1 |
| Effective: how far through the four stages, code meeting the spec | All four stages. Stage 4 accepted at `1dd5560`; Route final report `e79ea48`. Isolated harness run: stage-4 `highest_contiguous=4`, `overshoot` null on all four. `evidence/operator/PUBLIC-CLONE-VERIFICATION.md` |
| Effective: including what the shipped checks never asked | Stage 3 rejected at `3c7c411` on two defects the shipped checks passed: F1 seed moved the clock 2h so an overdraft of 8001 against 8000 was accepted; F2 whole-second holds against microsecond payments showed `available -4000` in 25 of 25 views. `evidence/stage-3/jury/`, `FACTORY.md` section 6 |
| Reusable: `FACTORY.md` and `mandates/` enough to stand it up | `FACTORY.md` section 11, 13-step runbook; section 11a records what failed |
| Reusable: design choices and what they cost | `FACTORY.md` section 2 (topology) and section 9 (measured cost) |
| Reusable: measured time | `FACTORY.md` section 9. 10.2 h active of 68.9 h wall clock, with a gap-threshold sensitivity table |
| Reusable: what it cost, and how that number was obtained | `evidence/operator/USAGE.md` — the command, the timestamp, the room id, and an explicit statement that it is a Band CLI list-price estimate, not an invoice, with no raw console output captured |
| Reusable: how the factory catches and recovers from bad work | Rejection at `3c7c411`; repairs `11e76f9` (Forge), `ac96360` (Trace), cross-attack `849b017`, final `5e6f83f`. Jury rebuilt from a clean clone before accepting. `history/rejections.md` |

## App, 25%

| Judging question | Evidence |
|---|---|
| Coherent, presentation-ready UI | `stage-4/` serves a browser app from the same container. Screenshots at 375, 768 and 1280 px in `evidence/stage-4/jury/final/browser/shots/` |
| Responsive | Tested in Chromium at 375, 768 and 1280 px. Chromium only; no other browser was tried, and that limit is stated in `FACTORY.md` section 10 |
| Clear in the states the spec identifies | Money on hold, refused amount, unconfirmed refund. `evidence/stage-4/jury/final/VERDICT.md` |
| Code another developer could maintain | Go standard library only, no third-party modules. `stage-4/go.mod`, `stage-4/Dockerfile` builds multi-stage to `FROM scratch` |

## Agent Teamwork, 25%

| Judging question | Evidence |
|---|---|
| More than one seat did it | Per-seat tool calls, machine counted: Forge 89, Trace 88, Loom 46 stage-code edits, Route 0. `tools/seat_edits.py`, `evidence/operator/PROVENANCE.md` |
| **One git author, so `git log` alone proves nothing — and here is why that is not the weakness it looks like** | All commits share one identity (`vaibhav4046`), because a single operator held the credentials. Of the 40 commits touching `stage-1..4`, 17 carry an explicit `(forge)`/`(trace)`/`(loom)` tag, 4 are the mechanical `copy accepted stage-N-1 as baseline`, and 19 attribute in prose only. **Zero of the 40 were written by the operator.** We attribute by *tool-call target path in the unedited room export* instead of by git config — which is stronger, because it comes from the export rather than from a self-reported setting. Run `python tools/seat_edits.py room.json` |
| Work distributed, not one seat carrying it | `python tools/room_stats.py room.json`. Agent tool_call share: Jury 26.0%, Trace 25.0%, Forge 19.7%, Route 15.2%, Loom 14.1% of 3,184 calls |
| Review changed something | Jury rejected a stage that passed every shipped check; the repair reversed a risk the authors had logged as acceptable. `FACTORY.md` section 6 |
| The repair was itself attacked, and nearly shipped still broken | The cross-attack `849b017` aimed at the repair rather than the build and found the rejected export re-opened defect F2 on import. Second repair `5e6f83f`, then independent re-verify. The rule we took from it: **a repair is only as good as the states it is reachable from.** `REPAIR-SCOPE.md` |
| Handoffs carried the whole task | Every handoff carries the specification hash, the exact commit and the acceptance criteria. Sample handoff at 2026-09-30T23:14:27.744Z. `FACTORY.md` section 3 |
| The code traces to the room | All 82 commits with author time inside the run window are named by SHA somewhere in the export, zero unreferenced — but **14 of those 82 are operator commits, not band output**, including one external-AI review. Read the weak "referenced" rule and the full disclosure in `FACTORY.md` section 8 and section 8.2 |
| Autonomy: the dispatch is the only human input | **7 human text messages, and this is where we fall short.** 4 dispatches plus 3 resumes after provider usage limits. No seat ever asked a question and no requirement changed. Full account with timestamps and the limit event behind each resume: `FACTORY.md` section 8 |

## Reproduce it yourself

```sh
# 1. eligibility, gates 1, 2 and the mandate part of gate 4
python -m harness check <this repo> --track pocketful

# 2. the grading configuration: stages are built and served with no outbound network
python -m harness run --track pocketful --repo <this repo> --all --mode isolated --out <dir>

# 3. room statistics: message counts, human messages, per-seat tool_call share
python tools/room_stats.py room.json

# 4. who edited stage code, counted from tool calls
python tools/seat_edits.py room.json
```

Commands 3 and 4 need only Python 3.12 and the standard library.

## Known limits, stated by us

- **Git authorship cannot settle who wrote what.** One shared identity, 17 of 40 stage commits
  explicitly tagged, 19 attributed in prose only. Some teams give each seat its own Git identity;
  we could not, because one operator held the credentials. Our attribution is the room export's
  tool-call target paths, which is why `tools/seat_edits.py` exists. It reports a **floor**: the
  console export truncates tool-call arguments at 2,000 characters, so 220 of 501 edit-family
  calls have an unreadable target and are counted in the "all" column only. The Route 0 result is
  a true zero, not a truncated one.
- We are the slowest and most expensive strong entry in this hackathon (68.9 h, $196.92 against
  rivals at $0-$75). The honest answer is in `README.md`, section "Why 68.9 hours": 32 provider
  usage-limit events in the export, 10.2 h actually active, and the spend bought a reviewer that
  said no.
- Autonomy: 3 of the 7 human messages are resumes, not dispatches. See above.
- 14 commits with author time inside the run window are operator commits, not band output. None
  touches `stage-1..4/`, none was sent to a seat as a message, and one contains an external Codex
  review. `FACTORY.md` section 8.2.
- The Jury seat read `harness/cli.py` and listed `pocketful/test`, against a rule in the dispatch.
  No test file or assertion was read, and no implementer seat did it. `FACTORY.md` section 10,
  limitation 9.
- Two low-severity accessibility findings are unpatched in `stage-4/`: no `h1` on the wallet
  route, and one link 4 px short of the touch target at 390 px. They were left alone on purpose,
  because the value of this submission is that no human edited the agents' code.
- Browser testing was Chromium only.
- `go test -race` was not run at stage 4.
- We make no claim about the withheld tests. The harness prints its own caveat that passing its
  run is directional feedback, not a guarantee.
- Cost is a list-price estimate, not a provider bill. Active time is inferred from the room log.