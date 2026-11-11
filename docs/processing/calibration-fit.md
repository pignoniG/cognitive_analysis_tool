# Calibration fit

`cwtool/calfit.py` (the fit the app and the command line use), `cwtool/calibration.py` (the sequence), and the earlier
step-level fits in `cwtool/photometry.py` and `cwtool/fit.py`. Estimates a participant's parameters from their calibration
sequence. For the procedure, see [Participant calibration](../usage/calibration.md).

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

## The fit on the time course

`calfit.fit_calibration`, for every device and every luminance route (a display such as the Varjo, glasses with a lux
sensor, a fixed-exposure camera, a camera mapped onto Lmin–Lmax).

**What is compared.** The expected pupil (Watson & Yellott at the luminance × the light sensitivity, delayed by the
latency, then through the dilation and constriction filter) against the measured pupil (lightly smoothed), sample by
sample over the sequence, on a 50 Hz grid that starts 30 s earlier so the filters have settled. The luminance is built
exactly as the analysis builds it for the recording's route, from the video's colours (and the lux sensor), so the fit
sees what the analysis sees.

**What is fitted, together.**

| Value | Display (Varjo) | Lux sensor, fixed-exposure camera |
|---|---|---|
| Light sensitivity | yes | yes |
| Red, green and blue weights | yes (a weak prior around 1, a relative balance with mean 1) | no |
| Pupil offset | no: the model's level is the sensitivity's | yes: the sensor's luminance is not absolute enough |
| Latency | from the constriction onsets at the brightening steps (at least 3), else fitted | same |
| Dilation (slow part) and constriction τ | with *Include the time constants* (default); the fast part of the dilation (60 %, 1 s) is held fixed | same |
| Transient and escape τ | only when asked | same |
| Gamma, the display's black | only when asked | — |
| Fixation weight | — | only when asked |

**Why on the time course.** The earlier fit took the level at the end of each step as its steady state, and fitted the
timing afterwards. A step that has not settled by its end, typically a black step after a bright one (the pupil dilates
with a time constant of several seconds), was then read as a level that is too small, and the sensitivity depended on how
the steps were cut: on the first Varjo run it went from 3.75 to 28 when the sequence moved by 0.34 s
([open issue 55](../OPEN_ISSUES.md)). On the time course a step that is still dilating is just part of the curve. On a
synthetic participant whose pupil dilates with τ 10 s on 10 s steps, the time course gives a sensitivity of 2.98 (true 3.0)
and τ 10.2 s, the step levels 3.75; moving the start by 0.3 s does not change the result.

**The display's values are effective.** The sensitivity multiplies the luminance and the colour weights the display's
primaries, so a dimmer headset and a less sensitive participant are the same fit, as are the display's primaries and the
eye's weighting. No photometry is needed for ΔPD; the nominal Lmin, Lmax and gamma are a starting point, and the fitted
values hold for this headset model and its settings. Compare sensitivities only between recordings made with the same
nominal values.

**Lower bounds and noise.** Samples at the tracker's ceiling ([Varjo](../devices/varjo.md)) only require the model to be
at least as large. Each sample counts as if there were about two independent ones per second, so the priors keep their
weight against a long sequence. The result gives approximate 95 % intervals from the curvature at the solution, the fit
error before and after (measured − expected with the best constant offset), the ΔPD RMS in the sequence from the whole
analysis, and notes: the latency and its onsets, anticipated constrictions, a weakly determined sensitivity, a value at the
end of its range, a poor correlation, the share at the ceiling.

**The transient is opt-in.** On the first Varjo run, with the transient free, it and a dilation τ at the end of its range
(28 s) explained the slow dilation after the black steps, and the session's ΔPD got worse (replicate blocks 0.41 mm apart,
against 0.26 mm without it). Asked for and found below 0.1 mm, it is left off and the rest fitted again.

The sections below describe the earlier fits (`photometry.fit_light_response`, `fit.fit_calibration`,
`photometry.fit_lux_response`). They remain in the library, for comparison, and are not used by the app.

## Light sensitivity (step levels, earlier)

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

**Level per step.** After the current latency, the level of each step is the mean of the lightly smoothed pupil over
its last 30 %. It is not extrapolated: on the seven Varjo calibration recordings the apparent trend at the end of a
step was as often a constriction as a dilation after brightening, i.e. mostly the pupil's own fluctuation, and
extrapolating it moved levels by 0.34 mm (median) and silently dropped a quarter of the steps
([open issue 40](../OPEN_ISSUES.md)). The one trend the physiology predicts is slow dilation after a darker step, which
can outlast a step: a step still dilating by more than 0.1 mm over its end after a darker one is flagged, its level
is short of the steady state, and half of that trend is added to its uncertainty. Each step's colour is its mean weighted gaze/background colour in the
video (after the first 0.5 s), so the fit sees the same, below-nominal levels as the analysis.

