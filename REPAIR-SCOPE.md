# REPAIR-SCOPE — a repair is only as good as the states it is reachable from

**This is the one engineering rule this factory produced that we could not find anywhere else in
the field. It came out of a real failure, not a slogan.**

## The rule

When a reviewer rejects a build and the builder repairs it, the obvious next step is to
re-run the original failing check. That check exercises the states the reviewer found.

**It does not exercise the states the reviewer never looked at.** A repair is only as good as
the set of states from which it is reachable. So after a repair, attack the *repair*: enumerate
every state the system can be reconstructed into, and look for one where the original defect
comes back.

## Where it came from

Stage 3. Jury rejected commit `3c7c411` with two reproduced defects:

- **F1** — an overdraft of **8001** was accepted against **8000** available.
- **F2** — `available` read **-4000** in **25 of 25** historical views.

The seats repaired both: `11e76f9` put holds and money on one clock, `ac96360` stopped seeded
and imported values from moving that clock. Both repairs looked correct against the failing
checks.

Then we turned the attack around. `849b017` aimed Trace's black-box suite at the *fix*, not at
the build, and asked a different question: **can the rejected build's own export be re-imported
in a state that brings F2 back?**

It could. The rejected export names the whole second in `created_at` and the placing
microsecond in `created_exact`. The repaired import path ignored `created_exact`, so a hold
landed on the floor of its second while the payment funding it sat later in that same second —
`available = -2000` in a historical view. The defect was alive. The repair had only moved it.

The second repair, `5e6f83f`, makes a validated, differing `created_exact` authoritative on
import. Jury rebuilt from a clean clone, re-ran its own suites, and accepted only then
(`829e053`).

## Why we are publishing it as a standalone rule

Anyone can reject a build. The cheap check after a repair is to re-run the check that failed.
The expensive check is to ask where else the repair is reachable from — and the honest answer
is usually "somewhere we did not look".

Three consequences we now enforce:

1. **A repair is not done when its failing check passes.** It is done when someone has tried to
   reach the defect from a state nobody enumerated during the original fix.
2. **Fix the constructor, not the symptom.** The defect lived in one code path (import). It had
   to be fixed where a state is *built*, not where it is *read*.
3. **Export/import and migration are attack surfaces, not plumbing.** Any path that reconstructs
   state from outside is a fresh attack surface, and it gets its own suite.

## Reproduce it

```text
evidence/stage-3/trace/f2_attack.py        the cross-attack probe; rc=0 on 3 cases
history/rejections.md                      finding L-F2-1, commits 849b017 -> 5e6f83f
evidence/stage-3/forge/legacy-import-red.txt    the failing states
evidence/stage-3/forge/legacy-import-green.txt  the states after the repair
```

Numbers in this file are the verified ones: 8001 against 8000, `-4000` in 25 of 25 views,
`-2000` in the re-imported state, repairs `11e76f9` and `ac96360`, cross-attack `849b017`,
second repair `5e6f83f`, acceptance `829e053`. No hidden-test or ranking claim is made.