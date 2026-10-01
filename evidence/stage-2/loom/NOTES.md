# loom stage-2 evidence (commit 17aa87e2f690ccf0ec582e01f7a44cd5453bcb30)

- logs/go-node-checks.log: go vet / go build / go test -count=1 ./... / node --test jstest
- logs/final2-run.out: clean-clone image build, size, startup, offline serving, browser smoke summary, real stage-1 -> stage-2 upgrade
- logs/smoke.log: 215 browser checks (Playwright/chromium in df-harness-runner, runtime only)
- logs/upgrade.log: real stage-1 server export imported by stage-2 while the browser stays signed in
- shots/: full-page screenshots at 375 and 1280 of every route, populated and empty, plus state-* (pay refused/success/uncertain, signup refused, request stale, authorization refused/partial/empty/populated, split done)
- scripts/: ui_smoke.py, upgrade_real.py, final2.sh (+ run2.sh, startup*.sh, offline.sh)

Startup: `docker run -d` -> first /health 200 is 0.9-1.8 s here and the same for the accepted stage-1 image (1.3-1.8 s): it is docker/WSL container creation. Container process start -> first /health is 126-179 ms.
