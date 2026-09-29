# Lux and event loggers

Two standalone scripts in `tools/` record data alongside the eye tracker.

## Lux logger

Logs the [TSL2591 lux sensor](../hardware/lux-sensor.md) when its microcontroller is connected to a computer over
USB, instead of logging to the board's SD card.

```bash
pip install -e ".[logger]"
python tools/lux_logger.py OUTPUT_FOLDER [--port PORT] [--baud 250000]
```

Without `--port`, the first USB serial device that looks like one of the supported boards (Adafruit, Arduino,
CH340 "USB2.0-Serial") is used; if none is found, the available ports are listed. Stop with Ctrl+C.

Readings (about 10 per second) are appended to one CSV per hour, named `<month>_<day>_<hour>.csv` in local time,
with rows

```text
unix time (ms), day, hour, minute, lux
```

the same format as the SD card logger and version 1.x. The analysis reads only the first column (time) and the
fifth (lux).

!!! tip "Use the same computer as the eye tracker"
    Logging on the computer that records the Pupil Core puts both on the same clock. The SD card logger's
    real-time clock drifts by seconds per day and ignores time zones; compensate with the **time lag** parameter.
    For the Neon, whose timestamps come from the Companion phone, see
    [clock synchronisation](../devices/pupil-neon.md#clocks).

## Event logger

Times the phases of an experiment and writes the `event_log` CSV the analysis reads, so ΔPD is averaged per phase
and the phases are shaded on the plots.

```bash
python tools/event_logger.py PROTOCOL.csv [--out FOLDER]
```

The protocol file has one `name,duration` line per phase (seconds). A blank duration means the phase lasts until
you press Enter; lines starting with `#` are comments. `tools/example_protocol.csv` is the protocol of the
February tests:

```text
# name,duration in seconds (blank = press Enter to end the phase)
Riposo,60
Briefing,
CountB_7,
Riposo,30
...
```

Start the logger with the recording, press Enter to begin, and follow the prompts. The log is saved as
`<date>_event_log.csv` with columns `Event, Start Time, End Time, Duration (s), Start (unix s), End (unix s)`. Times are
ISO 8601 with the UTC offset and also Unix time, so the file reads the same on any computer. Copy it into the
recording folder.

Each phase starts at its own logged time, so pauses between phases are kept. The reader takes the Unix start when
present, else the ISO time. Logs from the older logger have ISO times without a zone: for Varjo recordings they are
read in the zone of the computer that recorded (from Varjo Base's file name, which is in local time), for Glasses 3
recordings in the recording unit's zone (`recording.g3`), for the Pupil devices in the zone of the computer running the
analysis.

!!! note "Neon and Glasses 3 events"
    Events marked in the Neon Companion app or in Pupil Cloud, and Glasses 3 events (`eventdata.gz`), are read
    directly from the recording; see [Pupil Neon](../devices/pupil-neon.md#events) and
    [Tobii Pro Glasses 3](../devices/tobii-g3.md). An `event_log` CSV in the folder is read as well.
