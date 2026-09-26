#!/usr/bin/env python3
"""Log the timing of experiment phases to an ``event_log`` CSV.

Phases come from a protocol file with one ``name,duration`` per line; a blank
duration means the phase ends when you press Enter. Start the logger together
with the recording, then copy the CSV into the recording folder so the
analysis can shade and average ΔPD per event.

    python tools/event_logger.py tools/example_protocol.csv [--out FOLDER]

Output columns: Event, Start Time, End Time, Duration (s). Times are ISO 8601
with the UTC offset, so the log reads the same on any computer.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path


def read_protocol(path: Path) -> list[tuple[str, float | None]]:
    events = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].startswith("#"):
                continue
            duration = row[1].strip() if len(row) > 1 else ""
            events.append((row[0].strip(), float(duration) if duration else None))
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("protocol", type=Path, help="CSV of name,duration (s); blank duration = press Enter")
    ap.add_argument("--out", type=Path, default=Path("."), help="output folder")
    args = ap.parse_args()

    events = read_protocol(args.protocol)
    if not events:
        print(f"No events in {args.protocol}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / (datetime.now().strftime("%Y-%b-%d_%H-%M-%S") + "_event_log.csv")

    input("Ready! Press Enter to start...")
    log = []
    for name, duration in events:
        start = datetime.now().astimezone()
        start_ts = time.time()
        print(f"Started '{name}' at {start:%H:%M:%S}")
        if duration is None:
            input(f"Press Enter to stop '{name}'...")
        else:
            time.sleep(duration)
        end_ts = time.time()
        end = datetime.fromtimestamp(end_ts).astimezone()
        log.append((name, start, end, end_ts - start_ts))
        print(f"Finished '{name}' ({end_ts - start_ts:.2f} s)\n")

    with open(output, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Event", "Start Time", "End Time", "Duration (s)"])
        for name, start, end, elapsed in log:
            w.writerow([name, start.isoformat(), end.isoformat(), f"{elapsed:.3f}"])
    print(f"Log saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
