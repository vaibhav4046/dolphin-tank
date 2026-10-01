# Operator review of Stage 2 candidate

Date: 1 October 2026. Reviewer: Codex acting as the operator, not the BAND Jury seat. Source revision: `dbf467cf409c0fb8336ca5d990b44b872b62260a`. No stage implementation was edited. This evidence does not replace Jury acceptance or prove autonomous-run eligibility.

## Isolated harness

Command from the kickoff checkout in WSL Ubuntu 24.04:

```sh
. /root/dfv/bin/activate
python -m harness run --track pocketful --repo /mnt/d/project/dolphin-tank/band-work/result --stage 2 --mode isolated --out /mnt/d/project/dolphin-tank/band-work/checks/s2-codex-audit-20261001-1050
```

Result: process exit 0, Stage 1 passed 147/147; Stage 2 passed 35/35; Stage 3 failed the overshoot check as expected; highest contiguous stage 2; claimed stage 2. See the original report and count files copied alongside this note. The suite is partial; this is not a hidden-test claim. The report records working-tree provenance, not a fresh-clone run.

## Browser exercise

Used the built `pocketful-s2:latest` image in a separate local container, `pocketful-codex-review-1052`, on port 18082. Seeded only this review instance with disposable Ada/Bob accounts, EUR and two minor units. Ada began at 1250.00 EUR and Bob at 250.00 EUR. No real financial accounts or transfers were involved.

Observed through the actual browser controls:

1. Login as Ada reaches the wallet and displays available 1250.00 EUR.
2. Send 15.00 EUR to Bob: confirmation and activity entry appear; total and available become 1235.00 EUR.
3. Place a 100.00 EUR hold for Bob: total remains 1235.00, held becomes 100.00, available becomes 1135.00.
4. Attempt a 9999.00 EUR payment: an explicit insufficient-available-funds refusal appears. The displayed balance remains unchanged.
5. At a 375 x 812 viewport the wallet/form and authorization page remain legible. Wallet document scroll width was 360 pixels, within the 375-pixel viewport; no horizontal overflow observed.
6. Void the hold from Authorizations: release confirmation appears, status becomes Voided, held disappears and available returns to 1235.00.
7. Captured browser error/warning log was empty for this flow. Restored the temporary viewport override.

The separate Docker review container exited once without an application error in its log; it was restarted with an attached WSL command before the successful flow. Cause was not established. Do not characterize this as a proven application crash or a proven WSL shutdown issue.

Not covered by this manual pass: complete keyboard/a11y audit, all routes at mobile width, browser lost-response injection, recipient capture, all stale-state races, persistence across application restarts or the full Stage 2 specification. The harness and Jury work have separate scopes.

## Submission structure

After adding operator-authored README.md and FACTORY.md, `python -m harness check ... --track pocketful` reports one problem: missing `room.json`. The guide requires the full-session download from BAND, not a reconstructed CLI export. The current room also contains a Stage 1 human recovery nudge; the autonomy issue is documented in FACTORY.md.
