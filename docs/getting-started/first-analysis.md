# First analysis

## 1. Prepare the recording folder

Each device has its own layout; the tool detects it from the files present.

- **Varjo XR-4:** the folder written by Varjo Base, with `varjo_gaze_output_*.csv` and `varjo_capture_*.mp4`.
- **Pupil Core:** the recording folder after exporting it in Pupil Player (it must contain `exports/<n>/`).
- **Pupil Neon:** a recording folder from a Pupil Cloud "Timeseries Data + Scene Video" download, or a native
  recording folder.

For the Pupil devices, put the lux sensor logs (`<month>_<day>_<hour>.csv`) in the recording folder or a `lux`
subfolder, or choose their folder when opening. Optionally add an `event_log` CSV from the
[event logger](../usage/tools.md#event-logger) to label the phases of the experiment.

## 2. Open it

```bash
cwtool-gui path/to/recording
```

or start `cwtool-gui` and use **File → Open recording…**. The recording panel shows the detected device, the
number of samples and, for Pupil devices, how many lux readings were found.

## 3. Analyse the scene video

The first time, the scene video is analysed in the background (a progress bar shows the video pass). The result
is cached next to the recording (`cwtool_video.csv`), so opening the recording again is instant. A 4-minute 4K
Varjo capture takes under a minute on a 4-core laptop.

## 4. Read the plots

- **Top:** measured pupil (black, grey = lightly smoothed) and expected pupil for the estimated luminance (blue).
- **Bottom:** ΔPD, measured minus expected. Positive values mean a pupil larger than light alone explains.
- Shaded orange regions are events from the event log; click on either plot to move the video preview to that
  moment.

Every parameter change on the right updates the plots immediately.

## 5. Calibrate and save the participant's parameters

For Varjo recordings, calibrate the display's photometric parameters and the participant's pupil response on the
calibration sequence (see [Participant calibration](../usage/calibration.md)), then **File → Save parameters**.
Load the same file for that participant's other recordings.

## 6. Export

**File → Export results…** writes the pupil, ΔPD and per-event CSVs plus the parameters used
(see [Output files](../reference/outputs.md)).

The same analysis without the GUI:

```bash
cwtool path/to/recording --params participant.json --plot
```
