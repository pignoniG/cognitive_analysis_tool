# Pupil signal

`pipeline.prepare`. From the device's per-eye pupil values to a clean signal on a uniform grid.

## 1. Scale to mm

Device units × the profile's `pupil_scale` × the participant's `pupil_correction`. The Varjo reader sets the scale
per recording, 2 for exports that hold the radius and 1 for those that hold the diameter ([Varjo XR-4](../devices/varjo.md#pupil-scale)). For pixel data (Pupil Core 2D)
the scale is unknown and set later so the mean measured pupil equals the mean expected pupil (2021 method).

## 2. Range check

Scaled diameters outside **1–9 mm** are tracking errors and removed.

## 3. Artefact filter

Blink edges and tracking jumps change the apparent pupil faster than the iris can. A sample is removed when the
pupil changes faster than `max_pupil_speed` (default 10 mm/s) towards the previous or next sample **at least 40 ms
away**, and `artefact_padding` (0.05 s) is removed around each. Measuring the speed over 40 ms rather than between
neighbouring samples keeps the threshold independent of the sampling rate: at 200 Hz, sample-to-sample noise alone
would read as high speed. Physiological responses stay well below 10 mm/s. Set the speed to 0 to disable the filter.

Steps 2 and 3 run on each eye separately. Pixel data (Pupil Core 2D) skip both: their thresholds are in mm and the
scale is only known after the expected pupil is computed.

## 4. Combine the eyes

`eye` = `left`, `right` or `both`. `both` averages the two eyes. Where one eye is missing it is taken as the other plus
the median difference between the eyes, measured on the samples with both (at least 20; otherwise the tracked eye is
used as it is): the eyes often differ by a steady amount (up to 0.26 mm on the Varjo calibration recordings), and a
plain fallback would step the average by half of it whenever one eye drops out
([open issue 45](../OPEN_ISSUES.md)).

## 5. Resample

The signal is put on a uniform grid at `analysis_rate` (default 100 Hz; 0 = the device's native rate), by linear
interpolation between valid samples. Gaps longer than `max_gap` (0.5 s) are marked invalid: they are left out of
ΔPD, the offset and the statistics, and appear as breaks in the plots. Shorter gaps (blinks) are bridged. The
summary line reports the share of the recording in long gaps, together with the stretches where the luminance is
unknown ([Processing at a glance](pipeline.md), step 3d).

## 6. Smooth

Two Savitzky–Golay versions are kept:

| Signal | Window | Order | Use |
|---|---|---|---|
| measured | about 0.5 s | 2 | ΔPD, the black curve |
| measured (raw) | about 0.25 s (at least 9 samples) | 6 | the grey curve; the calibration fit, which needs step edges |

The measured pupil is then scaled (pixel data), offset ([ΔPD and alignment](delta-pd.md)) and compared with the
expected pupil.

## Plausibility

If the median measured pupil is outside 2–8 mm after scaling and the offset (as plotted and exported), a warning
suggests checking the pupil scale correction (set by hand) and the offset.