**Fit.** With the step luminances \(L_s\) from the display photometry and channel weights, the model is mapped onto
the measured steady states,

\[
A_s \approx WY(s \cdot L_s(g_R, g_G, g_B, \gamma, L_\text{min})) \; (+\, d)
\]

by weighted least squares (weights from each step's uncertainty, with a 0.1 mm floor for pupil fluctuations and model
error) over \(\log s\) and the log channel weights, and optionally \(\gamma\), \(\log L_\text{min}\) (white held at its nominal value) and an offset \(d\) (`fit_offset`, off by default; then \(b = -d\)). Residuals are in measured millimetres, at the pupil scale set by hand (`pupil_correction`): the scale is not fitted, because the sequence does not determine it (it trades off with the sensitivity and the black point, [open issues 1 and 36](../OPEN_ISSUES.md)). Weak priors keep poorly determined values near sensible ones: log weights around 0 (SD 1.5; wide, because
the pupil's colour weighting departs strongly from photopic luminance, blue in particular), \(\gamma\) around
2.2 (SD 0.2). The sensitivity has no prior, only its range (0.001–1000): a prior centred
on \(s = 1\) would mean "the display photometry is right", so it would pull the fit differently for different
datasheet values and break the exact trade-off between the two ([open issue 42](../OPEN_ISSUES.md)). Because the pupil
curve is S-shaped in log luminance, the fit starts from five sensitivities (0.03 to 30) and keeps the best. The weights are reported normalised to a mean of 1.

**Black level.** With *Also fit the black level* \(L_\text{min}\) is fitted within 0.0001–10 cd/m² while \(L_\text{max}\) stays at its nominal value; only \(s L_\text{min}\) and \(s L_\text{max}\) are determined, so holding the white fixes the scale of the pair. The notes report the contrast it implies against the nominal one. On the Varjo sample (8 s steps, black steps at 4.4 mm) it gives 0.21 cd/m² (481:1 against the datasheet's 10000:1), because the steps are too short to dark-adapt; with the nominal 0.01 the RMS is 0.76 mm instead of 0.66 (photopic weights).

**Sanity checks** (`luminance.display_notes`, also shown with every analysis): Lmax more than 10 % above the device's claimed peak luminance (Varjo: 200 cd/m²; it may be lower, since brightness is adjustable), Lmin not below Lmax, and a contrast below 100:1 are flagged ([open issue 48](../OPEN_ISSUES.md)).

**Uncertainty and warnings.** An approximate 95 % interval of \(s\) comes from the curvature at the solution. Notes
flag a wide interval (factor above 4), values at their limits, steps still dilating at their end, and skipped
steps.

**Synthetic check** (`tests/test_photometry.py`): a participant with sensitivity 3 and channel weights 1.5, 0.7, 0.8
on the 20-step staircase with 10 s steps, dilation τ 4 s and noise is recovered with weights within 2 % and the scale
within 1 %; the sensitivity comes out 4.0 (interval 2.2–7.4): dilation after the darker steps is not finished by their
end, so those steps read small, and the loosely determined sensitivity takes up the difference; doubling the datasheet luminance halves the fitted sensitivity exactly
and leaves the predictions unchanged.

**Real recording** (Varjo XR-4, April 2026, default display photometry): see
[open issue 36](../OPEN_ISSUES.md) for the results and what they say about sensitivity and pupil scale.

## Latency and offset (earlier)

`fit.fit_calibration`, run after the light sensitivity.

### Latency from constriction onsets

When the sequence is known (always, from the app), the latency is measured rather than fitted. At every clearly
brighter step, the video change is located and the constriction onset read the standard way: the line through the
points where the pupil has made 20 % and 50 % of its constriction, extended back to the level of the second before the
change. Only constrictions of at least 0.3 mm count, and at least three are needed; the median onset is held fixed,
and its interquartile range is reported. Onsets under 0.1 s are left out and counted in a note: a reflex cannot be that
fast (the shortest reported pupil latencies are about 0.2 s), and on the Varjo calibration recordings such onsets were
constrictions that started before the display changed, probably anticipating the regular steps
([open issue 41](../OPEN_ISSUES.md)).

The onset read this way is not quite the latency: the same construction applied to the model's own constriction
lands about 0.09 τ before its start with one constriction stage (which starts at full speed) and about 0.25 τ after
it with two (which start gradually). For each candidate constriction τ the latency is therefore set to the median
onset minus that bias, so `delay` is the time to the first movement of the pupil.

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
| offset (`pupil_offset`), optional (`fit_offset`) | – | least squares, for each candidate dynamics |

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

- A latency or time constant ending on its search limit means the model does not match the pupil yet; the notes say
  to revisit the light sensitivity fit.
- A transient below 0.1 mm (`fit.MIN_TRANSIENT`) means there is none: it is under the pupil's own fluctuation within
  a step, and the transients fitted on the Varjo calibration recordings were 0.35–1.7 mm. It is set to 0 and the other
  values are fitted again without it, since a spurious small transient also pulls the latency and time constants. A
  transient or escape τ at another limit
  usually means the participant shows little escape and the transient is only reshaping the constriction onset; the
  note suggests leaving it off.
- Pixel data (Pupil Core 2D) is refused: its scale is not defined.

### Result

The fitted parameters are the input parameters with `delay` (with `fit_offset`, also `pupil_offset` and `alignment` = `fixed`;
`pupil_correction` and by default the offset are left as they are), and with the dynamics `dynamics` = on, `attack`, `release`, `transient` and
`escape`. The app fits the transient whenever it fits the dynamics; `fit_calibration(..., fit_transient=False)` leaves
it out. The ΔPD RMS in the
window before and after is reported. Saved with the participant's parameters, they apply unchanged to the
participant's other recordings.

On synthetic recordings the fit recovers latency, time constants, transient and offset closely (see
`tests/test_alignment_and_fit.py`). On the seven Varjo calibration recordings the transient lowers the ΔPD RMS in the
sequence by 5–19 % and in the 4 s after brightening steps by 15–25 %; see [open issue 43](../OPEN_ISSUES.md).

## Glasses with a lux sensor (earlier)

`photometry.fit_lux_response`. Glasses have no display photometry, and their luminance comes from the lux sensor and
the scene video (see [Luminance](luminance.md#lux-sensor-devices)), so the display fit above does not apply. What is
fitted is smaller: a **light sensitivity** \(s\) multiplying the luminance entering the model, and the pupil
**offset** \(d\), by least squares on ΔPD over the sequence,

\[
\min_{s,d} \sum_t \big( PD_\text{measured}(t) + d - PD_\text{expected}(s \cdot L(t)) \big)^2 .
\]

The luminance \(L\) is what the analysis builds with the current parameters, and the expected pupil includes the
current latency and dynamics. For each \(s\) the best offset is the mean of expected − measured, so only \(s\)
is searched: a grid over 0.001–1000, then a bounded refinement. The interval of \(s\) comes from the curvature of the
cost, with about two independent samples per second. The pupil scale is the device's (millimetres) and is not fitted:
with the luminance uncertain, scale and sensitivity cannot be told apart on one sequence ([open issue 36](../OPEN_ISSUES.md)).
Pixel data is refused, as above.

Apply sets `sensitivity`, `pupil_offset` and `alignment` = `fixed`. The RMS before is the current sensitivity with its
best offset, so the improvement shown is the sensitivity's alone; with the offset free, the sensitivity often improves
the fit little. Notes say when the expected pupil barely varies over the window (the sensor saw no change), when it
follows the measured one poorly (correlation below 0.3), when the sensitivity is at its limit or weakly determined,
and when fewer than four steps have data.

**Fixation weight (optional).** With *Also fit the fixation weight* (`fit_fixation=True`) the gaze circle's share of
the weighted colour, `fixation_weight` ([open issue 47](../OPEN_ISSUES.md)), is fitted too, within 0.05–1: eight values
first, each with its own sensitivity search, then a bounded refinement around the best. It changes the luminance
\(L = \bar L \cdot Y_w / Y_\text{frame}\), so it needs the video route and a scene where the gaze area and the
background differ (a screen in a room): a full-field calibration on a display cannot determine it. The notes say when
the cost hardly changes across the weights (below 2 %), when the weight is at a limit, and that one recording is not
enough to rely on it. Apply then also sets `fixation_weight`.

Fit on a segment where light drives the pupil, such as the calibration sequence or a rest period; a fit over a
whole task recording would absorb the workload signal it is meant to leave in ΔPD. On the 30 September 2026 Pupil Core
recording (81 s of the sequence, ten steps, laptop screen) it gives a sensitivity of 0.08 with an interval of
0.02–0.37, ΔPD RMS 0.74 → 0.72 mm and a correlation of 0.51, and says the sensitivity is weakly determined. With the
fixation weight fitted it goes to 1 (the gaze area alone), with a sensitivity of about 2, RMS 0.67 mm and a
correlation of 0.59.
