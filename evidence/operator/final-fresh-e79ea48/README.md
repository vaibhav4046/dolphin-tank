# Final fresh-clone verification

Run 2026-10-03 on a brand-new `git clone` of the result repository at `e79ea48`, with the
official harness unmodified, grading configuration:

    python -m harness run --track pocketful --repo <fresh clone> --stage 4 --mode isolated --out <new dir>

Result (`console.txt`): stage 1 pass, stage 2 pass, stage 3 pass, stage 4 pass,
`highest contiguous stage: 4`, `claimed stage: 4 on the shipped checks`. Per-suite logs and
counts sit beside this file. Source under `stage-1/` to `stage-4/` is identical between `e79ea48`
and every later commit (later commits are documentation and evidence only).
