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

(`VideoResult.weighted`, used by every luminance method and by the calibration fit.)

## Display devices

For the Varjo, the capture shows what the display showed, so the colours map to luminance through the
**display photometry** (the per-channel extension of the WCAG 2.1 relative luminance proposed in the Varjo manuscript,
[in preparation](../reference/references.md)):

\[
L = \sum_{c \in \{R,G,B\}} k_c \left( L_\text{max}\, \frac{g_c}{\bar g}\, C_{w,c} + L_\text{min}\,(1 - C_{w,c}) \right)
\]

- \(L_\text{min}\), \(L_\text{max}\): the panel's black and white points (cd/m²), parameters `l_min`, `l_max`;
- \(g_c\): channel gains (`gain_r/g/b`), divided by their mean \(\bar g\) so they act as a relative balance;
- \(k_c\) = 0.2126, 0.7152, 0.0722: the photopic weights of the BT.709/sRGB primaries.

**Change from the manuscript (September 2026).** The manuscript divides the whole sum by \(\bar g\), black-point term included:
\(L = \frac{1}{\bar g}\sum_c k_c (L_\text{max} g_c C_{w,c} + L_\text{min}(1 - C_{w,c}))\). Black then maps to
\(L_\text{min}/\bar g\) rather than \(L_\text{min}\) whenever the gains do not average 1, and the manuscript's statement that
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

For the Pupil Core, Neon and Tobii Pro Glasses 3, the scene camera's automatic exposure hides the absolute level, so it comes from the
[lux sensor](../hardware/lux-sensor.md). Following Pignoni et al. (2021, eq. 5–8):

1. The lux readings are smoothed (Savitzky–Golay, 11 samples, order 6) and converted to the **average luminance**
   of the sensor's view: \(\bar L = (g \cdot E + o) / \Omega\) (parameters `lux_gain`, `lux_offset`,
   `lux_solid_angle`). \(\Omega\) = 2.2 is the ratio of illuminance to average luminance for the sensor in its
   housing, and \(g\) = 1, \(o\) = 0 by default (1.x used 1.706061 and 0.66935; see
   [Lux sensor](../hardware/lux-sensor.md)).
2. The video **distributes** that average over the view. With \(Y_w\) the relative luminance of the weighted
   gaze/background colour and \(Y_\text{frame}\) that of the whole frame, both computed with the photopic weights
   and channel balance:

\[
L = \bar L \cdot \frac{Y_w}{Y_\text{frame}}
\]

Looking at something brighter than the average of the view raises \(L\) above the sensor's average, and vice versa.
The camera's exposure cancels in the ratio. Set `lux_use_video` off to use the sensor's average alone.

The ratio follows where the gaze looks, and it is not always right to keep it. It is what carries the changing
screen into the luminance when the sensor sees little of it (a laptop screen filling part of the view, the sensor
looking past it), but on a uniform view it should stay near 1 and it only adds noise when it wanders, as it does on
dark frames. The analysis flags a wide spread (10th to 90th percentile above ×1.5, frames that are not nearly
black), which is a prompt to compare the two settings, not a verdict: two calibration recordings on a screen gave
opposite answers. The app
plots the sensor average, the luminance used and the ratio, so the effect of the video can be seen.

In the 2021 paper the area of interest was selected around the gaze with a Grab Cut algorithm and used alone
(\(L = \bar L \cdot rL_\text{AOI} / rL_\text{frame}\)). 2.0 uses the fixed gaze circle weighted against the background,
as for the display devices, so \(Y_w\) replaces \(rL_\text{AOI}\).

\(L_\text{min}\) and \(L_\text{max}\) are not used in this mode, so the plots show no black and white point lines.

Version 1.x combined the sensor and camera with a different heuristic; see [open issue 29](../OPEN_ISSUES.md).

## Lux devices without a lux log

If a glasses recording has no lux readings, the scene camera is used alone. **Camera exposure** (`camera_exposure`)
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
