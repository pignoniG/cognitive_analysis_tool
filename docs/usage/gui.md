# Desktop app

Start it with `cwtool-gui`, optionally followed by a recording folder, or with `python -m cwtool.gui`.

## Layout

| Area | Contents |
|---|---|
| Left panel | Recording, Scene video, Calibration sequence and the parameter editors |
| Summary line | ΔPD RMS and SD, expected pupil at the display's black and white points (display devices) or where the luminance comes from (lux sensor, or camera with fixed exposure), pupil scale and offset applied, sampling rates, share of the recording in gaps, and warnings in red |
| Plots | Measured vs expected pupil (top) and ΔPD (bottom), sharing the time axis |
| Video preview (dock) | The scene frame at the cursor with the analysis circles; toggle it in **View** |

## Menus

**File**

- **Open recording…**: choose a recording folder. The device is detected automatically.
- **Choose lux folder…**: the folder with lux sensor logs, for glasses recordings whose logs are not in the recording
  folder or its `lux` subfolder. It applies to the recordings opened afterwards.
- **Load parameters… / Save parameters / Save parameters as…**: the participant's parameter file (JSON), without
  the display photometry. Files written by version 1.x are converted when loaded.
- **Load display photometry… / Save display photometry…**: the headset's nominal Lmin, Lmax and gamma. The last
  file used with a device is loaded automatically with its recordings; the window title shows which one is in use.
- **Export results…**: CSVs, the parameters used and a PDF plot, into a folder of your choice
  (default `cwtool_export` inside the recording).

## Scene video

The video is analysed automatically when a recording is opened, unless a cached analysis made with the same
video, settings, frame timestamps and gaze exists. **Reanalyse video** (**Analyse video** before any analysis) runs
it again, for example after changing the video analysis settings; **Cancel**, shown while it runs, stops it.

**Video analysis settings** (drop-down under the buttons: gaze circle radius, scene circle, background, analysis
width) change what is measured in the video: after editing them, click **Reanalyse video**. The video preview
already draws the new circles, so sizes can be checked before re-running.

**Calibrate camera from lux** (glasses recordings with a lux log): measures the luminance that saturates a
fixed-exposure scene camera, for recordings of the same exposure without a lux log (see
[Luminance](../processing/luminance.md#calibrating-the-camera-from-a-lux-log)).

## Parameters

Parameters are grouped as in [Parameters](../reference/parameters.md): Participant, Display photometry, Participant
light response, Pupil signal, Lux sensor, Scene camera without lux log, ΔPD, with Dynamics in a drop-down under the
calibration controls and the video analysis settings in one under the scene video buttons. Every change re-runs the
analysis from the cached video pass, so the plots follow instantly.

Only the options that affect the loaded recording are shown (all of them before a recording is opened); hidden
options keep their values and are still saved in the parameter file:

| Recording | Hidden |
|---|---|
| Varjo | Lux sensor, Scene camera without lux log |
| Pupil Core / Neon / Glasses 3 with a lux log | Lmin, Lmax, Scene camera without lux log, Calibration sequence, scene circle radius |
| Pupil Core / Neon / Glasses 3 without a lux log | Lux sensor, Calibration sequence, scene circle radius; with camera exposure `auto` the camera full scale and exposure times, with `fixed` Lmin and Lmax |

Without a calibration sequence (glasses) the calibration box is titled **Pupil dynamics** and holds only the
Dynamics drop-down.

## Plots

- The view fits the data when a recording opens and follows it while you change parameters. Drag with the left
  mouse button to pan and use the wheel to zoom; after that the view stays where you put it.
- **Reset view** (button in the top right corner of the plots, **View** menu, Ctrl+0, or a double-click on the
  plots) shows all the data again: the whole recording and the range of the measured, expected and ΔPD curves. The calibration overlay, events and reference
  lines never stretch it.
- Right-click for pyqtgraph's view menu (e.g. export an image).
- The dark orange bar marks the current video frame; its time is shown at its top. Click on either plot to move it, or drag it to
  scrub the video: the preview follows while dragging, skipping frames if decoding cannot keep up. **◀ Frame / Frame ▶**
  in the preview move it frame by frame.
- The dashed green lines are the expected pupil at the display's black and white points: the range the model can
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
- **1. Fit light sensitivity**: the participant's light sensitivity and channel weights (optionally gamma), with a
  result window showing each step's steady-state pupil against the model.
- **2. Fit latency, scale and offset**: the participant's timing, pupil scale and offset, optionally with the
  transient constriction after brightening (pupillary escape).
- **Dynamics** (drop-down): the latency, always applied, and one switch for the rest: dilation and constriction time
  constants, constriction stages, transient and escape τ (greyed out while the switch is off).

## Video preview

Shows the scene frame matched to the cursor time (by recorded frame timestamps where the device provides them),
the scene circle used as background on Varjo videos (green), the gaze circle (orange), and the mean colour and luminance measured
in each. **◀ Frame / Frame ▶** step through frames.
