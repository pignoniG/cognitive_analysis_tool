# Calibration fit

`cwtool/photometry.py`, `cwtool/fit.py` and `cwtool/calibration.py`. Estimates a participant's parameters from
their calibration sequence, given the display photometry. For the procedure, see
[Participant calibration](../usage/calibration.md).

## Locating the sequence

`calibration.locate` works on the video pass's gaze circle colour:

1. **Change points:** frames where any channel jumps by more than 8 code values, at least 0.3 s apart.
2. **Step length:** if the sequence's steps are all the same length, the median interval between change points
   gives the recording's step length, and a rescaled copy of the sequence is tried as well.
3. **Scoring:** every change point, aligned with every step start, is a candidate start. A candidate must lie within
   the recording, give or take its first and last step (which may have begun before the recording or been cut
   short). Within the candidate window the sequence's colours and the measured ones are compared in linear light,
   skipping the first half second of each step (the video changes a frame late). Only times with analysed video are
   compared: the video is analysed at valid gaze samples, so tracking gaps have no colour, and at least half of the
   window must have one. One gain per channel is fitted by least squares, because recorded levels are below nominal
   (on the Varjo sample grey 255 records as 253, red 255 as 231). The score is the relative RMS error.

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

**Steady state per step.** After the current latency, the lightly smoothed pupil of each step is examined. If its
last 30 % is flat (change below 0.1 mm), the mean of that part is the steady state. Otherwise the pupil is still
moving: dilation can take longer than a step to settle, and after a brightening step the pupil often constricts and
then re-dilates slowly ("pupillary escape"). An exponential \(y = A + (y_0 - A)\,e^{-(t - t_0)/\tau}\) is then fitted
from the turning point (the extreme value before the final trend) to the end, and its asymptote \(A\) is used, limited
to 1 mm beyond the last second in the direction of the trend. Half the extrapolated distance is added to the step's
uncertainty, so extrapolated steps count less. Each step's colour is its mean weighted gaze/background colour in the
video (after the first 0.5 s), so the fit sees the same, below-nominal levels as the analysis.

**Fit.** With the step luminances \(L_s\) from the display photometry and channel weights, the model is mapped onto
the measured steady states,

\[
A_s \approx c \cdot WY(s \cdot L_s(g_R, g_G, g_B, \gamma)) + d
\]

by weighted least squares (weights from each step's uncertainty, with a 0.1 mm floor for pupil fluctuations and model
error) over \(\log s\), the log channel weights, \(\log c\) and \(d\), and optionally \(\gamma\). The pupil scale
correction is \(k = 1/c\) and the offset \(b = -d/c\). Residuals are in measured millimetres on purpose: written the
other way round (\(k A_s + b \approx WY\)), a fit can shrink its residuals by compressing both the model's range (an
extreme sensitivity putting every step at the smallest pupil) and the scale, which is what happened on the first real
recording. Weak priors keep poorly determined values near sensible ones: \(\log s\) around 0 (SD \(\log 10\)), log
weights around 0 (SD 1.5; wide, because the pupil's colour weighting departs strongly from photopic luminance, blue
in particular), \(\log c\) around 0 (SD 0.25), \(\gamma\) around 2.2 (SD 0.2). Because the pupil curve is S-shaped in log luminance, the fit
starts from five sensitivities (0.03 to 30) and keeps the best. The weights are reported normalised to a mean of 1.

**Uncertainty and warnings.** An approximate 95 % interval of \(s\) comes from the curvature at the solution. Notes
flag a wide interval (factor above 4), values at their limits, more than a third of the steps unsettled, and
skipped steps.

**Synthetic check** (`tests/test_photometry.py`): a participant with sensitivity 3 and channel weights 1.5, 0.7, 0.8
on the built-in sequence with 10 s steps, dilation τ 4 s and noise is recovered as sensitivity 2.7 (interval
1.0–7.5), weights within 5 %, scale within 5 %; doubling the datasheet luminance halves the fitted sensitivity and
leaves the predictions unchanged.

