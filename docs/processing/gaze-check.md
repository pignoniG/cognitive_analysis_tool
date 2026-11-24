# Gaze check

The pupil model takes the luminance where the participant looked, so the gaze has to land on the right place of the scene
video. A headset's capture and glasses' scene camera are mapped to the gaze differently by each device, and the mapping can be
off: a Neon inside a Meta Quest is fixed to the headset but not aligned with its view
([open issue 61](../OPEN_ISSUES.md)). The calibration therefore opens with a gaze check, and cwtool compares it with the gaze.

## In the presenters

The [calibration presenter](../usage/calibration-tool.md#gaze-check) and the validation task's calibration open, right after the lead-in,
with a short tone, 1 s of lead-in grey, then a dot with a white centre moving through 9 places on that grey, 3 s each by default, the centre first. In VR the places are
directions fixed to the head (±15° × ±12°), so they sit at fixed places of the headset's picture and of its capture. The run
file logs the tone's row (`phase` = `gaze`, no target) and each place (`phase` = `gaze`, `target_*`); the light steps follow.
Until November 2026 the gaze check closed the calibration; cwtool reads either order (the light sequence and its start
leave the gaze rows out).

## In cwtool

When the recording's folder (or its scene video's) holds a run file with a gaze check, after the log alignment
(`cwtool.gazecheck.check`):

1. **The windows.** Each place from 0.6 s after its onset (the saccade and the settling) to 0.2 s before the next, on the
   recording's clock through the run file's Unix times.
2. **The dot.** Six frames of each window are averaged (grey, 320 px wide). The median of the nine averages is the background,
   since the dot is elsewhere in each; the dot is the strongest blob of a place's difference from it (blurred to the dot's size,
   its weighted centre above half the peak). A blob weaker than 6 robust noise units is not taken: the place is left out and
   said.
3. **The gaze.** The median of the tracker's gaze in the window (at least 20 samples), and its spread.
4. **The offset.** Each place's difference, dot minus gaze, as an angle through the video's projection (a tracker turned
   on the head, or in a headset, moves the gaze by the same angle everywhere); their median is the offset that moves the gaze
   onto the dots. **In VR** the run file gives each place's direction from the head, so the gaze is compared with those
   directions instead, in the head's degrees: no assumed field of view enters, and a place whose dot is not found in the video
   still counts. Reported with the median error before and after moving the gaze by it, and the places' spread around it:
   more than 2° means one shift does not fit them all (the mapping is off by more than a shift). At least 3 places are needed.

5. **The video's projection (VR).** The dots found sit at known directions, so they measure where the head's directions fall
   in the video: a pinhole's centre and focal length on each axis, fitted to the dots (at least 5, spanning both axes, within
   1 % of the width). On 23 November 2026 a Quest capture over Link fitted to within 1 px: 79° × 50°, the head's straight ahead
   at (0.510, 0.389), not the 110° × 78° centred that had been assumed. When it differs from the projection in use, the
   summary says so.

The result is shown under the scene video line in the Data tab (green, or red when the median error is over 2° or there is no
offset), printed by `cwtool RECORDING`, and written to `<name>_export.json` under `gaze check`, with each place.

## The session's gaze offset

The check does not move the gaze; the operator does, **per session**: how a tracker sits on the head, or a Neon in a headset
frame, changes from one session to the next, so the offset is saved with the recording (`cwtool_gaze_offset.json` in its
folder, as the trim is) and not with the participant's parameters.

- **In the gaze correction window** (opened before the video is analysed when the run file has a gaze check, and from
  *Gaze correction…*): the scene video with the gaze and the places, the offset redrawn live with each place's error
  left; *Confirm and analyse* saves it, marked confirmed, so the recording is not asked about again (a confirmed zero
  is kept too). See [the app](../usage/gui.md#scene-video).
- **In the side panel:** under the scene video, the offset applied and whether it was confirmed, and *Gaze correction…*
  to open the window again.
- **On the command line:** the saved offset is applied; `--gaze-offset RIGHT DOWN` uses another one for that run (`0 0`:
  none), `--save-gaze-offset` saves it (or, without it, the check's proposed total, applied from the next run).
- **The projection** of a headset's capture, when the check measured one that differs: the window draws the gaze through
  it and *Confirm and analyse* saves it too (`cwtool_capture_projection.json`); on the command line `--save-projection`.
  The gaze is placed through it when the recording is read.

The gaze is moved by the angle, through the video's projection, so the same offset is the same angle anywhere in the
picture. The export records it under `gaze offset (deg, right, down)`, and every result carries a note saying it was applied.

## When it works

The dot must be the only thing that changes between the places: a head-fixed dot in a headset's capture, or a monitor seen by
glasses' scene camera with the head still. A head that moves shifts the background and lowers the dots' contrast; those places
are left out. Tested on synthetic videos and on one Quest recording over Link (23 November 2026: 9 of 9 dots found, gaze 2.8°
off the directions, 0.7° after the offset).

The gaze check also places the pupil in time when the video has a clock of its own (a Quest capture): the gaze's saccades to
the dots give the difference between the presenter's computer's clock and the tracker's ([log alignment](log-alignment.md)).
