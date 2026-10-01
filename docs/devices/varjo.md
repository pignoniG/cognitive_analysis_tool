# Varjo XR-4

Recordings from Varjo Base's eye tracking recorder. Reader: `cwtool/devices/varjo.py`. Checked against a Varjo
Base export from April 2026.

## Folder

```text
recording/
├── varjo_gaze_output_<date>.csv     # eye tracking, 200 Hz
├── varjo_capture_<date>.mp4         # capture of the left-eye view
└── <date>_event_log.csv             # optional, from tools/event_logger.py
```

## Gaze CSV

Columns are found by header name, falling back to the positions of the pilot study's export for files without a
header. Values written as `-nan(ind)` (Varjo Base on Windows) are read as missing.

| Used for | Column |
|---|---|
| time (video clock) | `relative_to_video_first_frame_timestamp` (ns) |
| Unix time | `relative_to_unix_epoch_timestamp` (ns) |
| validity | `status`, `left_status`, `right_status` (tracked when > 1; Varjo writes 0 = lost, 2 = tracked) |
| pupil | `left_pupil_diameter_in_mm`, `right_pupil_diameter_in_mm` |
| gaze | `gaze_projected_to_left_view_x/y` (default), or `left_projected_x/y`, `right_projected_x/y` |

A sample is valid only when all three statuses are tracked.

## Pupil scale

Older Varjo Base versions write the pupil **radius** in its diameter columns (confirmed by Varjo by email), so the
pupil scale is 2. Their iris diameter column reads a constant 6.04 mm, half a typical iris, which fits. A later
version (a September 2026 sample) writes real diameters: the iris column reads a constant 12.2–12.5 mm and the
pupil–iris ratio matches. The reader tells the two apart by the median iris diameter (above 9 mm: diameters, scale 1;
below, or unreadable: radii, scale 2), so each recording gets its own scale; the Recording box shows it. The calibration fits do not
estimate the pupil scale: one sequence does not determine it, and the dark-adapted pupil of a recording (6.4–7.7 mm in
the September 2026 sample) bounds it to about 0.9–1.2, so the device's scale is used. A participant correction
(`pupil_correction`) can be set by hand ([open issue 1](../OPEN_ISSUES.md)).

## Gaze

The capture shows the **left eye's view**. The combined gaze projected to that view is used by default; the left
eye's own projection is available (`gaze_eye="left"`), the right eye's is in the right view and so offset from the
capture. Projected coordinates run from −1 to 1 with y up and are converted to 0–1 with y down.

## Scene video

H.264 at a steady 30 fps; the gaze timestamps are relative to its first frame, so frames are matched by frame
rate. The scene is a circle with black corners: the background area is a centred circle (radius 0.8 of half the
frame height by default) to exclude them.

## Profile

| | |
|---|---|
| Pupil | mm, scale 2.0 (radius export) or 1.0 (diameter export, from the iris column) |
| Luminance | display: the scene capture's colours mapped through the [display photometry](../processing/luminance.md#display-devices), with the participant's light sensitivity |
| Field of view | 120° × 105° (nominal); the adapting field is the same |
| Circular scene | yes |
| Rate | 200 Hz |

## Calibration

Each participant watches the full-field calibration sequence in the headset; see
[Participant calibration](../usage/calibration.md). In the April 2026 sample the sequence used 10 s steps starting
16.4 s into the recording, and "Find in recording" located it in 0.2 s.
