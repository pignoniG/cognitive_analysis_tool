# Pupil Core

Pupil Labs Pupil Core recordings, exported with Pupil Player. Reader: `cwtool/devices/pupil_core.py`.

## Folder

```text
recording/
├── info.player.json          # start times (system and Pupil clock)
├── world.mp4                 # scene video
├── world_timestamps.npy      # capture time of each frame (Pupil clock)
├── world.intrinsics          # scene camera matrix (msgpack)
├── exports/
│   └── 000/                  # the newest numbered export is used
│       ├── pupil_positions.csv
│       └── gaze_positions.csv
├── 4_14_10.csv               # lux logs, here or in lux/
└── <date>_event_log.csv      # optional
```

Export the recording in Pupil Player first (with the Raw Data Exporter enabled).

## Pupil

- **3D model** (`diameter_3d`, mm) when the export has 3D rows; otherwise the **2D** ellipse diameter (`diameter`,
  eye camera pixels). Older exports without 2D rows carry the pixel diameter in their 3D rows, which is used.
- Samples with confidence below **0.6** (Pupil Labs' recommendation) are dropped.
- `eye0` is the right eye, `eye1` the left. The two eyes are sampled independently, so both are averaged into bins
  on a common grid at their nominal rate.

Pixel diameters have no known scale: the pipeline scales them so the mean measured pupil equals the mean expected
pupil, as in the 2021 paper. The calibration fit is not available for pixel data.

## Gaze

`gaze_positions.csv` `norm_pos_x/y` (confidence ≥ 0.6), with y flipped to put the origin at the top left. Samples
more than 5 % outside the frame are dropped.

## Time

Time zero is the first scene frame; `epoch_start = start_time_system_s + (first frame − start_time_synced_s)`. Scene
frames are matched to gaze samples by their recorded timestamps, taking the **nearest** frame as Pupil Player does
(this reproduces Player's `world_index` for every sample of the test recording; a fixed frame rate was off by up to
24 frames because the camera drops frames).

## Scene camera

The field of view comes from `world.intrinsics` with a pinhole model (about 75° × 48.5° for the 1280×720 wide-angle
lens when the file is missing). It converts the gaze circle radius from degrees to pixels. The eye, however, adapts
to the whole binocular field, so the adapting field area uses 200° × 135° (Pignoni et al. 2021).

## Luminance

From the lux sensor worn on the tracker, distributed over the view with the scene video; see
[Luminance](../processing/luminance.md#lux-sensor-devices). Without lux logs the scene camera is used alone, with a
warning: its automatic exposure makes it only relative.

## Profile

| | |
|---|---|
| Pupil | mm (scale 1) or px (fitted) |
| Luminance | lux sensor |
| Field of view | from the camera matrix; adapting field 200° × 135° |
| Circular scene | no |
| Rate | measured (120 or 200 Hz) |

## Differences from 1.x

Version 1.x pooled both eyes' pixel diameters into one series; 2.0 keeps the eyes separate and prefers the 3D
diameter in mm ([open issue 30](../OPEN_ISSUES.md)). It also combines the lux sensor and the video as published in
the 2021 paper rather than 1.x's heuristic ([open issue 29](../OPEN_ISSUES.md)).
