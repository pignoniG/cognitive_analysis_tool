# Tobii Pro Glasses 3

!!! warning "Experimental support"
    The reader (`cwtool/devices/tobii_g3.py`) was written from the 1.x Tobii branch (`develop-for-Tobii-Pro-III`,
    2022) and Tobii's recording format, and is tested on synthetic recordings only. Every result carries a warning
    until a real recording has confirmed it. [Open issue 45](../OPEN_ISSUES.md) lists what to check.

## Folder

Copy the recording folder from the recording unit's SD card:

```text
<recording>/
├── recording.g3        # JSON: created (UTC start), duration, stream files, scene camera calibration
├── gazedata.gz         # gaze and pupil, one JSON object per line
├── eventdata.gz        # events (optional)
├── scenevideo.mp4      # scene camera
├── 9_28_10.csv         # lux logs, here or in lux/
└── <date>_event_log.csv  # optional, from tools/event_logger.py
```

## What is read

| Used for | Source |
|---|---|
| start time | `recording.g3` → `created` (UTC); the recording start is taken as the start of the scene video |
| pupil | `gazedata.gz` → `data.eyeleft.pupildiameter`, `data.eyeright.pupildiameter` (mm) |
| gaze | `gazedata.gz` → `data.gaze2d`, normalised scene video coordinates, origin top left |
| invalid samples | samples with empty `data`; each eye separately, so a sample with one eye tracked still counts for that eye |
| scene video | `recording.g3` → `scenecamera.file` (default `scenevideo.mp4`), frames timed by its frame rate |
| field of view | `recording.g3` → `scenecamera.camera-calibration` (focal length, resolution) with a pinhole model, else the nominal 95° × 63° |
| events | `eventdata.gz` entries of type `event`, named by their `tag` (other types, such as `syncport`, are ignored); an `event_log` CSV is read as well |

Events are turned into intervals as for the Neon: `<label>.begin` / `<label>.end` pairs become one event, other
events last until the next one.

Differences from 1.x: 1.x kept only samples with both pupils, and flipped gaze y (`1 − y`), which suits the Pupil
Core's coordinates, not Tobii's. 2.0 keeps each eye separately and does not flip; `load(..., flip_gaze_y=True)`
reproduces the 1.x behaviour if a real recording shows the flip was right.

## Luminance

Like the other glasses, the Glasses 3 is used with the external [lux sensor](../hardware/lux-sensor.md), distributed
over the view with the scene video; without lux logs the camera is used alone
([Luminance](../processing/luminance.md#lux-devices-without-a-lux-log)).

## Profile

| | |
|---|---|
| Support | experimental |
| Pupil | mm, scale 1 |
| Luminance | lux sensor |
| Field of view | from the camera calibration (nominal 95° × 63°); adapting field 200° × 135° |
| Circular scene | no |
| Rate | measured (50 Hz, or 100 Hz if set on the unit) |
