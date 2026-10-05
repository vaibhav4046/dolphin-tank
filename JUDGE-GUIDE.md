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
| Work distributed, not one seat carrying it | `python tools/room_stats.py room.json`. Agent tool_call share: Jury 26.0%, Trace 25.0%, Forge 19.7%, Route 15.2%, Loom 14.1% of 3,184 calls |
| Review changed something | Jury rejected a stage that passed every shipped check; the repair reversed a risk the authors had logged as acceptable. `FACTORY.md` section 6 |
| Handoffs carried the whole task | Every handoff carries the specification hash, the exact commit and the acceptance criteria. Sample handoff at 2026-09-30T23:14:27.744Z. `FACTORY.md` section 3 |
| The code traces to the room | All 82 commits with author time inside the run window are named by SHA in a room message. Zero unreferenced. `FACTORY.md` section 8, "Operator activity during the run" |
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

- Autonomy: 3 of the 7 human messages are resumes, not dispatches. See above.
- Two low-severity accessibility findings are unpatched in `stage-4/`: no `h1` on the wallet
  route, and one link 4 px short of the touch target at 390 px. They were left alone on purpose,
  because the value of this submission is that no human edited the agents' code.
- Browser testing was Chromium only.
- `go test -race` was not run at stage 4.
- We make no claim about the withheld tests. The harness prints its own caveat that passing its
  run is directional feedback, not a guarantee.
- Cost is a list-price estimate, not a provider bill. Active time is inferred from the room log.