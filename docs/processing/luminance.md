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

For the Varjo, the capture shows what the display showed, so the colours map to luminance through the
**display photometry** (the paper's per-channel extension of the WCAG 2.1 relative luminance):

\[
L = \sum_{c \in \{R,G,B\}} k_c \left( L_\text{max}\, \frac{g_c}{\bar g}\, C_{w,c} + L_\text{min}\,(1 - C_{w,c}) \right)
\]

- \(L_\text{min}\), \(L_\text{max}\): the panel's black and white points (cd/m²), parameters `l_min`, `l_max`;
- \(g_c\): channel gains (`gain_r/g/b`), divided by their mean \(\bar g\) so they act as a relative balance;
- \(k_c\) = 0.2126, 0.7152, 0.0722: the photopic weights of the BT.709/sRGB primaries.

**Change from the paper (September 2026).** The paper divides the whole sum by \(\bar g\), black-point term included:
\(L = \frac{1}{\bar g}\sum_c k_c (L_\text{max} g_c C_{w,c} + L_\text{min}(1 - C_{w,c}))\). Black then maps to
\(L_\text{min}/\bar g\) rather than \(L_\text{min}\) whenever the gains do not average 1, and the paper's statement that
uniform gains reduce to the plain linear mapping holds only for gains of 1. In the calibration fit the gains are free,
so their overall scale also changed the black level during the fit, and normalising the reported weights to a mean of
1 afterwards changed it again. 2.0 applies the gains to the white-point term only: black is always \(L_\text{min}\),
and scaling all gains by a constant changes nothing ([open issue 9](../OPEN_ISSUES.md)).

With unit gains this is a linear mapping of relative luminance onto \([L_\text{min}, L_\text{max}]\). These are
real luminances: the adapting field area comes from the device profile. \(L_\text{min}\), \(L_\text{max}\) and
\(\gamma\) are the user's nominal values for the headset (e.g. its datasheet), saved in their own file; the defaults
(0.02 and 70 cd/m²) are the mean of the Varjo pilot calibrations. The channel gains are the participant's channel
weights, fitted with their light sensitivity on the [calibration sequence](../usage/calibration.md).

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

Version 1.x combined the sensor and camera with a different heuristic; see [open issue 29](../OPEN_ISSUES.md).

## Lux devices without a lux log

If a Pupil recording has no lux readings, the scene camera is used alone. **Camera exposure** (`camera_exposure`)
says how to read it.

**`auto`** (default): the camera adjusted its exposure, so the video gives only relative luminance. It is mapped onto
\([L_\text{min}, L_\text{max}]\) as for a display, and a warning says so.

**`fixed`**: the exposure was fixed during the recording (Neon's manual exposure mode, or manual exposure in Pupil
Capture for the Core). Linearised pixel values are then proportional to scene luminance, up to saturation:

\[
L = L_\text{full} \cdot Y_w, \qquad L_\text{full} = L_\text{white} \cdot \frac{t_\text{ref}}{t}
\]

- \(Y_w\): relative luminance of the weighted gaze/background colour, as above;
- \(L_\text{white}\) (`camera_white`): the luminance that saturates the camera (code 255) at the reference
  exposure time \(t_\text{ref}\) (`camera_reference_ms`);
- \(t\) (`camera_exposure_ms`): the recording's exposure time. A longer exposure saturates at a lower luminance.
  With either time at 0, \(L_\text{white}\) is used as is.

A warning appears when the gaze area is saturated (mean code value ≥ 250) in more than 5 % of the video samples,
since luminance is underestimated there.

### Calibrating the camera from a lux log

\(L_\text{white}\) depends on the camera, its gain and the lens, so it is measured once: record with the same
fixed exposure **and** the lux sensor, open that recording, enter its exposure time and click
**Calibrate camera from lux**. The sensor's average luminance \(\bar L\) and the whole frame's relative luminance
\(Y_\text{frame}\) describe the same view, so

\[
L_\text{white} = \operatorname{median}\left(\frac{\bar L}{Y_\text{frame}}\right)
\]

over the video samples that are neither black nor saturated. The dialog reports the spread (90th / 10th percentile
of the per-sample ratios); above ×2 it warns that the exposure was probably not fixed. Applying sets `camera_white`
and `camera_reference_ms`; save the parameters and load them for recordings without a lux log.

The assumptions behind this (fixed gain, the camera's tone curve, lens vignetting) are listed in
[open issue 35](../OPEN_ISSUES.md).

## Timing

The video and lux luminance are interpolated onto the analysis grid, shifted by the **time lag** parameter
(`timelag`, s, subtracted from the luminance timestamps).
