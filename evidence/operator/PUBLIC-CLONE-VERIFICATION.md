# Public anonymous clone verification

The strongest release evidence available: the **public repository, cloned with no credentials**,
built and scored with the official harness in grading configuration.

- Repository: `https://github.com/vaibhav4046/dolphin-tank`
- Revision: `4c2273c5331665891ace9e65683a5abb129a153f` — actually `4c2273c5331665891ace0e65683a5abb129a153f`
- Verified: 2026-10-04 18:18–18:27 UTC
- Operator: ZEUS (the OpenCode orchestration layer, not a BAND seat)

A local clone proves the working tree still works. This proves **the artifact a judge receives**
works. The clone was made with `git clone --depth 1 https://github.com/vaibhav4046/dolphin-tank.git`
and `GIT_TERMINAL_PROMPT=0`, so it exercised the anonymous path a judge without Band Desktop
membership or a GitHub account would take.

## Clone provenance

```text
HEAD : 4c2273c5331665891ace0e65683a5abb129a153f
files: 1870
clean: [0 dirty entries]
origin https://github.com/vaibhav4046/dolphin-tank.git   (no credentials in the URL)
```

Root contains `.gitattributes`, `.gitignore`, `FACTORY.md`, `LICENSE`, `README.md`, `room.json`,
and the four stage folders.

## Layout gates

| Folder | Dockerfile | RUN.md | tracked files |
|---|---|---|---:|
| `stage-1/` | yes | yes | 34 |
| `stage-2/` | yes | yes | 87 |
| `stage-3/` | yes | yes | 116 |
| `stage-4/` | yes | yes | 130 |

No nested `.git` directory inside any stage folder — the failure mode the participant guide calls
out, where a copied folder builds for you and arrives empty for a judge.

## Official offline check

```text
python -m harness check <anonymous clone> --track pocketful
```

```text
ok - gates 1, 2 and the mandate part of gate 4 pass. Not checked here: gate 3
(stage-1/ builds and serves /health). Run: python -m harness run --track pocketful
--repo <clone> --stage 1 --mode isolated
CHECK_EXIT=0
```

Gates 1 and 2 validate against the committed `room.json`: five distinct seats each with a
mandate naming harness and model, mandates free of track vocabulary, and reciprocal `@handle`
exchange in both directions.

## Full grading run

```text
python -m harness run --track pocketful --repo <anonymous clone> --all --mode isolated
RUN_EXIT=0

  stage-1/: claims stage 1 on the shipped checks
  stage-2/: claims stage 2 on the shipped checks
  stage-3/: claims stage 3 on the shipped checks
  stage-4/: claims stage 4 on the shipped checks
```

`--mode isolated` is the grading configuration: an internal Docker network with outbound traffic
blocked, so this also proves the result needs no network at run time.

```json
{
  "track": "pocketful",
  "folders": {
    "1": { "claimed": true, "share": 1.0, "overshoot": null, "highest_contiguous": 1 },
    "2": { "claimed": true, "share": 1.0, "overshoot": null, "highest_contiguous": 2 },
    "3": { "claimed": true, "share": 1.0, "overshoot": null, "highest_contiguous": 3 },
    "4": { "claimed": true, "share": 1.0, "overshoot": null, "highest_contiguous": 4 }
  },
  "mode": "isolated"
}
```

Two properties matter and both hold. **The chain scores**: `stage-4/` passes all four suites, so
this is a completed four-stage result. And **nothing overshoots**: every next-stage check
correctly fails and `overshoot` is `null` on all four, meaning no folder smuggles a later stage's
answer backwards.

Raw output: `band-work/checks/anon-clone-verify-4c2273c/`.

## What this does not prove

The harness prints its own caveat, and it is the honest one: this run includes only a portion of
the tests applied before judging, and passing it is directional feedback rather than a guarantee
against the withheld suite. The shipped stage-3 and stage-4 suites are 6 and 5 checks — 9% and 16%
of their graded suites. The real assurance is the acceptor's own checks and mutation testing
recorded under `evidence/stage-N/`, not this run.
---

## Addendum: re-verified at the published head

The revision above was `4c2273c`. The repository has since advanced with two
documentation-only commits (`8392d23`, `2b470df`). Rather than rewrite this file,
the published head was verified again from scratch, anonymously, on 2026-10-05.

```text
git clone --depth 1 https://github.com/vaibhav4046/dolphin-tank.git
HEAD  : 2b470df5d3cecce44967e6309ab0d78edb4b8029
files : 1871
clean : yes
```

**Stage code is byte-identical across all four stages** since the revision verified
above, so the acceptance chain did not move. The two later commits touched
`README.md` and this evidence file only.

Room integrity re-read from the published `room.json`:

```text
roomId    : 5dd42746-f387-4763-afe0-f96d8f504f71
scope     : full
messages  : 7216
seats     : 5 agent seats (Route, Forge, Loom, Trace, Jury) plus the operator
human msgs: 7  (4 stage dispatches, 3 provider-quota resumes)
reciprocal agent-to-agent pairs: 7
```

Official harness, grading configuration, against the published head:

```text
python -m harness check <clone> --track pocketful                        -> CHECK_EXIT=0
python -m harness run --track pocketful --repo <clone> --all --mode isolated
                                                                          -> RUN_EXIT=0

stage-1: claimed=True share=1.0 highest_contiguous=1 overshoot=None
stage-2: claimed=True share=1.0 highest_contiguous=2 overshoot=None
stage-3: claimed=True share=1.0 highest_contiguous=3 overshoot=None
stage-4: claimed=True share=1.0 highest_contiguous=4 overshoot=None
```

Every stage folder ships a `Dockerfile` and a `RUN.md`, and no nested `.git`
exists inside any of them. Raw output: `band-work/checks/final-anon-verify/`.
