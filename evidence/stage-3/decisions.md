# Stage 3 contract decisions (route)

## D-HOLD-TIME: historical views place holds at the public whole-second created_at; the overdraft check places them at created_exact

- `/me?as_of&known_at` and `/statement` count a hold from the authorization's public `created_at` (whole second), expiry at `expires_at` (created_at + ttl). Spec: "A hold starts at authorization creation", and the only creation instant a client can observe is `created_at`. A client probing `as_of = authorization.created_at` must see the hold.
- `Correct`'s historical overdraft check (T57) places holds at `created_exact` (sub-second) so back-to-back pay/authorize inside one second does not make every correction spuriously `historical_overdraft`.
- Known consequence (forge, commit 4dcefac): a view at the creation second can show `available < 0` when the funding payment lands later in that same second (266 probe views without the check, 85 with). `total` never negative, corrections never cause it. Accepted: changing it would move observable as_of numbers inside the creation second away from the public timestamps.
- Not exercised: HTTP-level views under concurrency; probes cover stamps +-1us only.

## D-HOLD-TIME REVOKED after jury REJECT of 3c7c411 (finding F2)

- Jury ruled the whole-second public created_at a violation of "available = total - held, never negative" at every read. Replacement decision: authorizations are stamped from the same clock and microsecond precision as payments (created_at, expires_at, closed_at); views and Correct's overdraft check place a hold at that one instant. created_exact is vestigial (written equal to created_at, accepted on import, never read by a view). Implemented in 11e76f9 (forge).
- Same class found by forge's probe A4: a seeded hold without created_at defaulted to the truncated reset second while seeded payments defaulted to the reset microsecond. Replacement: omitted seeded hold created_at = the reset instant at microsecond precision (trace, F1b).
- Rule for later stages: every timestamp that orders money and holds shares one clock and one precision.

## D-IMPORT-FUTURE: Import does not reject hand-crafted future-dated payments (declined, forge attack E3 on ac96360)

- Finding: importing a state whose payment `created_at` (and revision 1 times) is now+1h gives 204, and `/me` (balance 7290) disagrees with `/me?as_of=now` (7790). Reachable only with a hand-crafted state; no export of this service or of stage 1/2 contains such an instant.
- Spec: only Reset is told to reject a future seeded `created_at` (stage-3.md line 17); Import must accept "exports from the same team's stage-1 or stage-2 service" (line 156). No written requirement covers hand-crafted import states, and earlier stages accepted lax import validation as a known residual risk.
- Decision: not changed in stage 3. Rejecting would add a rule the spec does not state and needs another trace change, test and re-verification. Correct's `max(stamp, previous + 1us)` (b2d9bf3) stays as defence for the recorded-time ordering rule.
- Later stages: if Import validation is tightened, use the Reset rule (instant later than now + clock slack gives 422).
