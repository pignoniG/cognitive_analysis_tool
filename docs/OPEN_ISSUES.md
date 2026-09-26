# Open issues

Inconsistencies and suspected errors found while porting the Varjo build (`develop-varjo`, legacy
`pupil_code/`) to the 2.0 `cwtool` package, and between the code and the paper draft
("Toward Reliable Pupillometry in Extended Reality Environments", second draft).

The legacy code has since been removed from `v2.0`; file references such as `lum_analysis.py` or `data_tools.py`
point to `develop-varjo`.

Each issue says where it is, why it matters, what 2.0 currently does and what is proposed.
**Status** is one of: *open* (needs a decision), *kept* (2.0 reproduces the legacy behaviour until decided),
*fixed in 2.0*, *needs data* (needs a sample recording to settle).

Several of these interact. Issues 1, 2, 4, 9 and 12 in particular all change the absolute scale of the
expected or measured pupil, and the calibrated values in Table 2a (Lmax 1500–6500 cd/m²) may be absorbing
them rather than describing the headset or the participant.

---

## A. Pupil model and signal

### 1. Measured pupil is multiplied by 2
- **Where:** `lum_analysis.py` (`x * (1 + pupilCoeff)`, default `pupilCoeff = 1`); 2.0 `Parameters.pupil_scale = 2.0`.
- **Problem:** the code comment says Varjo outputs a radius, but the paper says the XR-4 reports pupil
  diameter in mm. Both cannot be true. If Varjo reports a diameter, every measured pupil is doubled.
- **Related:** the Varjo validity filter keeps values between 1 and 9 mm *before* scaling, which only makes
  sense if the value is already a diameter.
- **Proposal:** check against Varjo's documentation and a sample (typical adult diameters are 2–8 mm).
  If it is a diameter, set the default to 1.0 and keep the scale as a per-participant calibration term
  (the paper already discusses glasses biasing the mm conversion).
- **Context (G. Pignoni):** Varjo confirmed by email that its output is the radius. The scaling from eye-camera
  pixels to mm also seems inconsistent between sessions, so a correction is sometimes needed; this is one reason
  for recording calibration data.
- **2.0:** each device profile declares its pupil unit and default scale (Varjo mm ×2; Pupil Core 3D mm ×1;
  pixel data has no default and is scaled by the 2021 ratio method). Participants get a `pupil_correction`
  multiplier (fitted from the calibration sequence in the next step). The 1–9 mm validity range is applied after
  scaling, and a warning is shown when the median diameter is outside 2–8 mm.
- **Status:** fixed in 2.0 (correction fit pending, see issue 2/3 work).

