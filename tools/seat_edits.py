#!/usr/bin/env python3
"""Who edited stage code, counted from the room log.

Usage:
    python tools/seat_edits.py room.json

Standard library only. Reads the export read-only and writes nothing.

Counts Edit / Write / MultiEdit / NotebookEdit tool calls per seat, split by whether
the target path lies under stage-1/ .. stage-4/ in the result repository.

Two traps this script exists to avoid:

1. evidence/stage-N/ is NOT stage code. Paths such as
   .../result/evidence/stage-3/decisions.md match a naive "stage-N" search but are
   evidence files. Only a stage-N directory that is not nested under evidence/ counts.
2. The console export truncates tool call args at 2000 characters. Write calls with a
   long content field lose the file_path key entirely, because it is stored after the
   content. Those calls are counted in the "all" column and reported as path-unknown.
   They are never silently folded into the stage-N column.

Operator editability is out of scope for this file: it counts what the seats did, not
what the operator did. For that, see the commit-level disclosure in FACTORY.md.
"""

import json
import re
import sys
from collections import Counter, defaultdict

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

# stage-1 .. stage-4 as a path segment, either slash form
STAGE_SEG = re.compile(r"(?:^|/)(stage-([1-4]))(?:/|$)")
# "file_path":"...." with either escaped or single backslashes
FP_RE = re.compile(r'"file_path"\s*:\s*"(.*?)"')
# the console export cuts args at this length
ARG_TRUNCATE_AT = 2000


def stage_of(path):
    """Return 'stage-N' only for a real stage code directory, else None.

    Excludes anything under evidence/, which holds per-stage evidence files whose
    names contain stage-N but which are not the deliverable service.
    """
    if not path:
        return None
    for m in STAGE_SEG.finditer(path):
        before = path[:m.start()].rstrip("/")
        parent = before.rsplit("/", 1)[-1].lower()
        if parent == "evidence":
            continue
        return m.group(1)
    return None


def norm(p):
    """Normalise a captured path so windows and posix forms compare equal."""
    return p.replace("\\\\", "\\").replace("\\", "/")


# the result repository, as a prefix used to tell shipped code from scratch copies
REPO_PREFIX = "d:/project/dolphin-tank/band-work/result/"


def in_repo(path):
    """True when the path lies inside the submitted result repository."""
    return bool(path) and path.lower().startswith(REPO_PREFIX)


def target_of(args):
    """Best effort target path from a tool call's args."""
    if isinstance(args, dict):
        for k in ("file_path", "path", "filePath", "notebook_path"):
            if args.get(k):
                return norm(str(args[k]))
        return None
    if isinstance(args, str):
        m = FP_RE.search(args)
        if m:
            return norm(m.group(1))
        return None
    return None


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: python tools/seat_edits.py room.json\n")
        return 2

    with open(argv[1], encoding="utf-8") as fh:
        data = json.load(fh)

    msgs = data.get("messages") or []

    per_seat_total = Counter()
    per_seat_stage = Counter()
    per_seat_tool = defaultdict(Counter)
    per_seat_evidence = Counter()
    stage_targets = defaultdict(set)
    no_path = Counter()
    truncated = Counter()
    per_seat_repo = Counter()
    outside = Counter()

    for m in msgs:
        if str(m.get("messageType")) != "tool_call":
            continue
        try:
            call = json.loads(m.get("content") or "{}")
        except Exception:
            continue
        name = str(call.get("name"))
        if name not in EDIT_TOOLS:
            continue

        seat = str(m.get("senderName"))
        raw = call.get("args")
        per_seat_total[seat] += 1
        per_seat_tool[seat][name] += 1

        if isinstance(raw, str) and len(raw) >= ARG_TRUNCATE_AT:
            pass

        path = target_of(raw)
        if not path:
            no_path[seat] += 1
            if isinstance(raw, str) and len(raw) >= ARG_TRUNCATE_AT:
                truncated[seat] += 1
            continue

        stage = stage_of(path)
        if stage:
            per_seat_stage[seat] += 1
            stage_targets[seat].add(path)
            if in_repo(path):
                per_seat_repo[seat] += 1
            else:
                outside[seat] += 1
        else:
            per_seat_evidence[seat] += 1

    seats = sorted(set(per_seat_total) | set(per_seat_stage))

    print("Edit-family tool calls per seat, from the room log")
    print("(Edit / Write / MultiEdit / NotebookEdit)")
    print()
    print("%-10s %8s %8s %10s %10s   %s"
          % ("seat", "all", "stage-N", "evidence/N", "path-unkn", "tools"))
    print("-" * 98)
    for s in seats:
        tools = ", ".join("%s=%d" % (k, v) for k, v in sorted(per_seat_tool[s].items()))
        print("%-10s %8d %8d %10d %10d   %s"
              % (s, per_seat_total[s], per_seat_stage[s], per_seat_evidence[s],
                 no_path[s], tools))
    print("-" * 98)
    print("%-10s %8d %8d %10d %10d"
          % ("TOTAL", sum(per_seat_total.values()), sum(per_seat_stage.values()),
             sum(per_seat_evidence.values()), sum(no_path.values())))
    print()
    print("stage-N is a stage-N directory NOT under evidence/.")
    print("evidence/N is a write to evidence/stage-N/ or similar, which is not stage code.")
    print("in-repo counts only targets under band-work/result/; a scratch copy elsewhere")
    print("is counted in stage-N but not in in-repo.")
    print()
    print("%-10s %5s %5s" % ("seat", "in-repo", "outside"))
    for s in seats:
        print("%-10s %5d %5d" % (s, per_seat_repo[s], outside[s]))
    print("%-10s %5d %5d" % ("TOTAL", sum(per_seat_repo.values()), sum(outside.values())))
    print()

    print("distinct stage- code files targeted per seat:")
    for s in seats:
        paths = sorted(stage_targets[s])
        stages = sorted({stage_of(p) for p in paths})
        print("   %-10s %4d distinct file(s) across %s"
              % (s, len(paths), ", ".join(stages) if stages else "(none)"))
    print()

    print("stage-N edit calls per seat per stage folder:")
    folders = defaultdict(Counter)
    for m in msgs:
        if str(m.get("messageType")) != "tool_call":
            continue
        try:
            call = json.loads(m.get("content") or "{}")
        except Exception:
            continue
        if str(call.get("name")) not in EDIT_TOOLS:
            continue
        stage = stage_of(target_of(call.get("args")))
        if stage:
            folders[str(m.get("senderName"))][stage] += 1
    for s in sorted(folders):
        parts = ["%s=%d" % (k, folders[s][k]) for k in sorted(folders[s])]
        print("   %-10s %s" % (s, "  ".join(parts)))
    print()

    print("path-unknown by seat, against the %d character export truncation:"
          % ARG_TRUNCATE_AT)
    for s in sorted(no_path):
        print("   %-10s %5d unknown   %5d of those at the truncation limit"
              % (s, no_path[s], truncated[s]))
    tot_no = sum(no_path.values())
    tot_tr = sum(truncated.values())
    print("   %-10s %5d unknown   %5d of those at the truncation limit"
          % ("TOTAL", tot_no, tot_tr))
    if tot_no - tot_tr:
        print("   note: %d path-unknown calls are shorter than the limit and still"
              " carry no file_path key" % (tot_no - tot_tr))
    print()
    print("These are counted in the all column only. They are NOT added to stage-N,")
    print("because their target cannot be read back from the export.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))