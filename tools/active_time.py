"""Measured active room time from a Band room export (room.json).

Method: sort every event by its timestamp and add up the gaps between consecutive events that
are no longer than a threshold. Longer gaps count as idle. Standard library only.

    python tools/active_time.py room.json
"""
import json
import sys
from datetime import datetime


def stamp(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def main(path):
    with open(path, encoding="utf-8") as handle:
        messages = json.load(handle)["messages"]
    times = sorted(stamp(m["insertedAt"]) for m in messages)
    span = (times[-1] - times[0]).total_seconds() / 3600
    print(f"events {len(times)}   wall clock {span:.1f} h")
    print("gap threshold    active    idle")
    for minutes in (3, 5, 10, 15, 30):
        active = idle = 0.0
        for a, b in zip(times, times[1:]):
            gap = (b - a).total_seconds() / 60
            if gap <= minutes:
                active += gap
            else:
                idle += gap
        print(f"{minutes:>3} min        {active / 60:6.1f} h  {idle / 60:6.1f} h")
    gaps = sorted(((b - a).total_seconds() / 3600, a, b) for a, b in zip(times, times[1:]))[-8:]
    print("longest gaps:")
    for hours, a, b in gaps:
        print(f"  {hours:5.1f} h   {a:%m-%d %H:%MZ} to {b:%m-%d %H:%MZ}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "room.json")
