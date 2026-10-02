# Independent spec-literal conformance probe — stage 3

Run by ZEUS (the OpenCode orchestration layer, not a BAND seat) on 2026-10-02 against revision
`8654d93`. This is **not** a re-run of the reviewer's suite and not a claim about withheld tests.
It is a second opinion, written against the words of `pocketful/spec/stage-3.md` rather than
against the implementation, targeting the clauses that are easy to get subtly wrong: inclusive
bounds, verbatim echo, tie-break ordering, pagination stability, privacy, idempotency replay and
snapshot rules.

Method: `git archive HEAD stage-3` into a temp directory, `go build`, run the binary on its own
port, drive it over HTTP with the standard library only, kill by PID. The shared working tree is
never touched.

```text
== ZEUS spec-literal probe: 38 pass, 0 fail, 38 checks ==
```

Full output: `band-work/checks/zeus-spec-probe-8654d93.txt`.

## What was checked, by specification line

| stage-3.md | Requirement | Result |
|---|---|---|
| L17-18 | future seeded `created_at` → `422 validation_failed`, no state change | pass — `created_at must not be in the future` |
| L20-21, L85 | a fixture `balance` is the balance after seeded payments; opening balances are derived | pass — `as_of` before the earliest payment returns the derived opening 11300, not the seeded 10000 |
| L35 | a payment made at exactly `as_of` counts as having happened | pass — `as_of` `2026-09-20T10:00:00Z` returns 9800, i.e. both `p_1` and `p_2` at that instant counted |
| L29-30 | naive local time, bare date, empty value → 422 | pass, all three |
| L38-39 | `as_of` after the latest payment returns the current balance | pass |
| L40 | the response carries `as_of` back **exactly as given** | pass — `%2B00:00` decoded and re-emitted as `+00:00` |
| L68 | entries ordered by `created_at`, then payment `id` for ties | pass — two payments share `2026-09-20T10:00:00Z` and came back `p_1, p_2` |
| L70-71 | `opening_balance` before `from`, `closing_balance` before `to`, opening + Σdelta = closing | pass — 11300 + (−1300) = 10000 |
| L73-74 | pagination changes neither `balance_after` nor the window balances | pass — full window and both pages report (11300, 10000) and identical `balance_after` |
| L76-77 | only the caller's own payments, regardless of activity-feed visibility | pass |
| L90 | non-sender → `403 forbidden`; unknown payment → 404 | pass |
| L99 | `amount` integer 0..1000000000; `effective_at` not later than now | pass — 1000000001, −1 and a future instant all 422 |
| L99 | `amount` 0 is legal (zero reverses the entire payment) | pass — 201 |
| L101 | 201 with `payment_id`, `revision`, `amount`, `effective_at`, server `recorded_at`, `reason` | pass |
| L102 | recorded times for one payment strictly increase | pass |
| L104 | replay with the same body → 200 and the **original** revision | pass |
| L104 | same key, different body → `409 idempotency_key_reuse` | pass |
| L104 | stale `expected_revision` → `409 stale_revision` | pass |
| L117 | revision 1 present with `reason: ""` | pass |
| L118 | third party reading revisions → 404 even for a public payment; no token → 401 | pass |
| L125 | supplied `known_at` echoed exactly | pass |
| L130 | zero-amount revision appears once, as an entry with zero delta, not alongside the revision it replaces | pass — exactly one `p_2` entry, delta 0 |
| L135 | the first statement response carries an opaque `snapshot` | pass |
| L137-138 | a snapshot pages the same result; `from`/`to`/`known_at` with it → 422 | pass |
| L141 | unknown snapshot token → `404 not_found` | pass |
| L142 | `has_more` correct on a partial page | pass |

## Five defects this probe found — all five were in the probe

Recorded because a check that hides its own failures is not a check.

1. **Fixture schema guessed wrong.** Wrote `opening_balance`; the fixture contract is `balance`
   (the seeded *ending* balance, with opening balances derived per L85) plus a required
   `password`. Read from `stage-3/fixture.go` rather than guessing a second time.
2. **Wrong payment field names.** Wrote `from`/`to`; the contract is `from_user_id`/`to_user_id`.
3. **Reset drops tokens.** The probe reset state *after* logging in and then saw `401`s, and was
   about to record a defect. It is correct behaviour — `RUN.md` states that dropping state drops
   the session's tokens. Reordered to log in after the final reset.
4. **Wrong response field.** Read `payment.id`; the contract is `payment.payment_id`.
5. **Earlier, separate harness bug:** Docker does not support published ports on an
   `--internal` network, so the first literal-`RUN.md` attempt returned `000` everywhere. Probing
   from a sibling container on the same network fixed it — the product was never at fault.

## What this does and does not establish

It establishes independent corroboration that stage 3 honours 38 spec-literal boundary
behaviours at `8654d93`. It does **not** establish that stage 3 is accepted, that the withheld
suite would pass, or that the historical-hold rules are correct — those are the reviewer's job
and its re-review is still open. The shipped stage-3 suite remains 6 checks, 9% of the graded
suite.
