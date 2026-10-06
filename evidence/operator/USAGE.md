# Model spend — how the dollar figure was obtained

## What was run, when, and against what

| | |
|---|---|
| Command | `band usage rooms` |
| Run by | the operator (ZEUS, the OpenCode orchestration layer), not a BAND seat |
| Measured at | 2026-10-03 22:48 UTC — after the coordinator's final room report, so the figures are final rather than interim |
| Room id | `5dd42746-f387-4763-afe0-f96d8f504f71` (the submitted run) |
| Source of the numbers | the Band CLI catalog estimate, transcribed by the operator |

Reproduce it with:

```sh
band usage rooms 5dd42746-f387-4763-afe0-f96d8f504f71
```

This requires a signed-in Band account that owns or can read the room. A judge without one
cannot re-run it and should treat the figures below as the operator's transcription, which is
what they are.

## The figure published in this repository

```text
room 5dd42746 (submitted run)   55 sessions   487,800,071 tokens   $196.92
   @jury   $59.37   (30.1%)
   @trace  $50.31   (25.5%)
   @forge  $35.95   (18.3%)
   @route  $27.35   (13.9%)
   @loom   $23.94   (12.2%)
```

The five per-seat amounts add up to the total exactly (196.92), and each share is that seat's
amount divided by the total, so the table is internally consistent.

## What this is, stated plainly

**It is a list-price estimate produced by the Band CLI. It is not an invoice.** The CLI prices
the tokens it observed against the published catalog rates. It is not what the model provider
billed, it does not include any subscription, plan, seat or enterprise discount, and it says
nothing about what the seats cost in provider credits that were not consumed as tokens.

**No billing statement was obtained.** No invoice, no provider console screenshot and no credit
statement is in this repository, because none was ever available to the operator. Any judge who
needs the real number has to ask the provider; the number in this repository is the closest thing
the operator can actually produce.

`FACTORY.md` section 10 limitation 6 and `FACTORY.md` section 9 both say the same thing, and
`README.md` line 20 labels the figure "at list prices (not a bill)". Those three are the only
places the number is published.

## Raw console output was not captured to a file

Raw console output was not captured to a file; the figures above are the operator's
transcription of the Band CLI `usage rooms` output for this room, measured at the timestamp
shown. They are an estimate at list prices, not a bill.

This is stated here rather than papered over with a reconstructed transcript, because a
reconstructed console transcript would be indistinguishable from a real one to a reader, and
would not be evidence of anything. There is no `usage.txt` in this repository, and the
`band` CLI is not available to the reader, precisely because obtaining raw output requires the
operator's Band account.

## Two earlier figures, for honesty about the movement

The estimate is not a constant, because seats kept closing sessions after each measurement.

| Measured at | Total | Recorded in |
|---|---|---|
| 2026-10-03 22:25:38Z | $189.42 | commit `e07ad9c` (subject line) |
| 2026-10-03 22:48 UTC | $196.92 | the figure published above, and in `FACTORY.md` / `README.md` |

The published figure is the later and larger one. The earlier figure is named here so that a
judge who reads the `e07ad9c` commit subject does not think the repository contradicts itself.

## Other rooms

`FACTORY.md` section 9 also quotes $94.16 for an earlier Codex attempt and $15.26 for a toy
rehearsal, from the same command over the other two room ids. Those two numbers are **not**
restated here and are **not** independently re-measured by this document; they are carried
forward from the same `band usage rooms` output. The submitted room is the only one the
submission depends on, and it is the only one with a committed evidence trail around it.
