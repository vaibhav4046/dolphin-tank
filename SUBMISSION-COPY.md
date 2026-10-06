# SUBMISSION COPY — Dolphin Tank

Paste-ready. Every figure below is verified and reproducible from the public repository at
revision `948875d`. Nothing here claims a hidden test, a ranking, or a score.

**Status: NOT YET FILED.** The competition account is the owner's to authenticate. Once logged
in at `https://lablab.ai/ai-hackathons/wearedevelopers-hackathon`, this page is the whole job.

---

## Title (54 characters)

```
Five agents shipped an overdraft. One seat refused it.
```

Checked against 60 competitor entries: no rival title contains "overdraft", "shipped" or
"refused", and none makes the reviewer the subject of the sentence.

## Tagline — 2 sentences

```
Five BAND seats built a four-stage Go payments service, and the one seat allowed to say no
rejected stage 3 with a reproduced overdraft of 8001 against 8000 available. The 7,216-message
room export, the machine-counted seat provenance and the full reject, repair, cross-attack,
re-accept cycle are in the public repository.
```

## Tags — 5

```
Pocketful
Band Agentic Mesh
Band Control Plane
Anthropic Claude
Developer Tools
```

## Short description — 567 characters

```
The shipped checks said yes. Our reviewer said no. Jury reproduced an accepted overdraft of 8001
against 8000 available and available = -4000 in 25 of 25 views, rejected stage 3, and required
fresh evidence before accepting the repair. Four stages in Go, 147/+35/+6/+5 on the official
harness in isolated mode from an anonymous clone, overshoot null on all four. Provenance is
counted, not asserted: python tools/seat_edits.py room.json reports Forge 89, Trace 88, Loom 46
and Route 0 - the coordinator seat wrote no stage code. 7,216 unedited room messages, 7 human.
```

## Long description — 1,693 characters

```
Most dark factories here prove they built something. We are submitting the receipt for the moment
one of ours refused to.

Five BAND seats built Pocketful, a four-stage Go payments service: 147, +35, +6 and +5 on the
official harness in isolated mode from an anonymous public clone, every folder claiming its own
stage and overshoot null on all four, so no folder smuggles a later answer backwards.

Stage 3 passed every shipped check. Jury rejected it anyway on two reproduced defects: an
overdraft of 8001 against 8000 available, and a balance reading available = -4000 in 25 of 25
historical views. Forge and Trace repaired them. Then we aimed an attack at the repair instead of
the build, and it found the rejected build's own export re-opened the bug on import. That produced
a rule we now enforce: a repair is only as good as the states it is reachable from. Jury rebuilt
from a clean clone and re-verified before it accepted.

The provenance is counted, not claimed. python tools/seat_edits.py room.json attributes stage-code
edits from the unedited export by tool-call target: Forge 89, Trace 88, Loom 46, Route 0. The
planning seat wrote no product code. room_stats.py recounts 7,216 messages, of which 7 are human:
four stage dispatches and three resumes after provider quota limits. We say that because it is the
weakest part of the story and it is true.

Cost $196.92 at list prices, 10.2h active of 68.9h wall clock - about 86% of that clock was
provider quota rather than work. Start at JUDGE-GUIDE.md: one page, every claim mapped to a file,
a commit or a timestamp, including the rows that cost us points.

https://github.com/vaibhav4046/dolphin-tank
https://dolphin-tank.vercel.app
```

## Links

| Asset | URL |
|---|---|
| Repository | `https://github.com/vaibhav4046/dolphin-tank` |
| Showcase site | `https://dolphin-tank.vercel.app` |
| Demo film (1:56) | `https://dolphin-tank.vercel.app/assets/media/dolphin-tank-demo.mp4` |
| Deck (PDF, 4.7 MB) | `https://dolphin-tank.vercel.app/assets/media/dolphin-tank-deck.pdf` |
| Judge map | `https://github.com/vaibhav4046/dolphin-tank/blob/main/JUDGE-GUIDE.md` |
| The rejection | `https://github.com/vaibhav4046/dolphin-tank/blob/main/history/rejections.md` |
| The repair rule | `https://github.com/vaibhav4046/dolphin-tank/blob/main/REPAIR-SCOPE.md` |

---

## Three things to say if a judge asks

**"Your git log has one author."** Yes, and we say so in `JUDGE-GUIDE.md` before you ask. One
operator held the credentials. We attribute by tool-call target path in the unedited room export
instead, which is stronger evidence because it comes from the export and not from a self-reported
setting. Route, the coordinator, is a true zero.

**"68.9 hours for four stages?"** Active model time was 10.2 hours. `room.json` contains 32
provider usage-limit events; the longest single stall was 9.5 hours. About 86% of the clock was
the provider sleeping.

**"How do I know you didn't paste a summary of the run?"** `room.json` is 7,216 messages,
8.9 MB, and its SHA-256 is published in `proof-manifest.json`. `python tools/room_stats.py
room.json` recounts it.

## What we will not claim

Withheld or hidden tests. Any ranking, score or leaderboard position. Any hidden-test or
placement outcome. Provider billing — `$196.92` is a Band CLI list-price estimate, not an invoice
(`evidence/operator/USAGE.md`). Browser coverage beyond Chromium. `go test -race` at stage 4.