### 2. Measured pupil is shifted to match the expected mean
- **Where:** `lum_analysis.py` (`coeff = meanLux - meanRec`); 2.0 `Parameters.align_mean = True`.
- **Problem:** the mean of ΔPD is forced to about zero in every recording. This hides any constant offset,
  so absolute ΔPD levels cannot be compared between recordings, and a mis-set Lmin/Lmax or pupil scale is
  partly masked. The paper does not describe this step; its calibration procedure ("centre the expected and
  measured curves") may in practice be this automatic shift.
- **Proposal:** decide whether it is part of the method. If yes, document it in the paper and consider
  fitting the offset on the calibration sequence (per participant) instead of on each recording.
  If no, default to off.
- **Status:** kept, open.

### 3. The 0.5 s delay is applied even when dynamics are off
- **Where:** `lum_analysis.py` (delay loop sits outside `if pupilDynamics`); 2.0 `Parameters.delay = 0.5`, always applied.
- **Problem:** the paper presents the delay as the first stage of the optional dynamic correction, and gives
  200–500 ms as the physiological range. The code always delays by 500 ms.
- **Proposal:** decide whether the delay is part of the optional correction. Either way, expose it as a
  parameter (2.0 already does) and consider 0.3 s as a default within the literature range.
- **Status:** kept, open.

### 4. Field size used as a diameter instead of an area
- **Where:** `colour_tools.effectiveCornealFluxDensity` (`L * a * M(e)`), `fieldAngle = 160`; 2.0 `Parameters.field`.
- **Problem:** Watson & Yellott define the corneal flux density as F = L · a · M(e) with *a* the field
  **area in deg²**. The code passes 160 and the UI calls it "field angle". A 160° diameter field is
  about 20 000 deg² (π · 80²), so F is underestimated by roughly 125×. The same predicted pupil then
  needs about 125× more luminance, which may be why calibrated Lmax values sit at 1500–6500 cd/m².
  (For fields this large the formula is also outside the range it was fitted on.)
- **Proposal:** decide whether to treat the parameter as an area (and convert from the headset's FOV),
  or keep it as an empirical "field" constant and say so in the paper. Changing it will change every
  calibrated Lmax.
- **Note:** the 2021 paper (eq. 1) also describes *a* as "field diameter (degrees of view)".
- **Key point:** the formula uses luminance and field only through their product, so the two cannot be
  separated by calibration; any error in the field is absorbed into Lmax.
- **2.0:** the field is the device's visible field area in deg² (from its field of view, e.g. XR-4
  120° × 105° ≈ 9 900 deg²), and Lmin/Lmax are real luminances. Version 1 parameter files are converted exactly
  (Lmin/Lmax × 160 / area). The pilot Lmax values 1500–6500 cd/m² become about 24–105 cd/m²; the default
  Lmax is 70 cd/m² (mean pilot value, converted). A luminance-meter reading of a full-white frame on the XR-4
  would validate the approach.
- **Status:** fixed in 2.0 (needs validation with a luminance meter).

### 5. CW RMS is an RMS about the mean
- **Where:** `lum_analysis.py` (`rms` computed around `meanDistance`); 2.0 `Result.cw_rms`.
- **Problem:** the paper defines CW rms as the root-mean-square of ΔPD. The code computes it about the mean
  (a standard deviation). The two are the same only because of the mean alignment in issue 2.
- **Proposal:** define it once. If mean alignment is turned off, plain RMS of ΔPD is the more natural
  calibration error.
- **2.0:** two figures are reported: residual RMS (√mean ΔPD², the calibration error) and ΔPD SD (the unit
  for normalised ΔPD).
- **Status:** fixed in 2.0.

### 6. Pupil sampling rate is hardcoded to 100 Hz
- **Where:** `lum_analysis.py` (`sampleFreq = 100`); 2.0 `varjo.SAMPLE_RATE = 100`.
- **Problem:** filters, the delay and the ΔPD window are all defined in samples at 100 Hz. The XR-4 can
  also track at 200 Hz, and dropped samples (blinks, invalid rows) make the real rate irregular.
- **Proposal:** estimate the rate from the timestamps, and resample to a uniform grid before filtering.
- **2.0:** the measured rate is estimated from the timestamps; pupil data is resampled onto a uniform grid
  (`analysis_rate`, default 100 Hz), gaps up to `max_gap` (0.5 s) are interpolated and longer ones are left out
  of ΔPD and the RMS. Filters and windows are defined in seconds.
- **Status:** fixed in 2.0.

### 7. Attack/release filter started from 0
- **Where:** `lum_analysis.py` (`y = np.zeros_like(...)`, loop from n = 1).
- **Problem:** the filtered expected pupil starts at 0 and rises with the slow 6 s attack, producing a large
  artefact in the first seconds of every recording when dynamics are on.
- **Status:** fixed in 2.0 (filter starts at the first input value).

### 8. ΔPD windows shifted back by one window
- **Where:** `data_tools.drawDistance` (`sStart = sample * len - len`).
- **Problem:** the first two windows are identical and every window is labelled with a time one window
  (0.2 s) early.
- **Status:** fixed in 2.0 (consecutive, non-overlapping windows).

---

## B. Luminance from the video

### 9. Paper's RGB → cd/m² equation: the Lmin term is divided by the mean gain
- **Where:** paper, "Absolute luminance with per-channel panel gains"; 2.0 `luminance.absolute_luminance` (implemented as written).
- **Problem:** L_px = (L_R + L_G + L_B) / c̄ with L_C = (Lmax · c_C · C_lin + Lmin · (1 − C_lin)) · w_C.
  Dividing by c̄ also scales the black-point term, so with equal gains ≠ 1 black maps to Lmin / c̄, not Lmin.
  The paper's claim that uniform gains reduce to the plain linear mapping only holds for gains of 1.
- **Proposal:** apply the normalisation to the Lmax term only:
  L_px = Σ_C w_C · (Lmax · (c_C / c̄) · C_lin + Lmin · (1 − C_lin)).
- **Status:** open.

### 10. Table 2a "channel Lmax" columns do not follow the equations
- **Where:** paper, Table 2a.
- **Problem:** for participant a (Lmax 5000, gains 5 / 1.5 / 3), "Red Lmax" is 2631.6 = 5000 · 5 / 9.5,
  i.e. Lmax · r_C / (r_C + g_C + b_C). From the equations, red's contribution at full red is
  Lmax · r_C · 0.2126 / c̄ ≈ 1678 cd/m².
- **Proposal:** recompute the columns from the equations, or relabel them as "share of Lmax".
- **Status:** open (paper).

### 11. Which code produced the pilot results?
- **Where:** legacy `colour_tools.manualRGBtoLuminanceClac`, used by `readCdm2Varjo`.
- **Problem:** the legacy function is not the paper's equation. It adds `rCoeff − gCoeff/2 − bCoeff/2`
  (and so on) to the sRGB weights and then maps the result linearly between Lmin and Lmax. With the Table 2a
  gains (e.g. b_C = 20) that gives negative or extreme weights, so Table 2 was probably not computed with the
  code on `develop-varjo`. 2.0 implements the paper's equation.
- **Proposal:** confirm which implementation produced Table 2, and re-run one pilot participant through 2.0
  to check the numbers match.
- **Status:** open.

### 12. Gamma 2.2 inside the piecewise sRGB curve
- **Where:** paper eq. for C_lin; legacy `relativeLuminanceClac` / `manualRGBtoLuminanceClac`; 2.0 `luminance.srgb_to_linear`.
- **Problem:** the piecewise sRGB decoding (linear below 0.04045, ((C' + 0.055) / 1.055)^γ above) is defined
  with γ = 2.4. With γ = 2.2 the two pieces do not meet: at C' = 0.04045 the linear part gives 0.00313 and the
  power part 0.00506. "2.2" is the exponent of the *pure power* approximation of sRGB (C_lin = C'^2.2).
  The legacy code also mixes 2.2 (Varjo luminance) and 2.4 (video averages).
- **Proposal:** either piecewise with 2.4 (exact sRGB) or pure power with an adjustable γ (default 2.2).
- **Status:** open.

### 13. Averaging gamma-encoded pixel values
- **Where:** legacy `magicwand.mean` / `meanSmall`; 2.0 `video.analyse_frame`.
- **Problem:** the mean of each area is taken on 8-bit gamma-encoded values and linearised afterwards.
  Because the decoding curve is convex, this underestimates the luminance of textured areas
  (e.g. half black, half white averages to code 128 → ~0.22 instead of 0.5 linear).
- **Proposal:** linearise per pixel, then average. This makes the video cache depend on γ, or requires caching
  linear means for a fixed decoding curve (which issue 12 would settle).
- **Status:** open.

### 14. Fixation and background weighting done on raw RGB
- **Where:** legacy `vid_analysis.subFrameAsinc` (0.65 weighting applied to encoded RGB means).
- **Problem:** the paper weights relative luminances (rL = w_fix · rL_fix + w_bg · rL_bg).
- **Status:** fixed in 2.0 (weighting on linear values, as in the paper). Results differ slightly from legacy.

### 15. Background includes the fixation area
- **Where:** legacy `magicwand` (background mask is the whole scene circle); 2.0 `VideoSettings.background_excludes_fixation = False`.
- **Problem:** the paper describes rL_bg as "the remainder of the frame". The code includes the fixation circle.
  The effect is small (the fixation circle is ~1.5 % of the scene circle) but the text and code disagree.
- **Proposal:** pick one; 2.0 supports both.
- **Status:** kept, open.

### 16. Legacy video CSV has R and G columns swapped
- **Where:** `magicwand.mean` returns B, G, R (OpenCV order) but `subFrameAsinc` unpacks it as B, R, G;
  `readCdm2Varjo` then reads R from the "G_pixval" column and G from "R_pixval".
- **Problem:** the two swaps cancel, so luminance is correct, but `outputFromVideo.csv` is mislabelled for
  anyone reading it directly.
- **Status:** fixed in 2.0 (new cache format, RGB order).

### 17. Fixation circle size is not defined in visual angle
- **Where:** legacy `magicwand` (radius = scene radius / 8); 2.0 `VideoSettings.fixation_ratio`.
- **Problem:** the fixation area is a fraction of the frame, so it covers a different visual angle on each
  device (Varjo, Pupil Core, Neon scene cameras have different FOVs), and the paper does not give its size.
- **Proposal:** define it in degrees per device and report the value in the paper.
- **Status:** open.

---

## C. Data ingestion

### 18. Varjo CSV columns read by position
- **Where:** legacy `readPupilVarjo` / `readGazeVarjo` / `processPupilVarjo`; 2.0 `devices/varjo.py`.
- **Problem:** columns 1, 2, 6, 24–26, 34–36, 39, 43 are hardcoded. A Varjo Base update that adds or reorders
  columns would silently read the wrong data.
- **Proposal:** read by header name once a sample export is available.
- **Status:** needs data.

### 19. Only the left pupil was range-checked
- **Where:** `processPupilVarjo` (checks column 39 only).
- **Problem:** invalid right-eye values passed through and were averaged into "both".
- **Status:** fixed in 2.0 (each eye filtered independently).

### 20. Gaze from the left eye only
- **Where:** `vid_analysis.magicAnalysis` (`eye = "left"`); 2.0 `varjo.load(gaze_eye="left")`.
- **Problem:** the fixation area follows the left eye's projected gaze while the pupil defaults to the average
  of both eyes. Varjo also exports a combined gaze.
- **Proposal:** use the combined gaze by default; check the vertical flip and the mapping onto the
  3840 × 3744 frame (paper: "only monocular view shown" in Fig. 2) against a sample.
- **Status:** kept, needs data.

### 21. Video frame index assumes constant frame rate
- **Where:** `readGazeVarjo` (`frame_n = int(t / (1 / fps))`); 2.0 `video.analyse_video`.
- **Problem:** if the capture is variable frame rate or starts at an offset, gaze samples drift away from the
  frames they belong to.
- **Proposal:** use the container's frame timestamps (`CAP_PROP_POS_MSEC`) and check on a sample.
- **Status:** needs data.

### 22. Event log times depend on the computer's time zone
- **Where:** `data_tools.readEvents` (dateutil parse of a naive timestamp); 2.0 `varjo.read_event_log`.
- **Problem:** a timestamp without a zone is interpreted in the local time zone of the machine running the
  analysis, so events shift by hours when analysed elsewhere. Events are also assumed to be back-to-back
  (only the first start time is read; the rest are accumulated durations).
- **Proposal:** store event times with a zone or as unix time, and read each event's own start.
- **2.0:** `tools/event_logger.py` now writes times with the UTC offset, which the reader handles. Logs made with
  the old logger are still read in the local zone, and events are still assumed back-to-back.
- **Status:** partly fixed.

### 23. Lux sensor conversion constants are undocumented
- **Where:** `data_tools.readLux` (`1.706061 * x + 0.66935`, then `/ 2.2`, time × 0.001, one file per local hour).
- **Problem:** needed for Pupil Core and Neon. The origin of the constants (sensor calibration? lux → cd/m²?)
  is not documented, and hour-named files depend on the logger's local time.
- **Proposal:** document or re-derive while porting the Pupil readers (the legacy reader is on `develop-varjo`;
  the logger that writes these files is now `tools/lux_logger.py`).
- **Status:** needs data.

---

### 26. Saved legacy settings differ from the code defaults
- **Where:** the committed `settings.pkl` (last used settings of the legacy app) vs the defaults in `analysisTool.py`.
- **Values:** scene circle `maskSize` 0.8 (default 0.5), `pupilFiltering` 60 (default 1), `pupilDynamics` on
  (default off), `cameraLum_min` 0 / `cameraLum_max` 180 (defaults 0.02 / 200), age 33.
- **Why it matters:** results depend on which set was used, and the paper should report the values.
  `pupilFiltering` 60 means a ΔPD Savitzky-Golay window of 121 windows of 0.2 s, i.e. about 24 s of smoothing,
  which limits the time resolution of ΔPD far more than the paper suggests.
- **2.0:** scene circle default changed to 0.8 (the old 0.5 covered only half of the visible Varjo disc, which the
  video preview makes obvious). The other defaults are unchanged; `cw_smoothing` is the equivalent of `pupilFiltering`.
- **Status:** open.

## D. Paper text

### 24. Dynamics section: filter placement and stage count
- The text says the luminance signal is pre-filtered, then that the filter "acts on the luminance, after it is
  fed to the Watson and Yellott formula". The code filters the expected pupil diameter (after the formula),
  which matches the attack/release description.
- "Three stages are applied in sequence" but two are described (delay, attack/release). The third is presumably
  the min–max normalisation, which is only a rescaling (the filter is unaffected by it).

### 25. Default settings in Table 2b
- The "default" stage uses Lmax = 200 cd/m² with unit gains, while the legacy defaults are gains 0.4 / 0.0 / 0.2
  and Lmin = 0.02. State exactly which defaults the baseline used (2.0 uses unit gains).
