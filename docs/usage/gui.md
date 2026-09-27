# Desktop app

Start it with `cwtool-gui`, optionally followed by a recording folder, or with `python -m cwtool.gui`.

## Layout

| Area | Contents |
|---|---|
| Left panel | Recording, Scene video, Calibration sequence and the parameter editors |
| Summary line | ΔPD RMS and SD, expected pupil at the display's black and white points (display devices) or "luminance from lux sensor", pupil scale and offset applied, sampling rates, share of the recording in gaps, and warnings in red |
| Plots | Measured vs expected pupil (top) and ΔPD (bottom), sharing the time axis |
| Video preview (dock) | The scene frame at the cursor with the analysis circles; toggle it in **View** |

## Menus

**File**

- **Open recording…**: choose a recording folder. The device is detected automatically.
- **Choose lux folder…**: the folder with lux sensor logs, for Pupil recordings whose logs are not in the recording
  folder or its `lux` subfolder. It applies to the recordings opened afterwards.
- **Load parameters… / Save parameters / Save parameters as…**: the participant's parameter file (JSON). Files
  written by version 1.x are converted when loaded.
- **Export results…**: CSVs, the parameters used and a PDF plot, into a folder of your choice
  (default `cwtool_export` inside the recording).

## Scene video

The video is analysed automatically when a recording is opened, unless a cached analysis made with the same
video, settings, frame timestamps and gaze exists. **Analyse video** runs it again (for example after changing the
video analysis settings), **Cancel** stops it.

## Parameters

Parameters are grouped as in [Parameters](../reference/parameters.md): Participant, Photometric calibration,
Pupil signal, Lux sensor, Dynamics, ΔPD. Every change re-runs the analysis from the cached video pass, so the
plots follow instantly.

The **Video analysis** group (gaze circle radius, scene circle, background, analysis width) changes what is
measured in the video: after editing it, click **Analyse video**. The video preview already draws the new
circles, so sizes can be checked before re-running.

## Plots

- Drag with the left mouse button to pan, use the wheel to zoom, right-click for the view menu (auto-range,
  export an image).
- A click places the red cursor, which moves the video preview; the cursor can also be dragged.
- The dashed blue lines are the expected pupil at the display's black and white points: the range the model can
  explain on that device.
- Events from the event log are shaded orange and labelled in the ΔPD plot.

## Calibration sequence

See [Participant calibration](calibration.md) for the procedure.

- **Load sequence… / Built-in**: the colour sequence to overlay: the built-in 20 steps or a CSV.
- **Find in recording**: locates the sequence in the analysed video and adapts its step length.
- **Show sequence overlay**: shades each step in its colour on the pupil plot; drag the grey line to move it.
- **Start**: the sequence start in seconds.
- **ΔPD RMS in sequence**: how well the model fits within the sequence, the value to minimise when calibrating
  by hand.
- **Fit latency, scale and offset**: the automatic fit of the participant's pupil parameters.

## Video preview

Shows the scene frame matched to the cursor time (by recorded frame timestamps where the device provides them),
the scene circle used as background on Varjo videos, the gaze circle, and the mean colour and luminance measured
in each. **◀ Frame / Frame ▶** step through frames.