**Real recording** (Varjo XR-4, April 2026, default display photometry): see
[open issue 36](../OPEN_ISSUES.md) for the results and what they say about sensitivity and pupil scale.

## Latency, scale and offset

`fit.fit_calibration`, run after the light sensitivity.

### Latency from constriction onsets

When the sequence is known (always, from the app), the latency is measured rather than fitted. At every clearly
brighter step, the video change is located and the constriction onset read the standard way: the line through the
points where the pupil has made 20 % and 50 % of its constriction, extended back to the level of the second before the
change. Only constrictions of at least 0.3 mm count, and at least three are needed; the median is used and held fixed,
and its interquartile range is reported.

Fitting the latency together with the rest does not work on real data: the fit error barely depends on it (on the
April 2026 recording, 0.145 mm at 0 s against 0.152 mm at 0.4 s), so small mismatches in the response's shape, such
as re-dilation after a constriction, which the model does not describe, drive it to 0 s. Measured onsets on the same
recording give 0.32 s (interquartile range 0.27–0.34 s over 10 steps). Without a sequence, or with fewer than three
onsets, the latency is fitted as below.

### Fitted parameters

| Parameter | Range | Fitted as |
|---|---|---|
| latency (`delay`) | 0–1.5 s | grid search, then jointly with the time constants |
| dilation τ (`attack`) | 0.3–30 s | Nelder–Mead on log τ |
| constriction τ (`release`) | 0.05–5 s | Nelder–Mead on log τ |
| transient (`transient`), optional | 0.01–3 mm | Nelder–Mead on log, with the time constants |
| escape τ (`escape`), optional | 0.3–30 s | Nelder–Mead on log τ, with the time constants |
| scale (`pupil_correction`) | ×0.5–2 | least squares, for each candidate dynamics |
| offset (`pupil_offset`) | – | least squares, for each candidate dynamics |

For candidate dynamics, the expected pupil is computed over the window (with 30 s of signal before it so the filter
has settled), and mapped onto the measured pupil by least squares, \(PD_\text{measured} \approx c\,PD_\text{expected} + d\),
giving the scale \(k = 1/c\) and offset \(b = -d/c\). The cost is the remaining RMS, in measured millimetres. The
regression runs this way because the measurement is the noisy side: regressing the model on the measurement would pull
\(k\) towards zero whenever the pupil varies in ways the model does not (on the April 2026 recording it gave 0.40
instead of 0.62).

Without measured onsets, latency and constriction speed trade off against each other (a late fast response looks like
an early slow one), so they are fitted **jointly** rather than one after the other, from two starting points (constriction τ 0.3 s and
1 s), keeping the better. The fit uses the lightly smoothed pupil, which keeps the step edges that carry the latency.

### Guards and warnings

- A pupil that barely moves in the window (SD below 0.05 mm) cannot constrain the scale: only the offset is fitted.
- A fitted scale outside ×0.5–2 is implausible: the device scale is kept and only the offset is fitted.
- A latency or time constant ending on its search limit means the model does not match the pupil yet; the notes say
  to revisit the light sensitivity fit.
- A transient at its lower limit means there is none: it is set to 0. A transient or escape τ at another limit
  usually means the participant shows little escape and the transient is only reshaping the constriction onset; the
  note suggests leaving it off.
- Pixel data (Pupil Core 2D) is refused: its scale is not defined.

### Result

The fitted parameters are the input parameters with `delay`, `attack`, `release`, `dynamics` = on, `transient` and
`escape` (with the transient option), `pupil_correction` (multiplied by the fitted scale), `pupil_offset` and
`alignment` = `fixed`. The ΔPD RMS in the
window before and after is reported. Saved with the participant's parameters, they apply unchanged to the
participant's other recordings.

On synthetic recordings the fit recovers latency, time constants, transient, scale and offset closely (see
`tests/test_alignment_and_fit.py`). On the seven Varjo calibration recordings the transient lowers the ΔPD RMS in the
sequence by 5–19 % and in the 4 s after brightening steps by 15–25 %; see [open issue 43](../OPEN_ISSUES.md).
