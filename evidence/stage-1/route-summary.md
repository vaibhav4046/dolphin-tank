# Stage 1 route summary
- Accepted source commit: 0024598cf4a43b6584171b1f7b8f92523c652c3a (stage-1/ unchanged since). Spec sha256 65497dea09a8b432598c71662320cf66c3550e183cfd76e2d7f97318e0d30aa4.
- Seats: forge = domain/validators/auth/store (be0f7de, tests b5d424f, fixes 6e35abc 0024598); trace = idempotency/settlement/reset/export/import (edcfe3f, 36c4914); loom = HTTP layer/Dockerfile/RUN.md (61101ff, 9cb0bc3); jury = acceptance evidence (2c9a5d4, 6619c91).
- Shipped harness (jury ran it): out s1-0024598-a, claimed stage 1, 147/147 passed.
- Jury own checks c01-c13 + d2_smoke: all pass, ~154k requests, 0 x 5xx, race-type checks x3, go test -race clean.
- Cost seen by route: about $10.1 coordinator session total at acceptance. Other seats' cost not visible to route.
