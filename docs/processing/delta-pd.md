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

Absolute ΔPD in mm depends on the photometric calibration and the offset. Reporting changes relative to a baseline,
or in SD units, compares better across participants (see [open issue 28](../OPEN_ISSUES.md)).

## Events

For each event, the mean ΔPD inside it (in mm and SD units) is written to the events CSV. Events come from the
`event_log` CSV or, for the Neon, from the recording's own events.
