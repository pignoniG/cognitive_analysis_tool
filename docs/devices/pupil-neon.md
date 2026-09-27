# Pupil Neon

Pupil Labs Neon recordings. Reader: `cwtool/devices/neon.py`.

!!! warning "Not yet tested on a real recording"
    The reader was written from Pupil Labs' published data format and the `pl-neon-recording` library
    (September 2026) and is tested on synthetic recordings only. [Open issue 32](../OPEN_ISSUES.md) lists what a
    real recording must confirm.

Two layouts are read. Prefer the Pupil Cloud export: it has pupil diameters and blinks computed at the full 200 Hz
even when the phone could not keep up in real time.

## Pupil Cloud "Timeseries Data + Scene Video"

Download the recording from Pupil Cloud as **Timeseries Data + Scene Video** and open the recording's folder.

```text
<recording name>-<id>/
├── info.json                 # start_time (UTC ns), gaze_mode, versions
├── 3d_eye_states.csv         # pupil diameter left/right [mm], 200 Hz
├── gaze.csv                  # gaze x/y [px], worn
├── blinks.csv
├── events.csv
├── world_timestamps.csv      # frame timestamps [ns]
├── scene_camera.json         # camera matrix, distortion
├── <section id>_<start>-<end>.mp4
└── 4_14_10.csv               # lux logs, here or in lux/
```

| Used for | File and column |
|---|---|
| pupil | `3d_eye_states.csv`: `pupil diameter left [mm]`, `pupil diameter right [mm]` (older exports: `pupil diameter [mm]`, used for both eyes) |
| gaze | `gaze.csv`: `gaze x [px]`, `gaze y [px]`, divided by the video's size |
| not worn | `gaze.csv`: `worn` = 0 |
| blinks | `blinks.csv`: `start timestamp [ns]`, `end timestamp [ns]` |
| frame times | `world_timestamps.csv`: `timestamp [ns]` |
| events | `events.csv`: `timestamp [ns]`, `name` |
| field of view | `scene_camera.json`: `camera_matrix` |

With several sections (recording paused and resumed), the longest section and its video are analysed.

## Native recording format

The folder copied from the Companion phone over USB, or downloaded from Pupil Cloud as "Native Recording Data".
Each stream is a binary `<name> ps<n>.raw` with a `<name> ps<n>.time` file of int64 UTC nanoseconds.

| Used for | Files |
|---|---|
| pupil | `eye_state ps*.raw` (float32 records; left diameter first, right diameter at field 7, or by name from `eye_state.dtype`) |
| gaze | `gaze_200hz.raw` / `.time` if present, else `gaze ps*.raw` |
| not worn | `worn_200hz.raw` or `worn ps*.raw` (on the gaze timestamps) |
| events | `event.txt` / `event.time` |
| scene video | `Neon Scene Camera v1 ps*.mp4` / `.time` (the longest part) |
| field of view | `calibration.bin` (scene camera matrix) |

!!! note "Pupil diameters need eye state estimation"
    The native format has pupil diameters only if real-time eye state estimation was enabled in the Companion app.
    Otherwise the reader stops with an explanation: upload the recording to Pupil Cloud and use the Timeseries
    export instead. Blinks are not in the native format; the pipeline's speed filter removes their edges.

## Processing

- Pupil diameters are in mm (scale 1), each eye separately. Zero or missing values are invalid.
- Samples where Neon was not worn lose their pupil and gaze values; Cloud blinks remove the pupil from 0.1 s
  before to 0.1 s after each blink.
- Samples are averaged into bins on a grid at the measured rate (nominally 200 Hz).
- Time zero is the first scene frame; the eye cameras start slightly earlier, so the recording can start at
  negative times.

## Events

Neon events are instants. They are turned into intervals as follows:

- `recording.begin` and `recording.end`, which Neon adds to every recording, are ignored.
- Pairs named `<label>.begin` / `<label>.end` (also `_start`/`_stop`, `onset`/`offset`, with `.`, `_`, `-` or a
  space) become one event `<label>`.
- Any other event starts a phase that lasts until the next such event, or the end of the recording.

An `event_log` CSV from the [event logger](../usage/tools.md#event-logger) in the folder is read as well.

## Scene camera exposure

Neon's scene camera can run with **manual exposure** (1–1000 ms, set in the Companion app's preview), or one of
three automatic modes. Automatic exposure rescales the video's brightness with the scene, so the video can only
distribute the lux sensor's reading over the view (which is how it is used), not measure luminance itself. For
studies where the video should be photometrically stable, use manual exposure and keep it fixed across a
participant's recordings; exposures above 330 ms lower the frame rate below 30 fps.

## Clocks

Neon's timestamps come from the Companion phone's clock, the lux logger's from the computer (or the SD logger's
real-time clock). Pupil Labs report offsets under 10 ms between freshly synced clocks, growing to about 1 s after
24 hours. Before a session, force both to resync with the time server, as Pupil Labs recommend:

- **Phone:** *Settings → System → Date & time*, turn off *Set time automatically*, move the time by one hour, wait
  5 seconds, turn it back on.
- **Computer running the lux logger:** the same in the system's date and time settings (on macOS then run
  `sudo sntp -sS time.apple.com`).

Any remaining offset shifts the luminance against the pupil and can be corrected with the **time lag** parameter
([open issue 34](../OPEN_ISSUES.md)). A light switched on in front of both the sensor and the scene camera gives a
visible mark to measure it.

## Profile

| | |
|---|---|
| Pupil | mm, scale 1 |
| Luminance | lux sensor, distributed with the scene video |
| Field of view | from the camera matrix (nominal 103° × 77°); adapting field 200° × 135° |
| Circular scene | no |
| Rate | measured (nominally 200 Hz) |
