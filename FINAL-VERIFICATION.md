# Verification at a named revision

This is a reproducibility checklist, not a withheld-test or readiness certificate.

Independent check on 6 October 2026: revision `d984122cb4c597fc27a79482ff43354a8e5fa7f4`; official package `803560d2a678ace1414465c098eb0ab5380ffade`.

- Fresh anonymous clone succeeded.
- Uncached stage-4 `go test -count=1 ./...` passed.
- Browser-logic tests passed 21/21.
- Official offline `harness check` passed gates 1, 2 and the mandate part of gate 4.
- Clean-container gate and isolated stage chain NOT independently rerun: Docker/Podman unavailable.
- Earlier isolated-run results in README/evidence are project-reported, not a new container rerun.

`proof-manifest.json` names the tested revision and room hash. Later stage-code changes need fresh validation.

## Fresh-clone procedure

Prepare the official package and Python environment following its participant guide. With Docker running, run from that package:

```sh
bash /path/to/verify-final.sh FULL_COMMIT_SHA
```

The script clones anonymously, checks out the named revision, hashes room.json, runs offline gates and the complete isolated chain. Review the generated report, claimed stages, overshoot, errors/skips and per-stage logs. Retain the report with its revision. A skipped check is not complete.

## Media evidence

The new local stage-4 walkthrough uses seeded test balances against unmodified code at the revision above. It shows payment, a hold, refused spending and refund. Requests and splits are navigated, not transacted. This is product evidence, not container-isolation proof or a new BAND run.

## Known autonomy limitation

Seven human texts: four stage dispatches and three provider-limit resumes. Not fully hands-off. Preserve the unchanged export and full history.
