# Sensor logger

A desktop app that records the lux sensor, a Shimmer (ECG and other signals) and an EmotiBit side by side, on the
computer's clock, together with the phases of the experiment. It replaces running `tools/lux_logger.py` and
`tools/event_logger.py` separately (see [Lux and event loggers](tools.md), which still work).

```bash
pip install -e ".[logger]"
cwtool-logger                 # or: python -m cwtool.logger
```

!!! warning "On macOS, start it from Terminal"
    The Shimmer is reached through macOS's Bluetooth, and macOS ends any program that uses Bluetooth unless the app
    that started it has been allowed to. Terminal asks the first time (allow it); the Claude app, and some editors'
    built-in terminals, are not allowed. The logger checks first, and adding a Shimmer from such an app fails with
    "This app may not use Bluetooth".

## Recording

1. **Add the sensors** with the *+ Lux*, *+ Shimmer*, *+ EmotiBit* buttons (see below). Each sensor gets a live plot
   as soon as it is connected, so the signals can be checked before recording; nothing is saved yet. Choose the signal
   shown with the drop-down above each plot.
2. **Pick the folder** for the recordings (remembered between sessions) and press the green **Start recording**
   button. It turns red (**Stop recording**) with the elapsed time beside it.
3. **Mark the phases** of the experiment, if any (see [Events](#events)).
4. Press **Stop recording**. The folder is shown in the status bar.

Sensors can be added or removed while recording; one added during a recording starts its own file at that moment.
The table lists each sensor's status (*ok*, *waiting for data*, *silent* with the seconds since its last sample, or
the error that stopped it), its row count and the time since the last row.

### What the plots show

The time axis is the last 30 s. The value axis follows the data: the span of the signal with a margin, ignoring the
outermost 0.5 % so one spike does not flatten it, and at least 1 % of the signal's level so noise on a flat signal is
not magnified.

## The sensors

### Lux sensor

The [TSL2591 logger](../hardware/lux-sensor.md) on a USB port. *+ Lux* finds the board by its name (Adafruit, Arduino,
CH340 "USB2.0-Serial"); choose the port by hand if several are connected. About 10 readings per second.

### Shimmer

A Shimmer3 running the LogAndStream firmware (the one Consensys uses), streaming over Bluetooth. The sensors enabled
on the device in Consensys are the ones logged, as the **raw values the device sends** (ADC counts); converting to
mV or µS is done in the analysis. Typical sampling rate 51.2 Hz.

- **Windows and Linux:** pair the Shimmer in the system's Bluetooth settings, then choose its serial port in the add
  dialog (`COM5`, `/dev/rfcomm0`, ...).
- **macOS:** pair it in *System Settings → Bluetooth*. The add dialog lists the paired Shimmers by name and address
  (`Shimmer3-873A  (Bluetooth 00-06-66-...)`) and connects to them directly, because the `/dev/cu.Shimmer...` port that
  macOS creates often stays silent. The first attempt can fail and be repeated automatically; connecting takes up to
  half a minute. See the warning above about starting from Terminal.

When connecting, the logger sets the Shimmer's real-time clock to the computer's time (tick the box in the add dialog
off to skip it), as Consensys does, and saves the offset it measured in `session.json` (`real-time clock`). This does
**not** change the logger's files: the streamed samples are stamped by another clock (ticks since power-on, mapped onto
the computer's time as described under [Clocks](#clocks)). It makes the unit's own SD card recordings agree with the
computer, and clears the blue/green "clock not set" light. The clock is lost when the unit is switched off, and it does
not correct the drift of the unit's oscillator.

Switch the Shimmer on and wait for its slow blue blink (standby) before connecting; only one computer can be
connected to it at a time, so close Consensys first. Its status lights:

| Light | Pattern | Meaning |
|---|---|---|
| upper, blue | 0.1 s on, 2 s off | standby, waiting for a connection |
| upper, blue | solid | connected |
| upper, blue | 1 s on, 1 s off | streaming |
| upper, blue / green | alternating, 0.1 s each | the unit's clock is not set (normal after switching on), or no configuration file on its SD card; streaming still works |
| lower | yellow solid, green solid | charging, full (docked) |
| lower | green, yellow, red, 0.1 s every 5 s | full, medium, low charge (undocked) |

A solid red lower light means the battery is critically low: a unit in that state may show the Bluetooth connection
but never answer. Charge it first.

### EmotiBit

The EmotiBit sends its data over Wi-Fi to the **EmotiBit Oscilloscope**, which can publish it as
[Lab Streaming Layer](https://labstreaminglayer.org) (LSL) streams; the logger reads those. So the Oscilloscope must be
running, connected to the device, with its **LSL output enabled**; the logger does not talk to the EmotiBit directly.

- The EmotiBit joins a **2.4 GHz** Wi-Fi network named in a `config.txt` on its SD card
  (`{"WifiCredentials": [{"ssid": "...", "password": "..."}]}`), or entered over USB serial with the `C` key. Without
  it the Oscilloscope cannot find the device. The computer must be on the same network (and subnet).
- The USB cable is for power, flashing and status messages only; sensor data does not travel over it.
- The Oscilloscope publishes one single-channel stream per signal (EDA, PPG_RED, ACC_X, HR, ...), all carrying the
  device ID (for example `MD-V7-0000188`) as their source. *+ EmotiBit* lists the devices found on the network (this
  takes a couple of seconds) and records all the streams of the one you choose.

## Events

The phases of the experiment are saved in `event_log.csv`, the file the analysis reads to shade and average ΔPD per
phase. They are only recorded while recording.

- **Manual:** type a name and press *Begin* (or Enter). The running phase, if any, ends at the same instant; *End*
  ends it without starting another.
- **Protocol:** *Load protocol…* reads a CSV with one `name,duration` per line (duration in seconds, blank = until
  you press *Next phase*; lines starting with `#` are comments), the same format as `tools/example_protocol.csv`.
  *Start protocol* begins the first phase; phases with a duration advance by themselves, the others wait for *Next
  phase*. The current phase and the time left are shown below the buttons.

Stopping the recording ends the running phase.

## What is saved

Each recording gets its own folder, named by the date and time it started:

```text
<recordings folder>/2026-10-06_15-30-00/
├── lux.csv
├── shimmer.csv
├── emotibit.csv
├── event_log.csv
└── session.json
```

One file per sensor, named after the sensor (a second Shimmer would be `shimmer_2.csv`), written while recording and
flushed every second, so a crash loses little. Every data file starts with a header and its first column is the
**Unix time in seconds** on the computer's clock, so the analysis cuts the span it needs from each file.

| File | Columns |
|---|---|
| `lux.csv` | `unix time (s)`, `lux` |
| `shimmer.csv` | `unix time (s)`, `device time (s)`, then one column per enabled channel (`accel_ln_x`, `gyro_mpu9150_x`, `exg_ads1292r_1_ch1_24bit`, ...), raw values |
| `emotibit.csv` | `unix time (s)`, `signal`, `value`: one row per sample, with the stream name (`EDA`, `PPG_RED`, ...) as the signal, so signals of different rates share the file |
| `event_log.csv` | `Event`, `Start Time`, `End Time`, `Duration (s)`, `Start (unix s)`, `End (unix s)`, as written by `tools/event_logger.py` |
| `session.json` | start and end, the computer's UTC offset, and for each sensor its file, kind, columns, settings (port, sampling rate, ...) and row count |

`lux.csv` is read by the analysis as it is: put it (the recording's folder) with the eye tracker's recording, or
point the *lux folder* setting at it ([Luminance](../processing/luminance.md#lux-sensor-devices)). The older hourly
`<month>_<day>_<hour>.csv` files remain supported.

### Clocks

All times are the Unix time of the computer running the logger. Run it on the computer that records the Pupil Core and
both share a clock; for the Neon, whose timestamps come from the phone, see
[clock synchronisation](../devices/pupil-neon.md#clocks).

- **Lux:** stamped when the line arrives over USB.
- **Shimmer:** its own clock is regular but drifts, and Bluetooth delivers samples in bursts. `device time (s)` is the
  device's clock (zero at the first sample) and `unix time (s)` maps it onto the computer's clock, using the smallest
  difference between the two over the last minute (the sample that arrived with the least delay), so the burst delay
  does not enter. Both columns are saved, so the mapping can be redone.
- **EmotiBit:** LSL's own clock synchronisation and de-jittering, then converted to Unix time. In a test the newest
  sample was about 0.35 s old when the logger received it; that is delivery delay, and whether the timestamps
  themselves are exact has not been measured.

These assumptions have not been checked against an external reference ([open issue 49](../OPEN_ISSUES.md)).

## When something does not work

- **The window freezes.** If it stops responding for more than 2 s, the stack of every thread is written to
  `stall.log` in the recordings folder. Send it with a note of which sensors were connected.
- **A sensor says *silent*.** The device stopped sending: check its battery, its connection, and for the EmotiBit that
  the Oscilloscope is still connected and streaming.
- **Shimmer: no answer.** Not in standby (switch it off and on), still connected to Consensys or another computer, a
  flat battery (red light), or, on macOS, the program was not started from Terminal.
- **EmotiBit: not in the list.** The Oscilloscope does not see it (Wi-Fi settings, 2.4 GHz, same network), or its LSL
  output is off.
- **Disk errors** (for example a full disk) are shown in the status bar; the recording goes on, and the rows that could
  not be written are missing from the file.

## From Python

The window is a thin layer over classes that do not use Qt:

```python
from pathlib import Path
from cwtool.logger import Logger
from cwtool.logger.sources import LuxSerialSource, ShimmerSource, LslSource

log = Logger()
log.add(LuxSerialSource())                        # connects, then streams into live buffers
log.add(LslSource("MD-V7-0000188", name="emotibit"))
session = log.start_recording(Path("recordings"))
log.mark("Baseline")                              # begin an event
...
log.stop_recording()                              # returns the session folder
log.shutdown()
```

A new sensor is a `Source` subclass (`cwtool/logger/base.py`): `open()` connects and sets `columns`, `run(emit,
stopped)` calls `emit([(unix_time, value, ...), ...])` until `stopped` is set.
