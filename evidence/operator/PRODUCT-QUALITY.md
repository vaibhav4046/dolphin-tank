# Product-quality gate — stage-4 browser product

Run by ZEUS (the OpenCode orchestration layer, not a BAND seat) on 2026-10-03 against revision
`85a3ee6`. Independent of the BAND run: the image is built from the committed repository with
`git archive`, and every check is written here rather than taken from the band's own scripts.

```text
== ZEUS product-quality gate: 127 pass, 7 fail, 134 checks ==
```

Screenshots and raw log: `band-work/checks/zeus-quality-85a3ee6/` and `…-85a3ee6.txt`.

Method: build `stage-4/` → serve → seed a realistic four-payment state through `/_test/reset` →
sign in through the real login form → drive every UI route at all five viewports the protocol
requires (1440×900, 1280×800, 1024×768, 768×1024, 390×844) → tab through the page → repeat under
`prefers-reduced-motion: reduce`. No page-side library is injected; only the Playwright API.

## What passed

| Area | Result |
|---|---|
| Horizontal overflow, all 6 routes × 5 viewports (30 combinations) | **0 overflows.** `scrollWidth == clientWidth` at every size, including 390 px |
| Elements clipped outside the viewport | **0** at every size |
| Touch targets ≥ 44 px on 390×844 | pass on 5 of 6 routes (see finding 2) |
| Accessible name on every `a`, `button`, `input`, `select`, `textarea` | **pass** on all 30 route×viewport combinations |
| Keyboard reachability | Tab order is `Skip to content → Pocketful → Wallet → Requests → Split → Authorizations → Log out → Refresh → …` — a skip link first, then landmarks, then controls |
| Visible focus indicator on every tab stop | **pass** — every stop had an outline or a box-shadow |
| Infinite animation under `prefers-reduced-motion: reduce` | **none** |
| Signed-out landing page renders content, not a blank page | pass (180 characters of real copy) |
| Console errors across the whole sweep | **none** |

Heading structure is correct on five of six routes: `/requests` (h1 Requests), `/split`
(h1 Split), `/authorizations` (h1 Authorizations), `/login` (h1 Log in), `/signup`
(h1 Create your account), each with h2 sub-sections beneath.

## Two genuine findings

Both are in `stage-4/`, which is band-owned code, so they are **reported, not fixed here** — see
"provenance" below.

### 1. The wallet route has no `h1` — at all five viewports

`/` renders four `h2` sections (`Pay someone`, `Request money`, `Authorise a payment`,
`Activity`) and **no top-level heading at all**. Every other route has a proper `h1`.

```text
FAIL page has an h1 1440x900 / :: headings=['H2:Pay someone','H2:Request money','H2:Authorise a payment','H2:Activity']
FAIL page has an h1 1280x800 /   (same)
FAIL page has an h1 1024x768 /   (same)
FAIL page has an h1 768x1024 /   (same)
FAIL page has an h1 390x844 /    (same)
```

Severity: low-to-moderate. It is the product's primary route and the one a judge lands on first.
Screen-reader users get no document-level heading, and the heading outline starts at level 2.
This is the kind of thing the protocol's accessibility list means by "semantic headings".

### 2. One sub-44 px touch target on `/signup` at 390 px

```text
FAIL touch targets >= 44px 390x844 /signup :: A 40x44 "Log in"
```

A link measuring **40 × 44 px** — correct height, 4 px short on width. Severity: low. It is the
"already have an account? Log in" link on the sign-up form.

## One failure that was this gate's own fault

`FAIL sign in through the UI :: landed on http://127.0.0.1:18455/login`

The sign-in **did** work. The tab sweep immediately afterwards found `BUTTON:Log out` and an
input pre-filled with `bob`, and every later route rendered signed-in wallet content, so the
session existed. The assertion tested the URL, and the app re-renders the wallet without changing
it. Recorded rather than quietly dropped: the fix is to assert on the presence of a sign-out
control, not on the path.

## Why these were reported and not fixed

`stage-4/` is BAND seat output. The participant guide is explicit that *"hand-built code does not
count"* and that anything an operator commits under `stage-N/` is code the band did not write.
So the two findings are recorded here and in `FACTORY.md` rather than patched.

They were also **not** injected into the room. The guide requires that from a stage dispatch until
the coordinator's final report the dispatched task is the only human input; a message saying
"fix the missing h1" would be steering, and it would add a seventh human message to a room log
that judges read for exactly that. Two minor accessibility findings are not worth spending the
autonomy evidence on — and disclosing them is worth more than quietly fixing them.

## Scope limit

This gate tests the **browser product's presentation quality**: layout, responsiveness,
keyboard and screen-reader basics, motion and console health. It is not a correctness check —
that is the harness and the acceptor's job — and it says nothing about withheld tests.
