# Heart rate variability

Heart rate variability (HRV) is computed from the ECG of a Shimmer3 ECG unit recorded with the
[sensor logger](../usage/logger.md). It is a side product of the sensor data: it does not enter ΔPD, it goes into the
export package next to it, for the whole recording and for each event, so that heart and pupil measures of the same
phase can be compared. The code is `cwtool/hrv.py` (no Qt).

## What the ECG must be

| | |
|---|---|
| Sampling rate | **256 Hz or more.** At the Shimmer's usual 51.2 Hz the R peak is known to about ±10 ms, which is the size of the beat to beat differences, and the ECG's own spectrum reaches above the Nyquist frequency. The logger's *Sampling rate* choice sets it (see [Recording the ECG](../usage/logger.md#recording-the-ecg)); the analysis adds a note to a recording below 200 Hz. |
| Lead | **Lead II** (LL − RA, `exg_ads1292r_1_ch1_24bit`), where the R wave is largest. Lead I flips between R and S waves and is not used. |
| Electrodes | RA, LA, LL and RL (the fifth, Vx, is not needed). |
| Gain | read from `session.json` (`exg`, saved by the logger). Without it 4 is assumed, with a note: the gain only changes the scale in mV, not the beats. |

## The steps

1. **Millivolts.** Raw counts × 2.42 V / (2²³ − 1) / gain. Only used inside the detection.
2. **Time base.** The Shimmer's own clock (`device time (s)`) is regular; the Unix times of the file carry the delay
   of Bluetooth bursts. Beats are found on the device clock and mapped onto the Unix clock by the straight line
   through (device time, Unix time) of the whole file. Short gaps in the stream (lost packets, up to 0.5 s) are bridged
   by interpolation; a longer gap ends the stretch, and no interval is measured across it.
3. **R peaks.** [NeuroKit2](https://neuropsychology.github.io/NeuroKit/) finds them (`ecg_clean`, then the `neurokit`
   method of `ecg_peaks`), on each gap-free stretch, after flipping a stretch whose larger deflection points down.
   Each peak is moved to the maximum of the band-passed ECG (0.5–40 Hz) nearby and refined below one sample by a
   parabola. NeuroKit2 is sensitive, so a detection below 35 % of the median R amplitude (a T wave, noise) is dropped.
   NeuroKit2 is the `hrv` extra; without it the export skips the HRV and says so.
4. **Which intervals to trust.** An interval (time since the previous beat) is **not trusted** if it spans a gap, lies
   outside 0.25–2.5 s, or is more than 30 % away from the median of the 11 intervals around it. That catches a missed
   beat (an interval twice as long) and an extra one (a short interval and a long one). Untrusted intervals are left
   out, not repaired, and so are the successive differences that involve them.
5. **Measures** of a window, from the trusted intervals:

   | Measure | Definition |
   |---|---|
   | `mean_hr_bpm`, `mean_nn_ms` | 60000 / mean interval; the mean interval |
   | `sdnn_ms` | standard deviation of the intervals |
   | `rmssd_ms` | root mean square of the differences between successive intervals |
   | `pnn50_percent` | share of successive differences above 50 ms |
   | `sd1_ms`, `sd2_ms` | Poincaré plot: SD1 = SD of the differences / √2, SD2 = √(2·SDNN² − SD1²) |
   | `lf_ms2`, `hf_ms2`, `lf_hf` | power of the interval series in 0.04–0.15 Hz and 0.15–0.40 Hz, from the series resampled at 4 Hz (cubic spline), detrended, Welch's method (64 s segments, 50 % overlap); only for windows of at least 120 s |

## Windows

The export holds one row per window: the **whole recording** and **each event** of the event log, clipped to the
recording. With an [export range](../usage/gui.md#export-range) the beats in the left-out parts are dropped, and no
interval counts that spans one; `kept_seconds` says how much of the window is left. The first beat of a window has no
interval (its predecessor is before the window).

How long a window must be is not a software question. Short-term HRV norms (RMSSD, SDNN, LF, HF) are defined for
about 5 minutes; about 1 minute is often accepted for RMSSD alone, and anything shorter is rough. The result carries
a note for windows under 60 s (all measures rough) and under 120 s (no LF and HF), and one when more than 10 % of the
intervals were not trusted.

## What it does not do

- It does not interpret the numbers. Heart rate and HRV follow movement, posture, speech, breathing rate (HF moves
  with it), caffeine and the task itself; this is why a baseline phase in the event log matters.
- It is **not validated against a clinical reference**. It was checked on synthetic ECGs with known beat times and on
  recordings of one person at rest, and compared with NeuroKit2 on a 5-minute recording: the beats agree (296 of the
  297 NeuroKit2 finds, to within 1.1 ± 1.2 ms), and SDNN, RMSSD, pNN50 and SD1 computed from the same beats are the same
  as NeuroKit2's; LF and HF differ by 5 to 12 % (other Welch settings) and SD2 by 7 %
  ([open issue 51](../OPEN_ISSUES.md)).
- It does not correct untrusted intervals by interpolation or by inserting a missed beat: it leaves them out.
- It uses one lead. An ECG that is too noisy to find the beats gives a note (`weak ECG`) or too few beats, not a number.

## From Python

```python
from cwtool import hrv, sensors
loaded = sensors.load_sensors(session_folder, epoch_start, duration)          # Sensor objects with their settings
shimmer = next(s for s in loaded if hrv.has_ecg(s))
results, beats = hrv.analyse(shimmer, epoch_start, [("recording", 0.0, duration)])
print(results[0].rmssd, results[0].notes)
```
