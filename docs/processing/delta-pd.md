# ΔPD and alignment

`pipeline.run`. Comparing the measured pupil with the expected one.

## Offset

The model predicts the pupil of an average observer, so the measured pupil is shifted onto it. `alignment` sets how
the offset is chosen:

| Mode | Offset | Use |
|---|---|---|
| `recording` | median of expected − measured over the whole recording | default, as in 1.x; ΔPD is centred on zero |
| `baseline` | the same median, over the events named in `baseline_events` (default "Riposo, Rest, Baseline") | ΔPD relative to rest phases; falls back to the whole recording with a warning if none are found |
| `fixed` | `pupil_offset` | the value fitted on the participant's calibration sequence, applied unchanged |
| `none` | 0 | absolute comparison |

Only valid samples (outside long gaps) enter the median.

## ΔPD

\[
\Delta PD = PD_\text{measured} + \text{offset} - PD_\text{expected}
\]

averaged over consecutive windows of `cw_window` (0.2 s), ignoring missing samples, then smoothed with a first-order
Savitzky–Golay filter over `cw_smoothing` windows on each side (1: three windows). Windows without valid samples stay
empty.

## Statistics

| Value | Meaning |
|---|---|
| ΔPD RMS | root mean square of ΔPD about zero: how far the pupil strays from the model overall |
| ΔPD SD | standard deviation of ΔPD: its spread around its own mean |
| ΔPD in SD units | ΔPD / SD, exported next to ΔPD in mm |
| Light left in ΔPD | how much of ΔPD the luminance still explains: the slope of ΔPD on log₁₀ luminance (mm per tenfold luminance) and the R² of ΔPD on log₁₀ luminance and its recent change. Shown in the summary; a warning above R² 0.1 |

The light left in ΔPD is the first check of a result: if the model removed the light, ΔPD does not follow the
luminance, and both figures are near 0. A large value means ΔPD changes where the light changes may not be workload.
It cannot tell model error from a task that itself follows the light (a bright task screen and a dark rest screen):
there, judge it on a recording, or a part, where the light varies and the task does not.

Absolute ΔPD in mm depends on the light sensitivity, the display photometry and the offset. Reporting changes relative to a baseline,
or in SD units, compares better across participants; Eckert et al. (2022) reach the same conclusion for
PLR-corrected pupil sizes.

## Events

For each event, the mean ΔPD inside it (in mm and SD units) is written to the events CSV. Events come from the
`event_log` CSV and, for the Neon and the Glasses 3, from the recording's own events.
