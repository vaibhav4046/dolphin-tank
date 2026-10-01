# Rejection history

Every jury rejection: commit, requirement id, reproduction, root cause, repair commit. Append only.

## Stage 1 (pocketful)
No rejections. Jury ACCEPTED 0024598cf4a43b6584171b1f7b8f92523c652c3a on first submission (evidence/stage-1/jury/verdict.md).
Own-check failures during jury development were all jury script bugs, fixed before the final runs; the product failed none.

Residual risks the jury accepted, usable as attack input for later stages:
- net/http rejects some malformed requests (bad %-escape in path, control byte in header) with plain-text 400, no JSON envelope.
- A zero-amount request (zero split share) is payable and records a 0-amount payment.
- Import accepts a state that lacks minor_units/seq/splits/sys/tokens (204); 10 of 63 corrupted-state variants were accepted.
- Unknown route or wrong method gives 404 (no 405); HEAD /health is 404.

## Stage 2 (pocketful)
No jury rejections. Jury ACCEPTED f33035a390c63c61dfc4ce12feb8076542c8469b on first submission (evidence/stage-2/jury/verdict.md).
Own-seat repairs before submission (not rejections): quiet-row contrast and inline link touch targets (loom 7875bf1); overlapping refreshes allowed and write buttons freed before the refresh read (loom dbf467c); explicit null authorization_ttl_seconds now 422 on reset and import (trace 17aa87e, found by route's spec review). Jury-test bugs fixed by jury before final runs (logs kept under evidence/stage-2/jury/logs/).
Residual risks the jury accepted: see evidence/stage-2/route-summary.md.
