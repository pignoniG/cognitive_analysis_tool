import time
from datetime import datetime
import csv

# -------------------------
# CONFIGURATION
# -------------------------

events = [
("Riposo" , 60), 
("Briefing" , None),
("CountB_7" , None),
("Riposo" , 30), 
("Notte" , 60), 
("Briefing" , None),
("Fibonacci", None),
("Riposo" , 30), 
("Alba" , 60), 
("Briefing" , None),
("10_Nomi" , None),
("Riposo" , 30), 
("Nuvolo" , 60), 
("Briefing" , None),
("CountB_13" , None),
("Riposo" , 60)
]


# -------------------------
# EVENT LOGGER
# -------------------------

log = []

print("\nEvent logger started\n")

input(f"Ready! Press Enter to start...")

output_csv = datetime.now().strftime('%Y-%b-%d_%H-%M-%S')+"_event_log.csv"  # set to None to disable CSV output
print ("output_csv",output_csv)

for name, duration in events:
  
    start_time = datetime.now()
    start_ts = time.time()
    print(f"Started '{name}' at {start_time.strftime('%H:%M:%S')}")

    if duration is not None:
        time.sleep(duration)
        end_ts = time.time()
    else:
        input(f"Press Enter to stop '{name}'...")
        end_ts = time.time()

    end_time = datetime.fromtimestamp(end_ts)
    elapsed = end_ts - start_ts

    log.append({
        "event": name,
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": elapsed
    })

    print(f"Finished '{name}' (duration: {elapsed:.2f} s)\n")

# -------------------------
# SUMMARY
# -------------------------

print("\nEvent summary:")
for entry in log:
    print(
        f"{entry['event']}: "
        f"{entry['duration_seconds']:.2f} s "
        f"(started {entry['start_time'].strftime('%H:%M:%S')})"
    )

# -------------------------
# OPTIONAL CSV EXPORT
# -------------------------

if output_csv:
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Event", "Start Time", "End Time", "Duration (s)"])
        for e in log:
            writer.writerow([
                e["event"],
                e["start_time"].isoformat(),
                e["end_time"].isoformat(),
                f"{e['duration_seconds']:.3f}"
            ])

    print(f"\nLog saved to {output_csv}")
