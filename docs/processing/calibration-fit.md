# Calibration fit

`cwtool/photometry.py`, `cwtool/fit.py` and `cwtool/calibration.py`. Estimates a participant's parameters from
their calibration sequence, given the display photometry. For the procedure, see
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

## Light sensitivity

`photometry.fit_light_response`.

**What can be determined.** Watson & Yellott depend on luminance only through the product luminance × field area, so
scaling Lmin and Lmax together is indistinguishable from a participant whose pupil is more or less sensitive to
light. With the pupil scale also unknown (Varjo), one sequence cannot separate the display's brightness from the
participant's sensitivity. The display photometry is therefore taken as given (the user's nominal values), and one
**light sensitivity** factor \(s\) per participant multiplies the luminance entering the model:

\[
PD = WY(s \cdot L)
\]

Any error of the display photometry common to all participants is absorbed by \(s\).

**Steady state per step.** For each step, after the current latency, an exponential
\(y = A + (y_0 - A)\,e^{-(t - t_0)/\tau}\) is fitted to the lightly smoothed pupil, and its asymptote \(A\) with its
standard error is the step's steady state. Dilation can take longer than a step to settle (τ about 5 s on the April
2026 sample), so a plain average of the step's end would be biased; steps with τ above a third of the step are
marked as not settled. Each step's colour is its mean weighted gaze/background colour in the video (after the first
0.5 s), so the fit sees the same, below-nominal levels as the analysis.

**Fit.** With the step luminances \(L_s\) from the display photometry and channel weights,

\[
k \cdot A_s + b \approx WY(s \cdot L_s(g_R, g_G, g_B, \gamma))
\]

is solved by weighted least squares (weights from each step's uncertainty, with a 0.05 mm floor) over \(\log s\),
the log channel weights, the scale \(k\) and offset \(b\), and optionally \(\gamma\). Weak priors keep poorly
determined values near sensible ones: \(\log s\) around 0 (SD \(\log 10\)), log weights around 0 (SD 0.5), \(k\)
around 1 (SD 0.25), \(\gamma\) around 2.2 (SD 0.2). Because the pupil curve is S-shaped in log luminance, the fit
starts from five sensitivities (0.03 to 30) and keeps the best. The weights are reported normalised to a mean of 1.

**Uncertainty and warnings.** An approximate 95 % interval of \(s\) comes from the curvature at the solution. Notes
flag a wide interval (factor above 4), values at their limits, more than a third of the steps unsettled, and
skipped steps.

**Synthetic check** (`tests/test_photometry.py`): a participant with sensitivity 3 and channel weights 1.5, 0.7, 0.8
on the built-in sequence with 10 s steps, dilation τ 4 s and noise is recovered as sensitivity 2.8 (interval
1.7–4.5), weights within 4 %, scale within 3 %; doubling the datasheet luminance halves the fitted sensitivity and
leaves the predictions unchanged.

## Latency, scale and offset

`fit.fit_calibration`, run after the light sensitivity.

### Fitted parameters

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

### Guards and warnings

- A pupil that barely moves in the window (SD below 0.05 mm) cannot constrain the scale: only the offset is fitted.
- A fitted scale outside ×0.5–2 is implausible: the device scale is kept and only the offset is fitted.
- A latency or time constant ending on its search limit means the model does not match the pupil yet; the notes say
  to revisit the light sensitivity fit.
- Pixel data (Pupil Core 2D) is refused: its scale is not defined.

### Result

The fitted parameters are the input parameters with `delay`, `attack`, `release`, `dynamics` = on,
`pupil_correction` (multiplied by the fitted scale), `pupil_offset` and `alignment` = `fixed`. The ΔPD RMS in the
window before and after is reported. Saved with the participant's parameters, they apply unchanged to the
participant's other recordings.

On synthetic recordings the fit recovers latency, time constants, scale and offset closely (see
`tests/test_alignment_and_fit.py`).
