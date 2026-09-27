# Expected pupil model

`cwtool/model.py`, `pipeline.expected_pupil`. The pupil diameter light alone would produce, in three stages.

## 1. Watson & Yellott (2012)

The unified formula for the light-adapted pupil. The corneal flux density is luminance × adapting field area ×
the monocular attenuation:

\[
F = L \cdot a \cdot M(e), \qquad M(2) = 1,\; M(1) = 0.1
\]

with \(a\) the adapting field area in deg² (from the device profile, treating the field as an ellipse) and \(e\)
the number of eyes adapted (`eyes`). The Stanley & Davies (1995) diameter is

\[
D_{SD} = 7.75 - 5.75 \, \frac{(F/846)^{0.41}}{(F/846)^{0.41} + 2}
\]

corrected for age \(y\) against the reference age \(y_0\) (`age`, `reference_age`, default 28.58):

\[
D = D_{SD} + (y - y_0)(0.02132 - 0.009562\, D_{SD})
\]

Because \(F\) depends only on \(L \cdot a\), changing the field area is equivalent to rescaling
\(L_\text{min}\) and \(L_\text{max}\). This is how parameter files from 1.x, which used the field as a free value,
are converted exactly.

| Device | Adapting field | Area |
|---|---|---|
| Varjo XR-4 | 120° × 105° (display) | 9 896 deg² |
| Pupil Core, Neon | 200° × 135° (binocular visual field) | 21 206 deg² |

## 2. Latency

The expected pupil is delayed by `delay` (default 0.5 s), the pupil's response latency. It is always applied, and
fitted per participant by the [calibration fit](calibration-fit.md).

## 3. Dynamics (optional)

With `dynamics` on, a one-pole filter with different time constants for the two directions:

\[
y_n = \alpha\, y_{n-1} + (1 - \alpha)\, x_n, \qquad \alpha = e^{-1/(f_s \tau)}
\]

\[
\tau = \begin{cases}\tau_\text{attack} & \text{if } x_n > y_{n-1} \text{ (dilation)} \\ \tau_\text{release} & \text{otherwise (constriction)}\end{cases}
\]

Dilation is slow (`attack`, default 6 s) and constriction fast (`release`, default 0.5 s). The filter acts on the
expected diameter after the formula and starts from the first value.

## Display range

For display devices the expected pupil at \(L_\text{min}\) and \(L_\text{max}\) is shown as the dashed black and
white point lines: the range of pupil sizes the display can explain for this participant.
