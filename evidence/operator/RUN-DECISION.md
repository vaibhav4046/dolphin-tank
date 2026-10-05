# Run 1 vs Run 2: the swap decision, written down before the pressure

Recorded by ZEUS, the operator orchestration layer, on 2026-10-05. This file exists
so the final call is made against criteria written in advance rather than against
the clock in the last hour.

## The situation

Run 1 finished. Four stages, each accepted by an independent Jury seat, verified
against the official harness in grading configuration from a fresh clone of the
public repository. It is published, and it is the only run that currently satisfies
every submission requirement.

Run 2 is a second attempt, started to remove one weakness in Run 1. Run 1's room
contains 7 human messages: 4 stage dispatches and 3 resumes after the model
provider cut off agent turns mid-flight. The judging criteria say the per-stage
dispatch should be the only human input, with no reruns, so those 3 resumes are a
real mark against the 25% Agent Teamwork criterion.

Run 2 is dispatched once and never touched again, which would make its autonomy
clean. The trade is explicit: **clean autonomy, or a finished result.**

## Default: Run 1 is the submission

Run 1 is the default. It is not a fallback in the sense of being second-best; it is
the only run that is complete, published and verified.

The rubric decides this. Factory is 50% of the score, and it explicitly rewards
"how far through the four stages it got with code that meets the spec". Run 1
reached four of four, independently accepted. Autonomy is a slice of the 25%
Teamwork criterion. Trading a verified four-stage result for a cleaner autonomy
story is a bad deal unless the replacement actually matches it.

## Run 2 replaces Run 1 only if every one of these is true

1. Jury has accepted **stage 4** of Run 2. Not written, not self-tested, not
   "nearly done". Accepted, by a reviewer seat, on evidence it reproduced itself.
2. `python -m harness run --track pocketful --repo <run2> --all --mode isolated`
   exits 0, with stage 4 claiming stage 4 and `overshoot` null on all four folders.
3. The full room export for Run 2 is downloaded from the BAND console, unmodified,
   and the human-message count in it is 1 per stage with no resume messages.
4. `harness check` passes on the Run 2 repository.
5. README, FACTORY.md and the submission fields are rewritten to Run 2's real
   figures, with Run 2's real cost and time, measured the same way.
6. The public repository passes an anonymous clone verification at the final head.

If any one of those fails, Run 1 is submitted. A partially complete Run 2 is worth
nothing, because the submission requires every completed stage to build and serve.

## Timelines

Hackathon closes 2026-10-06 06:59 UTC.

- **Swap decision point: 2026-10-06 00:00 UTC.** If Run 2 has not reached a Jury
  stage-4 acceptance by then, it cannot be documented, exported and verified in the
  remaining hours. Run 1 is submitted.
- **Absolute freeze: 2026-10-06 02:00 UTC.** No further changes to the submission
  repository after this point, whichever run wins. Final verification and upload only.

## What must never happen

- Run 2 must not modify, delete or overwrite anything under `band-work/result/`,
  `band-work/evidence/`, or the public repository. It builds in `band-work/result-2/`
  and `band-work/checks-2/`, and it stays there.
- No commit may touch `band-work/result/stage-1..4`. The value of Run 1 is that no
  human ever edited the agents' code, and that firewall is not negotiable.
- Run 1's room export is not regenerated. It is a verbatim console export and it is
  already verified.

## Run 1 is already frozen

So that this decision cannot be lost, rushed, or quietly reversed:

- Git tag `run1-verified` on commit `fbe4ece`.
- Full history bundled to `band-work/FROZEN-RUN-1/run1.bundle`.
- `room.json`, `README.md`, `FACTORY.md` and `LICENSE` copied to
  `band-work/FROZEN-RUN-1/`, outside both runs' working trees.
- The public repository already serves Run 1 at its verified head.

Restoring Run 1 from the bundle is `git clone run1.bundle run1`.