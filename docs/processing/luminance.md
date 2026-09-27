# Luminance

How the video pass's colours become the luminance \(L(t)\) in cd/m² that drives the pupil model. Which method is
used depends on the device profile's `luminance_source`.

## Colour to linear light

Code values \(C\) (0–255) are decoded with a power curve,

\[
C_\text{lin} = \left(\frac{C}{255}\right)^{\gamma}
\]

per pixel, before averaging (see [Scene video analysis](video.md#linearising-before-averaging)). At \(\gamma\) = 2.2
this is the usual approximation of the sRGB curve; unlike the piecewise sRGB formula it stays continuous for any
\(\gamma\), which is adjustable because headset tone mapping is undocumented.

The gaze circle and background means are then weighted, with \(w\) = `fixation_weight` (default 0.65):

\[
\mathbf{C}_w = w\,\mathbf{C}_\text{lin,gaze} + (1 - w)\,\mathbf{C}_\text{lin,background}
\]

## Display devices

For the Varjo, the capture shows what the display showed, so the colours map to luminance through the display's
**photometric calibration** (the paper's per-channel extension of the WCAG 2.1 relative luminance):

\[
L = \frac{1}{\bar g}\sum_{c \in \{R,G,B\}} k_c \left( L_\text{max}\, g_c\, C_{w,c} + L_\text{min}\,(1 - C_{w,c}) \right)
\]

- \(L_\text{min}\), \(L_\text{max}\): the panel's black and white points (cd/m²), parameters `l_min`, `l_max`;
- \(g_c\): channel gains (`gain_r/g/b`), normalised by their mean \(\bar g\) so they act as a relative balance;
- \(k_c\) = 0.2126, 0.7152, 0.0722: the photopic weights of the BT.709/sRGB primaries.

With unit gains this is a linear mapping of relative luminance onto \([L_\text{min}, L_\text{max}]\). These are
real luminances: the adapting field area comes from the device profile, not from the photometric parameters. The
defaults (0.02 and 70 cd/m²) are the mean of the Varjo pilot calibrations; each participant is calibrated on the
[calibration sequence](../usage/calibration.md).

## Lux sensor devices

For the Pupil Core and Neon, the scene camera's automatic exposure hides the absolute level, so it comes from the
[lux sensor](../hardware/lux-sensor.md). Following Pignoni et al. (2021, eq. 5–8):

1. The lux readings are smoothed (Savitzky–Golay, 11 samples, order 6) and converted to the **average luminance**
   of the sensor's view: \(\bar L = (g \cdot E + o) / \Omega\) (parameters `lux_gain`, `lux_offset`,
   `lux_solid_angle`).
2. The video **distributes** that average over the view. With \(Y_w\) the relative luminance of the weighted
   gaze/background colour and \(Y_\text{frame}\) that of the whole frame, both computed with the photopic weights
   and channel balance:

\[
L = \bar L \cdot \frac{Y_w}{Y_\text{frame}}
\]

Looking at something brighter than the average of the view raises \(L\) above the sensor's average, and vice versa.
The camera's exposure cancels in the ratio. Set `lux_use_video` off to use the sensor's average alone.

\(L_\text{min}\) and \(L_\text{max}\) are not used in this mode, so the plots show no black and white point lines.

!!! note "Without lux logs"
    If a lux device's recording has no lux readings, the scene camera alone is used, mapped onto
    \([L_\text{min}, L_\text{max}]\) as for a display, and a warning says so: the automatic exposure makes it only
    relative.

Version 1.x combined the sensor and camera with a different heuristic; see [open issue 29](../OPEN_ISSUES.md).

## Timing

The video and lux luminance are interpolated onto the analysis grid, shifted by the **time lag** parameter
(`timelag`, s, subtracted from the luminance timestamps).
