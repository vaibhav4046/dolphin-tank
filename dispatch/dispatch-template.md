# Dispatch template

The generic shape of the human message that starts a stage. The track detail lives here, in the
room, and never in a seat's mandate. Replace the placeholders. The real messages are in
`room.json` (the four human dispatches).

```text
@<coordinator> You are the lead seat for our factory. Coordinate the other seats
(@<seat>, @<seat>, @<seat>, @<acceptor>) and build <STAGE> of the track below in its own
complete, buildable folder. Later stages will be dispatched separately; build nothing beyond
<STAGE> now.

Track: <TRACK>
Specification (read in full, it is the source of truth): <ABSOLUTE PATH TO THE STAGE SPEC>
Result repository (absolute path, shared by every seat, commit only here; it already holds the
frozen mandates): <ABSOLUTE PATH>
<STAGE> goes in: <ABSOLUTE PATH>\<stage folder>\
Start from the accepted previous folder: copy it forward, delete any nested .git in the copy,
and widen the copy to this stage's specification. Do not modify an accepted earlier folder.
Required in the stage folder: source, a Dockerfile, a RUN.md. It must build and serve from a
clean container with no outbound network at run time.

Rules of this run:
- Build to the written specification, never to the shipped checks. The rest are held back and
  every one of them is written in the specification. Do not read or copy the test directory or
  anything in the harness folder. Run the shipped checks only through the harness command below.
- After the shipped checks pass, the independent seat states in writing what the specification
  demands that the shipped checks never demonstrated, then writes and runs checks for exactly
  those requirements. Keep that work proportionate and do not re-verify an unchanged commit.
- Require real concurrency and retry behaviour, not only sequential correctness.
- Earlier stages must keep working. Do not add anything that belongs to a later stage.

Run the shipped checks inside WSL2. Use a new --out directory every run:
<HARNESS COMMAND WITH --stage N --mode isolated --out <unique>>

Report back to me when <STAGE> is accepted or blocked, per your mandate.
```
