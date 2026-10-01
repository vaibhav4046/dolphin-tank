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
