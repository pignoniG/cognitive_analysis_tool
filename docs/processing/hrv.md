# Heart rate variability

Heart rate variability (HRV) is computed from the ECG of a Shimmer3 ECG unit recorded with the
[sensor logger](../usage/logger.md). It is a side product of the sensor data: it does not enter ΔPD, it goes into the
export package next to it, for the whole recording and for each event, so that heart and pupil measures of the same
phase can be compared. The code is `cwtool/hrv.py` (no Qt).

Where it is computed: in the app, with **Compute HRV** in the [Sensor data](../usage/gui.md#sensor-data-optional) box
(the beats are drawn on the ECG plot and the measures shown in a table, so the detection can be checked before
exporting; the export then includes them); on the command line, by `cwtool` when it packs sensor data (`--no-hrv`
turns it off). The logger computes nothing: it records the raw ECG and its settings.

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
5. **Measures** of a window, from the trusted intervals. The set follows the review and tutorial of Pham et al. (2021,
   [Sensors 21(12):3998](https://doi.org/10.3390/s21123998)), whose tutorial uses NeuroKit2; the definitions are
   NeuroKit2's unless noted.

   | Measure | Definition |
   |---|---|
   | `mean_hr_bpm`, `mean_nn_ms` | 60000 / mean interval; the mean interval |
   | `sdnn_ms` | standard deviation of the intervals (holds the slow variation too: needs minutes) |
   | `cvnn` | SDNN / mean interval, a ratio: more stable when conditions or people have different heart rates |
   | `madnn_ms` | 1.4826 × the median absolute deviation of the intervals: a robust spread, little moved by an outlier |
   | `rmssd_ms` | root mean square of the differences between successive intervals: the **preferred short-term measure**, vagally mediated and reliable in short windows |
   | `pnn50_percent`, `pnn20_percent` | share of successive differences above 50 ms and above 20 ms |
   | `sd1_ms`, `sd2_ms`, `sd1_sd2` | Poincaré plot: SD1 = SD of the differences / √2 (equivalent to RMSSD), SD2 = √(2·SDNN² − SD1²) (like SDNN), and their ratio |
   | `lf_ms2`, `hf_ms2`, `lf_hf` | power of the interval series in 0.04–0.15 Hz and 0.15–0.40 Hz, from the series resampled at 4 Hz (cubic spline), detrended, Welch's method (64 s segments, 50 % overlap); only for windows of at least 1 minute |
   | `lfn`, `hfn` | LF / (LF + HF) and HF / (LF + HF): normalised, as the guidelines ask to report both forms (NeuroKit2 divides by the total power, which for these windows is nearly the same; VLF is not estimated, a 25 s … 5 min band needs 5 minutes) |
   | `lnhf` | natural logarithm of HF (ms²), the usual estimator of vagal tone |

## Windows

The export holds one row per window: the **whole recording** and **each event** of the event log, clipped to the
recording. `kept_seconds` says how much of the window is left after an [export range](../usage/gui.md#export-range).
A beat belongs to the window it is in, with its interval from the beat before it, wherever that beat is; only the very
first beat of the recording has no interval.

### Cutting at the export range

The HRV is **always worked out on the whole recording first and cut afterwards**, so the export range loses nothing at
its edges and there is no option to do it the other way:

1. the beats are found on all the ECG, and every interval is judged (trusted or not) against its neighbours wherever
   they are;
2. a window then counts the beats that are in it and not in a left-out part, each with its interval from the beat
   before it, even if that beat lies in a left-out part;
3. a successive difference (RMSSD, pNN50, SD1) is taken between two trusted intervals in a row, the later one counted,
   so one at the edge of a cut uses the interval before it, and none is ever taken across a cut;
4. the spectrum is read from the interval series of the whole recording (resampled once), cut at the markers: each kept
   stretch of the window is detrended and cut into half-overlapping Welch segments of 64 s that lie inside it, and the
   segments of all the stretches are averaged. A cut is never bridged. If no stretch is as long as a segment, the longest
   one is used whole, and below one minute of kept data in all there is no spectrum.

### How long a window must be

It follows Pham et al. (2021), who cite studies finding that time-domain measures such as RMSSD are as reliable from
windows of 10 to 30 s as from 5 minutes, while the frequency measures need at least 1 minute. Each result carries a
note:

| Window | What the note says |
|---|---|
| under 30 s | even RMSSD is rough; SDNN, SD2 and the spectrum mean nothing |
| 30 s to 1 min | RMSSD, pNN50 and SD1 are usable; SDNN and SD2 need minutes; no spectrum |
| 1 to 2 min | HF is usable; LF covers few cycles (0.04 Hz is 25 s a cycle), so LF and LF/HF are rough |
| over 2 min | no note on length |

Also a note when more than 10 % of the intervals were not trusted. Norms published for 5-minute recordings do not
apply to shorter windows, and short-term values are not comparable to 24-hour ones.

## Reading the numbers

- **RMSSD** (with pNN50, SD1 and HF) reflects the parasympathetic (vagal) modulation of the heart rate and is the
  measure to prefer in short windows; SDNN is the total variation and depends on the window length.
- **HF is respiratory sinus arrhythmia**: it follows breathing, and 0.15–0.40 Hz means 9 to 24 breaths a minute.
  Slower breathing moves the variation into LF, faster breathing out of HF; speech and posture do the same. Interpret
  HF together with RMSSD, and where it matters control the breathing or record it (the ECG unit's respiration channel
  is not used here).
- **LF is not a sympathetic index**: it is shaped by both branches and by the baroreflex, and **LF/HF is not a
  measure of sympathovagal balance**; do not conclude from it alone.
- **The absolute spectral values depend on the method** (FFT, Lomb–Scargle, Welch; the window, the detrending): they
  cannot be compared with other studies' values, only between windows analysed alike, which is why the normalised
  forms are given as well. Welch on this page differs from NeuroKit2's by 5 to 13 % on the same beats.
- **Tonic and phasic**: a value in one window says little alone. The change from a baseline phase (a rest event in
  the event log) to a task phase, the *phasic* HRV, is what relates to load and effort, and its direction depends on
  the task (Pham et al. 2021, section 15). Put a baseline phase in the protocol.

## What it does not do

- It does not interpret the numbers: see above. Heart rate and HRV also follow movement, caffeine and the task itself.
- It computes no VLF, ULF, geometric (HTI, TINN), entropy, fractal (DFA) or time-frequency measures, nor RSA from a
  respiration signal; these need long recordings or another signal.
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

## Check against the literature

The procedure was checked against Shaffer & Ginsberg (2017), Laborde et al. (2017), Pham et al. (2021) and the descriptions
of Brennan et al. (2001) and Kubios found in other papers (the 1996 Task Force text could not be opened, so what is
attributed to it is as these papers quote it). The bands, the minimum of 1 minute for HF and 2 for LF, RMSSD as the
preferred short-term vagal measure, the HF and breathing link, LF and LF/HF not being sympathetic or balance measures, the
Poincaré relations, the 4 Hz resampled interval series with Welch's method and the use of a baseline phase agree with them.
The differences are that the Welch segments are 64 s (Kubios used 256 s, so LF is coarse and absolute values are not
comparable with other software), that Laborde et al. prefer an autoregressive estimate for HF, that untrusted intervals are
left out rather than interpolated (except in the spectrum), and that the thresholds of the trust rule are chosen on test
recordings, not taken from a standard. They also advise looking at the ECG, which the beats drawn on the plot are for.
Details and what is still open are in [open issue 51](../OPEN_ISSUES.md).

## Reference

Pham T., Lau Z. J., Chen S. H. A., Makowski D. (2021). Heart rate variability in psychology: a review of HRV indices
and an analysis tutorial. *Sensors* 21(12), 3998. [doi:10.3390/s21123998](https://doi.org/10.3390/s21123998)
