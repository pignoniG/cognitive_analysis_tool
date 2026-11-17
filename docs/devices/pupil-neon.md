# Pupil Neon

Pupil Labs Neon recordings. Reader: `cwtool/devices/neon.py`.

!!! warning "Checked on few real recordings"
    The reader was written from Pupil Labs' published data format and the `pl-neon-recording` library
    (September 2026). It has since read one native recording with its scene video and three Cloud exports from a
    Neon in a Quest 3 frame; [open issues 32 and 61](../OPEN_ISSUES.md) list what is checked and what is not. Every
    result still carries a warning saying the support is experimental.

**Two routes**, named at the top of the recording's details in the app (a coloured badge) and in the export:

- **Glasses** (`pupil_neon`): the Neon's scene camera and the lux sensor, as for the Pupil Core.
- **XR** (`pupil_neon_xr`): a Neon inside a Meta Quest, whose scene camera does not see the displays. The luminance
  comes from the Quest's video capture, as from a display; see [Neon inside a Meta Quest](#neon-inside-a-meta-quest).

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
└── 4_14_10.csv               # lux logs (or lux.csv), here or in lux/
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
| blinks | `blinks ps*.raw` (type, start, end), if present |
| events | `event.txt` / `event.time` |
| scene video | `Neon Scene Camera v1 ps*.mp4` / `.time` (the longest part) |
| field of view | `calibration.bin` (scene camera matrix) |

!!! note "Pupil diameters need eye state estimation"
    The native format has pupil diameters only if real-time eye state estimation was enabled in the Companion app.
    Otherwise the reader stops with an explanation: upload the recording to Pupil Cloud and use the Timeseries
    export instead. Native recordings of data format 2.5 have blinks (`blinks ps*.raw`); on older ones the pipeline's speed filter removes the blink edges.

## Processing

- Pupil diameters are in mm (scale 1), each eye separately. Zero or missing values are invalid.
- Samples where Neon was not worn lose their pupil and gaze values; blinks (Cloud, or native `blinks ps*.raw`) remove the pupil from 0.1 s
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
distribute the lux sensor's reading over the view (which is how it is used), not measure luminance itself.

With **manual exposure** the video is photometrically stable, and it can stand in for the lux sensor: set
**Camera exposure** to `fixed` and enter the exposure time. Calibrate the camera's full-scale luminance once on a
recording made with the lux sensor (see
[Lux devices without a lux log](../processing/luminance.md#lux-devices-without-a-lux-log)). Exposures above 330 ms
lower the frame rate below 30 fps.

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

## Neon inside a Meta Quest

A recording is read on the XR route when its `info.json` names a headset frame (`frame_name`, e.g. "Quest3 XR") or when
a Quest capture that overlaps it lies in its folder or the folder above (where Pupil Cloud's download puts the export
folder next to the files copied beside it):

```text
DataCalibration_1/
  2026-11-16_11-29-14-cc09cfd6/                         the Neon's Cloud export
  com.meta.pclinkservice.server-20261116-112913-0.mp4   the Quest's capture (here of a PC app over Link)
  <...>_calibration_run_<...>.csv                       the calibration presenter's run file (aligns the capture exactly)
```

**The capture.** The Quest names it after the app that recorded it (`com.oculus.vrshell` for the headset's own view,
passthrough included; `com.meta.pclinkservice.server` for a PC app over Link) and the local time the capture started,
to the second. It holds one eye's view, 1920 × 1080, at a variable rate of about 30 fps, so its frames are timed from
their timestamps in the file. Keep the name: it is how the capture is found and placed in time. A capture copied into
the Cloud export folder is never taken as the Neon's scene video.

**Time.** Time zero is the capture's start as named, read in the phone's time zone (from the recording's name and its
UTC start). That places the capture within about a second. The app then aligns it (the switch *Align the capture to the
pupil* in Data → Scene video):

- with the calibration presenter's **run file** next to the capture or in the export folder, by the steps it logged
  in Unix time, as the Varjo's log alignment does (the presenter's computer and the Neon's phone are both kept to UTC);
- without it, by the **pupil's response**: the lag at which the pupil's speed follows the picture's changes best, less
  an assumed latency of 0.5 s. This needs a picture that changes (a calibration run); the fitted latency then holds what
  the assumption misses.

The pupil, the events and the sensors are moved onto the capture's clock; the result says which way was used.

**Gaze.** The Neon gives the gaze in its scene camera's image. Its direction (through the camera matrix) is placed in
the capture as if the capture looked straight ahead with a field of 110° × 78° (the Quest 3's horizontal field; the
16:9 capture's vertical one). The Neon's frame is fixed to the headset but not aligned with its view, so the gaze can be
off: check it in the video preview ([open issue 61](../OPEN_ISSUES.md)).

**Luminance.** As for a display: relative, from the capture's pixels, scaled by the participant's calibration fit;
no photometry is needed. The adapting field is the headset's, 110° × 96°.

**Recording a session.** Start the Quest capture, then the Neon; run the calibration in VR and keep its run file; run
the task; stop the Neon, then the capture. Put the capture and the run file next to the Neon's export.

## Profile

| | |
|---|---|
| Pupil | mm, scale 1 |
| Luminance | lux sensor, distributed with the scene video |
| Field of view | from the camera matrix (nominal 103° × 77°); adapting field 200° × 135° |
| Circular scene | no |
| Rate | measured (nominally 200 Hz) |

On the XR route (`pupil_neon_xr`): luminance from the display (the Quest's capture), field of view 110° × 78°
(nominal, the capture), adapting field 110° × 96°.
