# Gaze check

The pupil model takes the luminance where the participant looked, so the gaze has to land on the right place of the scene
video. A headset's capture and glasses' scene camera are mapped to the gaze differently by each device, and the mapping can be
off: a Neon inside a Meta Quest is fixed to the headset but not aligned with its view
([open issue 61](../OPEN_ISSUES.md)). The calibration therefore ends with a gaze check, and cwtool compares it with the gaze.

## In the presenters

The [calibration presenter](../usage/calibration-tool.md#gaze-check) and the validation task's calibration end with a short tone, 1 s
of lead-in grey, then a dot with a white centre moving through 9 places on that grey, 3 s each by default, the centre first. In VR the places are
directions fixed to the head (±15° × ±12°), so they sit at fixed places of the headset's picture and of its capture. The run
file logs the tone's row (`phase` = `gaze`, no target) and each place (`phase` = `gaze`, `target_*`).

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
4. **The offset.** Each place's difference, dot minus gaze, as an angle through the device's field of view (a tracker turned
   on the head, or in a headset, moves the gaze by the same angle everywhere); their median is the offset that moves the gaze
   onto the dots. Reported with the median error before and after moving the gaze by it, and the places' spread around it:
   more than 2° means one shift does not fit them all (the mapping is off by more than a shift). At least 3 places are needed.

The result is shown under the scene video line in the Data tab (green, or red when the median error is over 2° or there is no
offset), printed by `cwtool RECORDING`, and written to `<name>_export.json` under `gaze check`, with each place.

## The session's gaze offset

The check does not move the gaze; the operator does, **per session**: how a tracker sits on the head, or a Neon in a headset
frame, changes from one session to the next, so the offset is saved with the recording (`cwtool_gaze_offset.json` in its
folder, as the trim is) and not with the participant's parameters.

- **In the window:** *Gaze offset (this session)* under the scene video, in degrees right and down. *From gaze check* fills in
  the offset the check found, added to the one already applied; the values can be changed by hand. *Apply* saves them and
  reads the recording again: the gaze is moved when the recording is read, so the video is analysed again with it, and the
  check then reports what is left ("with the session's offset ... applied").
- **On the command line:** the saved offset is applied; `--gaze-offset RIGHT DOWN` uses another one for that run (`0 0`:
  none), `--save-gaze-offset` saves it (or, without it, the check's proposed total, applied from the next run).

The gaze is moved by the angle, through the device's field of view, so the same offset is the same angle anywhere in the
picture. The export records it under `gaze offset (deg, right, down)`, and every result carries a note saying it was applied.

## When it works

The dot must be the only thing that changes between the places: a head-fixed dot in a headset's capture, or a monitor seen by
glasses' scene camera with the head still. A head that moves shifts the background and lowers the dots' contrast; those places
are left out. Tested on synthetic videos only so far.
