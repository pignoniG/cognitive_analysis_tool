# Expected pupil model

`cwtool/model.py`, `pipeline.expected_pupil`. The pupil diameter light alone would produce, in three stages.

## 1. Watson & Yellott (2012)

The unified formula for the light-adapted pupil. The corneal flux density is luminance × adapting field area ×
the monocular attenuation, with the participant's light sensitivity \(s\) (`sensitivity`, default 1) applied to
the luminance:

\[
F = s \cdot L \cdot a \cdot M(e), \qquad M(2) = 1,\; M(1) = 0.1
\]

with \(a\) the adapting field area in deg² (from the device profile, treating the field as an ellipse) and \(e\)
the number of eyes adapted (`eyes`). The sensitivity is fitted on the calibration sequence
([Calibration fit](calibration-fit.md#light-sensitivity)); the exported luminance is \(L\), without it. The Stanley & Davies (1995) diameter is

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

## 4. Transient (optional)

After a brightening step the pupil constricts beyond its new steady state and then re-dilates towards it within a
few seconds ("pupillary escape"). On the seven Varjo calibration recordings the model without it misses a dip of
0.43 mm on average 1 s after a brightening step, which recovers with a time constant of 1–2 s. With `transient`
above 0, the expected pupil is reduced by

\[
T(t) = \text{transient} \cdot \frac{h}{h + h_0}, \qquad h = \max\big(0,\; \log_{10} L - \mathrm{LP}_{\tau_\text{escape}}(\log_{10} L)\big)
\]

where \(\mathrm{LP}_\tau\) is a one-pole low-pass with time constant `escape`: \(h\) is the increase of log luminance
over its recent level, jumping at a brightening step and decaying with `escape`. Darkening gives no transient. The
response saturates with the step size (\(h_0\) = 0.2 log units, fixed: the measured re-dilation grew from 0.25 mm for a
0.1 log unit step to 0.52 mm for a 1 log unit step), so `transient` is the largest transient constriction in mm. It
has the same latency as the rest and, with `dynamics` on, passes through a one-pole low-pass with the constriction
time constant `release`.

## Display range

For display devices the expected pupil at \(L_\text{min}\) and \(L_\text{max}\) is shown as the dashed black and
white point lines: the range of pupil sizes the display can explain for this participant.
