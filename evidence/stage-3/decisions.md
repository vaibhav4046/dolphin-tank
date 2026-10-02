# Stage 3 contract decisions (route)

## D-HOLD-TIME: historical views place holds at the public whole-second created_at; the overdraft check places them at created_exact

- `/me?as_of&known_at` and `/statement` count a hold from the authorization's public `created_at` (whole second), expiry at `expires_at` (created_at + ttl). Spec: "A hold starts at authorization creation", and the only creation instant a client can observe is `created_at`. A client probing `as_of = authorization.created_at` must see the hold.
- `Correct`'s historical overdraft check (T57) places holds at `created_exact` (sub-second) so back-to-back pay/authorize inside one second does not make every correction spuriously `historical_overdraft`.
- Known consequence (forge, commit 4dcefac): a view at the creation second can show `available < 0` when the funding payment lands later in that same second (266 probe views without the check, 85 with). `total` never negative, corrections never cause it. Accepted: changing it would move observable as_of numbers inside the creation second away from the public timestamps.
- Not exercised: HTTP-level views under concurrency; probes cover stamps +-1us only.
