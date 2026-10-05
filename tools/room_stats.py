#!/usr/bin/env python3
"""Room statistics from a BAND console export.

Usage:
    python tools/room_stats.py room.json

Standard library only. Reads the export read-only and writes nothing.

Field names are the ones actually present in the console export:
  messages[].senderType    "Agent" or "User"
  messages[].messageType   text | thought | task | tool_call | tool_result | error | participant
  messages[].senderName    seat display name
  messages[].insertedAt    ISO 8601 UTC timestamp
"""

import json
import sys
from collections import Counter


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: python tools/room_stats.py room.json\n")
        return 2

    path = argv[1]
    data = load(path)

    room = data.get("room") or {}
    msgs = data.get("messages") or []

    print("room id        : %s" % room.get("id"))
    print("room title     : %s" % room.get("title"))
    print("export scope   : %s" % data.get("scope"))
    print("exported at    : %s" % data.get("exportedAt"))
    print("total messages : %d" % len(msgs))
    print()

    if not msgs:
        print("no messages")
        return 0

    stamps = sorted(m["insertedAt"] for m in msgs if m.get("insertedAt"))
    print("first timestamp: %s" % stamps[0])
    print("last timestamp : %s" % stamps[-1])
    print()

    print("by messageType :")
    for k, v in sorted(Counter(str(m.get("messageType")) for m in msgs).items()):
        print("   %-12s %5d" % (k, v))
    print()

    print("by senderType  :")
    for k, v in sorted(Counter(str(m.get("senderType")) for m in msgs).items()):
        print("   %-12s %5d" % (k, v))
    print()

    print("messages per sender (all types):")
    per_sender = Counter((str(m.get("senderType")), str(m.get("senderName"))) for m in msgs)
    for (stype, sname), v in sorted(per_sender.items(), key=lambda kv: (-kv[1], kv[0][1])):
        print("   %-6s %-18s %5d" % (stype, sname, v))
    print()

    human_text = [
        m for m in msgs
        if str(m.get("senderType")) == "User" and str(m.get("messageType")) == "text"
    ]
    print("human text messages (senderType User and messageType text): %d" % len(human_text))
    for m in sorted(human_text, key=lambda x: x["insertedAt"]):
        first = (m.get("content") or "").strip().splitlines()[0][:96]
        print("   %s  %s" % (m["insertedAt"], first))
    print()

    agent_tool = [
        m for m in msgs
        if str(m.get("senderType")) == "Agent" and str(m.get("messageType")) == "tool_call"
    ]
    print("agent tool_call messages: %d" % len(agent_tool))
    print("per-seat share of agent tool_call messages:")
    seat_calls = Counter(str(m.get("senderName")) for m in agent_tool)
    total_calls = sum(seat_calls.values())
    for seat, n in sorted(seat_calls.items(), key=lambda kv: (-kv[1], kv[0])):
        share = (100.0 * n / total_calls) if total_calls else 0.0
        print("   %-10s %5d  %5.1f%%" % (seat, n, share))
    print("   %-10s %5d  %5.1f%%" % ("TOTAL", total_calls, 100.0 if total_calls else 0.0))
    print()

    errs = [m for m in msgs if str(m.get("messageType")) == "error"]
    print("error events: %d" % len(errs))
    for m in sorted(errs, key=lambda x: x["insertedAt"]):
        text = " ".join((m.get("content") or "").split())
        print("   %s  %-8s %s" % (m["insertedAt"], m.get("senderName"), text[:88]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))