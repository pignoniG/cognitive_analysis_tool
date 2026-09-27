# Calibration fit

`cwtool/fit.py` and `cwtool/calibration.py`. Estimates a participant's pupil parameters from their calibration
sequence, given the photometric calibration. For the procedure, see
[Participant calibration](../usage/calibration.md).

## Locating the sequence

`calibration.locate` works on the video pass's gaze circle colour:

1. **Change points:** frames where any channel jumps by more than 8 code values, at least 0.3 s apart.
2. **Step length:** if the sequence's steps are all the same length, the median interval between change points
   gives the recording's step length, and a rescaled copy of the sequence is tried as well.
3. **Scoring:** every change point, aligned with every step start, is a candidate start. Within the candidate
   window the sequence's colours and the measured ones are compared in linear light, skipping the first half second
   of each step (the video changes a frame late). One gain per channel is fitted by least squares, because recorded
   levels are below nominal (on the Varjo sample grey 255 records as 253, red 255 as 231). The score is the
   relative RMS error.

The best candidate gives the start and, if rescaled, the new step timing.

## Fitted parameters

| Parameter | Range | Fitted as |
|---|---|---|
| latency (`delay`) | 0–1.5 s | grid search, then jointly with the time constants |
| dilation τ (`attack`) | 0.3–30 s | Nelder–Mead on log τ |
| constriction τ (`release`) | 0.05–5 s | Nelder–Mead on log τ |
| scale (`pupil_correction`) | ×0.5–2 | least squares, for each candidate dynamics |
| offset (`pupil_offset`) | – | least squares, for each candidate dynamics |

For candidate dynamics, the expected pupil is computed over the window (with 30 s of signal before it so the filter
has settled), and the scale \(k\) and offset \(b\) minimising \(\lVert k\,PD_\text{measured} + b - PD_\text{expected}\rVert\)
are solved directly. The cost is the remaining RMS.

Latency and constriction speed trade off against each other (a late fast response looks like an early slow one), so
they are fitted **jointly** rather than one after the other, from two starting points (constriction τ 0.3 s and
1 s), keeping the better. The fit uses the lightly smoothed pupil, which keeps the step edges that carry the latency.

## Guards and warnings

- A pupil that barely moves in the window (SD below 0.05 mm) cannot constrain the scale: only the offset is fitted.
- A fitted scale outside ×0.5–2 is implausible: the device scale is kept and only the offset is fitted.
- A latency or time constant ending on its search limit means the model does not match the pupil yet; the notes say
  to revisit the photometric calibration.
- Pixel data (Pupil Core 2D) is refused: its scale is not defined.

## Result

The fitted parameters are the input parameters with `delay`, `attack`, `release`, `dynamics` = on,
`pupil_correction` (multiplied by the fitted scale), `pupil_offset` and `alignment` = `fixed`. The ΔPD RMS in the
window before and after is reported. Saved with the participant's parameters, they apply unchanged to the
participant's other recordings.

On synthetic recordings the fit recovers latency, time constants, scale and offset closely (see
`tests/test_alignment_and_fit.py`).
