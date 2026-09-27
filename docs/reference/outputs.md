# Output files

## Export

Written by **File → Export results…** or `cwtool` (default folder `RECORDING/cwtool_export`). `<name>` is the
recording folder's name.

### `<name>_pupil.csv`

One row per analysis grid sample (default 100 Hz).

| Column | Unit | Content |
|---|---|---|
| `timestamp_unix` | s | Unix time |
| `timestamp_relative` | s | from the first scene frame |
| `luminance_cdm2` | cd/m² | estimated luminance |
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

Only when the recording has events.

| Column | Content |
|---|---|
| `event` | label |
| `start_relative`, `end_relative` | s |
| `mean_delta_pd_mm`, `mean_delta_pd_sd` | mean ΔPD within the event |

### `<name>_params.json`

The parameters used, loadable as a participant file.

### `<name>_plot.pdf`

Measured vs expected pupil and ΔPD (needs matplotlib; `--plot` on the command line).

## Video cache

Written next to the recording after the video pass.

- `cwtool_video.csv`: one row per analysed gaze sample: `time`, mean 8-bit colour of the gaze circle (`fix_r/g/b`)
  and background (`bg_r/g/b`), then linear means `<area>_lin<γ>_<channel>` for the gaze circle (`fix`), background
  (`bg`) and whole visible scene (`frame`) at each γ of the grid.
- `cwtool_video.json`: what the cache was made from: format version, gamma grid, video settings, video file name,
  a hash of the frame timestamps and a hash of the gaze samples. The cache is used only if all match.

Delete both files to force a new analysis, or use `--reanalyse` / **Analyse video**.
