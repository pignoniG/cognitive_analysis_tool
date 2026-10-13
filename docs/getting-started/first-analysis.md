# First analysis

## 1. Prepare the recording folder

Each device has its own layout; the tool detects it from the files present.

- **Varjo XR-4:** the folder written by Varjo Base, with `varjo_gaze_output_*.csv` and `varjo_capture_*.mp4`.
- **Pupil Core:** the recording folder after exporting it in Pupil Player (it must contain `exports/<n>/`).
- **Pupil Neon** (experimental): a recording folder from a Pupil Cloud "Timeseries Data + Scene Video" download, or
  a native recording folder.
- **Tobii Pro Glasses 3** (experimental): the recording folder from the SD card, with `recording.g3` and
  `gazedata.gz`.

For the glasses (Pupil Core, Neon, Glasses 3), put the lux sensor log (`lux.csv`, or the older `<month>_<day>_<hour>.csv`
files) in the recording folder or a `lux` subfolder, or point the app (**File → Logger folder…**) or `cwtool --logs` at the
sensor logger's recordings folder, where each session folder holds the lux log and the Shimmer and EmotiBit files: the
session of the recording is found by its time, the folder is remembered and nothing is copied into each recording. Optionally add an `event_log` CSV from the
[event logger](../usage/tools.md#event-logger) to label the phases of the experiment.

## 2. Open it

```bash
cwtool-gui path/to/recording
```

or start `cwtool-gui` and use **File → Open recording…**. The recording panel shows the detected device and the
number of samples. Under it, the **Set-up** checklist says what the recording still needs before its ΔPD can be trusted
(for glasses, whether the lux readings were found, which the Sensor data box also says), and each missing item is a
link to where it is done. **File → Open recent** lists the last recordings.

## 3. Analyse the scene video

The first time, the scene video is analysed in the background (a progress bar shows the video pass). The result
is cached next to the recording (`cwtool_video.csv`), so opening the recording again is instant. A 4-minute 4K
Varjo capture takes under a minute on a 4-core laptop.

## 4. Read the plots

- **Top:** measured pupil (black, grey = lightly smoothed) and expected pupil for the estimated luminance (green).
- **Bottom:** ΔPD (red), measured minus expected. Positive values mean a pupil larger than light alone explains.
- Shaded orange regions are events from the event log; click on either plot to move the video preview to that
  moment, or drag the red handle under the first plot.
- The plots under the buttons **Plots**, **Heart rate variability** and **Sensor signals** can be switched on and off.
  Drag to pan in time, press the magnifier to drag a rectangle to zoom to, right-click to zoom out, and the button with
  four arrows (or Ctrl+0) shows everything again. **Help → Gestures and shortcuts** lists them all.

Every parameter change in the side panel updates the plots immediately.

## 5. Calibrate and save the participant's parameters

For Varjo recordings, enter the display photometry once, then fit the participant's light sensitivity and pupil
response on the calibration sequence (see [Participant calibration](../usage/calibration.md)) and
**File → Save parameters**.
Load the same file for that participant's other recordings. **Revert** (Params tab) goes back to the saved values, and the
app asks before closing or opening another recording with parameters that were changed and not saved.

## 6. Export

**File → Export results…** (Ctrl+E) writes the pupil, ΔPD and per-event CSVs plus the parameters used
(see [Output files](../reference/outputs.md)). It runs in the background; the Export tab keeps a link to the folder. With
sensor data from the [sensor logger](../usage/logger.md), the Shimmer's heart rate variability can be previewed with
**Compute HRV** in the Data tab and goes into the package ([how it is computed](../processing/hrv.md)).

The same analysis without the GUI:

```bash
cwtool path/to/recording --params participant.json --plot
```
