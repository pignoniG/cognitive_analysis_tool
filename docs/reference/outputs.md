# Output files

## Export

Written by **File → Export results…** or `cwtool` (default folder `RECORDING/cwtool_export`) as one package: every
file below is cut to the same [export range](../usage/gui.md#export-range) and sensor files from the
[sensor logger](../usage/logger.md) go in with the results. `<name>` is the recording folder's name.

A **trim** (start, end, left-out segments) removes rows from every file by their time: a row is kept when its time is
at or after the start, at or before the end, and not inside a left-out segment (a segment includes its start and not
its end). The analysis itself always uses the whole recording.

!!! note "ΔPD in SD units after trimming"
    `delta_pd_sd` is ΔPD divided by the SD of ΔPD over the recording. With a trim it is divided by the SD of the
    ΔPD that is kept, so the values do not depend on what was left out. `<name>_export.json` says which was used.

### `<name>_pupil.csv`

One row per analysis grid sample (default 100 Hz).

| Column | Unit | Content |
|---|---|---|
| `timestamp_unix` | s | Unix time |
| `timestamp_relative` | s | from the first scene frame |
| `luminance_cdm2` | cd/m² | estimated luminance (only relative for a glasses recording without lux log and with automatic exposure) |
| `pupil_measured_mm` | mm | measured pupil, smoothed, scaled and offset; empty in long gaps |
| `pupil_measured_raw_mm` | mm | the same, lightly smoothed |
| `pupil_expected_mm` | mm | expected pupil |

### `<name>_cw.csv`

One row per ΔPD window (default 0.2 s).

| Column | Unit | Content |
|---|---|---|
| `timestamp_unix`, `timestamp_relative` | s | window centre |
| `delta_pd_mm` | mm | ΔPD |
| `delta_pd_sd` | SD | ΔPD / SD of ΔPD over the recording |

### `<name>_events.csv`

Only when the recording has events (and, with a trim, events with some of their time kept). An event is clipped to
the start and end, and its mean ΔPD is taken over the ΔPD windows that are kept; an event that is left out entirely
is not listed.

| Column | Content |
|---|---|
| `event` | label |
| `start_relative`, `end_relative` | s |
| `mean_delta_pd_mm`, `mean_delta_pd_sd` | mean ΔPD within the event |

### `<name>_lux.csv`

Only with a lux log: `timestamp_unix`, `timestamp_relative`, `lux` (the readings as logged), within the recording.

### `<name>_<sensor>.csv`

One file for each imported sensor file (`<name>_shimmer.csv`, `<name>_emotibit.csv`), within the recording and the
export range. The first two columns are `timestamp_unix` and `timestamp_relative` (the same axis as the files above);
the rest are the logger file's own columns, raw as logged: the Shimmer's channels in ADC counts plus its
`device time (s)`, or the EmotiBit's `signal` and `value`. See [Sensor logger](../usage/logger.md#what-is-saved).

### `<name>_params.json`

The parameters used, loadable as a participant file.

### `<name>_export.json`

What the package holds, for whoever receives it: the recording and device, the meaning of the time columns and the
Unix time of time zero, the trim (or `null`), the seconds kept, which SD was used for `delta_pd_sd` and its value, each
sensor file with its source, columns and row count, the list of files and the version of `cwtool`.

### `<name>_plot.pdf`

Measured vs expected pupil and ΔPD (needs matplotlib; `--plot` on the command line). The parts the trim leaves
out are shaded grey.

## Video cache

Written next to the recording after the video pass.

- `cwtool_video.csv`: one row per analysed gaze sample: `time`, mean 8-bit colour of the gaze circle (`fix_r/g/b`)
  and background (`bg_r/g/b`), then linear means `<area>_lin<γ>_<channel>` for the gaze circle (`fix`), background
  (`bg`) and whole visible scene (`frame`) at each γ of the grid.
- `cwtool_video.json`: what the cache was made from: format version, gamma grid, video settings, video file name,
  a hash of the frame timestamps and a hash of the gaze samples. The cache is used only if all match.

Delete both files to force a new analysis, or use `--reanalyse` / **Analyse video**.
