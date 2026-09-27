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
- **Varjo sample:** `left_iris_diameter_in_mm` is exactly 6.04 mm in every sample, half of a typical 11–12 mm iris,
  which supports the radius explanation. Being a constant, it cannot serve as an independent per-session scale check.
  Eye tracking runs at 200 Hz (the device profile now says so).
- **Status:** fixed in 2.0.

### 2. Measured pupil is shifted to match the expected mean
- **Where:** `lum_analysis.py` (`coeff = meanLux - meanRec`); 2.0 `Parameters.align_mean = True`.
- **Problem:** the mean of ΔPD is forced to about zero in every recording. This hides any constant offset,
  so absolute ΔPD levels cannot be compared between recordings, and a mis-set Lmin/Lmax or pupil scale is
  partly masked. The paper does not describe this step; its calibration procedure ("centre the expected and
  measured curves") may in practice be this automatic shift.
- **Proposal:** decide whether it is part of the method. If yes, document it in the paper and consider
  fitting the offset on the calibration sequence (per participant) instead of on each recording.
  If no, default to off.
- **Context (G. Pignoni):** no better matching method was found so far; previous publications compared recordings
  in units of ± one standard deviation of ΔPD.
- **2.0:** `alignment` chooses how the offset is found: "recording" (median over the whole recording, the 1.x
  behaviour but with the median), "baseline" (median over named events, e.g. rest periods), "fixed" (an offset
  fitted on the participant's calibration sequence and reused for their other recordings, which keeps ΔPD's
  absolute level) or "none". ΔPD is exported both in mm and in SD units.
- **Status:** fixed in 2.0.

### 3. The 0.5 s delay is applied even when dynamics are off
- **Where:** `lum_analysis.py` (delay loop sits outside `if pupilDynamics`); 2.0 `Parameters.delay = 0.5`, always applied.
- **Problem:** the paper presents the delay as the first stage of the optional dynamic correction, and gives
  200–500 ms as the physiological range. The code always delays by 500 ms.
- **Proposal:** decide whether the delay is part of the optional correction. Either way, expose it as a
  parameter (2.0 already does) and consider 0.3 s as a default within the literature range.
- **Context (G. Pignoni):** 0.5 s is a good approximation of the eye's response delay; the optional dynamics
  are known to be imperfect.
- **2.0:** the delay stays a separate parameter (default 0.5 s, always applied). The calibration fit
  (`cwtool.fit`, "Fit latency, scale and offset" in the GUI) estimates each participant's latency, dilation and
  constriction time constants, pupil scale correction and offset from the 20 steps of the sequence, given the
  operator's photometric calibration. Latency and constriction speed trade off, so they are fitted jointly.
- **Status:** fixed in 2.0 (to be validated on the pilot recordings).

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
- **2.0:** switched to the pure power curve C_lin = (C'/255)^γ with γ adjustable (default 2.2). It is continuous
  for any γ and within 1 % of full scale of exact sRGB at 2.2. Compared with the previous hybrid, mid-tones decode
  about 12 % darker (code 128: 0.218 instead of 0.248), so calibrations made before this change should be
  re-checked on the sequence; this cannot be converted exactly.
- **Status:** fixed in 2.0.

### 13. Averaging gamma-encoded pixel values
- **Where:** legacy `magicwand.mean` / `meanSmall`; 2.0 `video.analyse_frame`.
- **Problem:** the mean of each area is taken on 8-bit gamma-encoded values and linearised afterwards.
  Because the decoding curve is convex, this underestimates the luminance of textured areas
  (e.g. half black, half white averages to code 128 → ~0.22 instead of 0.5 linear).
- **Proposal:** linearise per pixel, then average. This makes the video cache depend on γ, or requires caching
  linear means for a fixed decoding curve (which issue 12 would settle).
- **2.0:** pixels are linearised before averaging. Each area's per-channel histogram gives the mean of
  (C/255)^γ for a grid of γ values (1.4–3.0 in steps of 0.2), which are cached; other γ values are
  interpolated (error below 0.001 of full scale), so γ remains a live parameter without re-reading the video.
  Textured scenes now read brighter than before (a half-black, half-white area gives 0.5 instead of about 0.22).
  Older video caches are re-analysed automatically. γ is limited to 1.4–3.0.
- **Status:** fixed in 2.0.

### 14. Fixation and background weighting done on raw RGB
- **Where:** legacy `vid_analysis.subFrameAsinc` (0.65 weighting applied to encoded RGB means).
- **Problem:** the paper weights relative luminances (rL = w_fix · rL_fix + w_bg · rL_bg).
- **Status:** fixed in 2.0 (weighting on linear values, as in the paper). Results differ slightly from legacy.

### 15. Background includes the fixation area
- **Where:** legacy `magicwand` (background mask is the whole scene circle); 2.0 `VideoSettings.background_excludes_fixation = False`.
- **Problem:** the paper describes rL_bg as "the remainder of the frame". The code includes the fixation circle.
  The effect is small (the fixation circle is ~1.5 % of the scene circle) but the text and code disagree.
- **Proposal:** pick one; 2.0 supports both.
- **Reference:** Eckert et al. (2022) also define the background as "the whole screen except the fixation area".
- **2.0:** the background now excludes the gaze circle by default, matching both papers; including it remains an option.
- **Status:** fixed in 2.0.

### 16. Legacy video CSV has R and G columns swapped
- **Where:** `magicwand.mean` returns B, G, R (OpenCV order) but `subFrameAsinc` unpacks it as B, R, G;
  `readCdm2Varjo` then reads R from the "G_pixval" column and G from "R_pixval".
- **Problem:** the two swaps cancel, so luminance is correct, but `outputFromVideo.csv` is mislabelled for
  anyone reading it directly.
- **Status:** fixed in 2.0 (new cache format, RGB order).
- **Checked again (September 2026) for a green/blue swap:** none in either version. In 1.x only red and green are
  swapped, twice, which cancels; blue is never moved, and the whole-frame average weights the channels equally. In
  2.0 both decoders (PyAV, OpenCV) return pure red, green and blue H.264 frames as R, G, B
  (`tests/test_video.py::test_channels_are_in_rgb_order`); the preview converts OpenCV's BGR to RGB; the cache,
  channel gains, photopic weights and calibration sequence all use R, G, B. The April 2026 Varjo capture shows green
  at 170 s and blue at 230 s, where the built-in order (greys, red, green, blue) puts them given the located start
  and 10 s steps. The calibration scene plays the colours in R, G, B order (confirmed by the author), so the
  capture, the sequence and the analysis agree.

### 17. Fixation circle size is not defined in visual angle
- **Where:** legacy `magicwand` (radius = scene radius / 8); 2.0 `VideoSettings.fixation_ratio`.
- **Problem:** the fixation area is a fraction of the frame, so it covers a different visual angle on each
  device (Varjo, Pupil Core, Neon scene cameras have different FOVs), and the paper does not give its size.
- **Proposal:** define it in degrees per device and report the value in the paper.
- **Reference:** Eckert et al. (2022) used a fixation radius of about 16° (display width / 5) with weights 26:74.
  The 2.0 default is about 5° radius, roughly a tenth of their area, so the 65:35 and 26:74 weights are not directly
  comparable; the paper should report the radius next to the weights.
- **2.0:** the gaze circle is set as a radius in degrees (`fixation_radius_deg`, default 5.25°, equal to the previous
  Varjo default), converted to pixels with each device's vertical field of view, assuming a linear lens mapping.
- **Status:** fixed in 2.0 (the lens mapping is approximate).

---

## C. Data ingestion

### 18. Varjo CSV columns read by position
- **Where:** legacy `readPupilVarjo` / `readGazeVarjo` / `processPupilVarjo`; 2.0 `devices/varjo.py`.
- **Problem:** columns 1, 2, 6, 24–26, 34–36, 39, 43 are hardcoded. A Varjo Base update that adds or reorders
  columns would silently read the wrong data.
- **Proposal:** read by header name once a sample export is available.
- **2.0:** columns are found by header name (checked against a Varjo Base export from April 2026, which matches the
  old positions), with the old positions as a fallback. Varjo Base on Windows writes missing values as `-nan(ind)`,
  which the reader now treats as missing (the first run on real data failed on it).
- **Status:** fixed in 2.0.

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
- **Checked on the Varjo sample:** the capture shows the left eye's view. The left eye's projection and the combined
  gaze projected to the left view coincide; the right eye's projection is offset (it is in the right view).
  2.0 now uses the combined gaze (both eyes) by default; "left" and "right" remain options.
- **Status:** fixed in 2.0.

### 21. Video frame index assumes constant frame rate
- **Where:** `readGazeVarjo` (`frame_n = int(t / (1 / fps))`); 2.0 `video.analyse_video`.
- **Problem:** if the capture is variable frame rate or starts at an offset, gaze samples drift away from the
  frames they belong to.
- **Proposal:** use the container's frame timestamps (`CAP_PROP_POS_MSEC`) and check on a sample.
- **Confirmed on the Pupil Core sample:** the scene camera's real capture times (`world_timestamps.npy`) have a
  0.23 s gap at the start and jitter, while the MP4's own timestamps are perfectly regular. A fixed 30 fps mapping
  assigned every gaze sample to the wrong frame, by up to 24 frames (0.8 s).
- **2.0:** readers can supply recorded frame timestamps; gaze samples are then matched to the nearest frame, which
  agrees with Pupil Player's `world_index` for 100 % of the sample's gaze samples. Varjo still uses the frame rate.
- **Varjo sample:** H.264 at a steady 30 fps (all frame intervals 33.33 ms), and gaze timestamps are relative to the
  first video frame, so frame-rate timing is correct for Varjo.
- **Status:** fixed in 2.0.

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
- **2.0:** ported from master: average luminance = (1.706061 · lux + 0.66935) / 2.2 sr, with the three constants
  editable as "lux sensor" parameters. For a uniform field seen by a sensor with half-angle θ, E = π·L·sin²θ
  (L ≈ E / 0.79 for the 60° sensor field of view in the 2021 paper), which differs from dividing by 2.2; the origin
  of the calibration line should still be documented.
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

### 27. Pupil size depends on gaze angle
- **Where:** all devices; not corrected anywhere.
- **Problem:** camera-based eye trackers under-measure the pupil when the eye looks away from the camera
  (pupil foreshortening; Hayes & Petrov 2016, Petersch & Dierkes 2021, cited by Eckert et al. 2022). With fixed eye
  cameras this adds a gaze-dependent error to the measured PD, which could be mistaken for workload in tasks with
  systematic gaze shifts.
- **Proposal:** check its size on Varjo data (ΔPD against gaze eccentricity during steady light); if relevant, add a
  per-device correction as a function of gaze angle, or report gaze distributions per condition.
- **Status:** open.

### 28. ΔPD is relative, not absolute
- **Where:** interpretation of results.
- **Note:** Eckert et al. (2022) also conclude that PLR-corrected pupil sizes only show relative changes and require a
  baseline without task load. This supports "baseline" alignment and reporting in SD units, and is worth citing where
  the paper discusses absolute vs relative ΔPD.
- **Status:** open (paper).

### 29. Master combines the lux sensor and camera differently from the 2021 paper
- **Where:** master `lum_analysis.py` (`useCamera`): Lmin = lux / (10 · frame + 1), Lmax = 11 · Lmin, and the
  result is halved.
- **Problem:** the published method (Pignoni et al. 2021, eq. 5-8) is Lmax = avgL / avgRL, Lmin = 0,
  L = Lmax · aoiRL. The two give different absolute luminances.
- **2.0:** implements the paper's equations with the gaze-weighted relative luminance: L = avgL · rL_w / rL_frame.
  Master's heuristic is not reproduced; add it as an option if results must match 1.x.
- **Status:** open (confirm which is intended).

### 30. Master pooled both eyes and used pixel diameters for Pupil Core
- **Where:** master `processPupil` (column 6 = 2D diameter in px, eye0 and eye1 rows in one series).
- **2.0:** eyes are kept separate (eye0 = right, eye1 = left) and combined per sample; the 3D model's diameter in mm
  is used when available, pixels (scaled by the 2021 ratio method) otherwise.
- **Status:** changed in 2.0 (results differ from 1.x).

### 31. Calibration step length differs from the paper
- **Where:** the Varjo sample recording (April 2026).
- **Observation:** the 20-step sequence uses 10 s steps (200 s, starting 16.4 s into the recording), and the last
  blue step stays on for another 26 s; the paper describes 6 s steps (120 s). Recorded colour levels are also below
  nominal (grey 255 → 253, red 255 → 231) because of the capture pipeline and compression.
- **2.0:** "Find in recording" locates the sequence from the analysed video, rescales its timing to the recording's
  step length and sets the start. The paper should state the step length used.
- **Status:** open (paper).

### 32. The Neon reader is written from the documentation only
- **Where:** `cwtool/devices/neon.py`, from the Pupil Labs data format page and `pl-neon-recording` (September 2026).
- **To check on a real recording:** the column names of the Pupil Cloud export (older exports had a single
  `pupil diameter [mm]` column, which is read for both eyes); recordings with several sections (only the longest
  is analysed); the native `eye_state` record layout when there is no `.dtype` file (left diameter at field 0,
  right at field 7); multipart scene videos (only the longest part is analysed); the 0.1 s padding around
  Cloud blinks.
- **Status:** needs data.

### 33. Glasses trackers' scene camera field of view comes from a pinhole model
- **Where:** `devices/common.pinhole_fov`, used by the Pupil Core and Neon readers.
- **Problem:** both scene cameras have wide-angle lenses with strong distortion. The pinhole field of view from the
  camera matrix is the view near the image centre (e.g. about 80° instead of Neon's nominal 103° horizontal), and
  it is what converts the gaze circle radius from degrees to pixels. It is right for a gaze circle near the centre
  and increasingly wrong towards the edges. The adapting field used by Watson & Yellott is unaffected (it is the
  binocular visual field).
- **Proposed:** undistort the gaze point and circle with the distortion coefficients, which both devices provide.
- **Status:** open.

### 34. Clocks of the Neon phone and the lux logger
- **Where:** Neon timestamps are UTC from the Companion phone's clock (NTP); the lux logger stamps readings with
  the computer's clock, or the Arduino's real-time clock.
- **Problem:** any offset between the clocks shifts the lux signal against the pupil. Pupil Core has the same issue
  (its system time comes from the recording computer, usually the same one that runs the logger).
- **2.0:** compensate with the time lag parameter, as in 1.x. Pupil Labs recommend forcing a time server sync on the
  phone and the computer before a session (offsets under 10 ms, drifting to about 1 s over 24 hours); the
  procedure is in the Neon documentation page. Logging an event visible to both (a light switched on in front of
  the sensor and the camera) would let the offset be measured.
- **Status:** open.

### 35. Fixed-exposure camera as a luminance meter
- **Where:** `pipeline.prepare` (camera exposure "fixed") and `pipeline.calibrate_camera`.
- **Assumptions:** (a) the camera's gain is fixed along with its exposure time; Neon's manual mode sets the exposure
  time, and whether the gain also stays fixed is not documented. (b) After decoding with the gamma parameter, pixel
  values are proportional to luminance; the scene cameras' tone curves are not published, and the one gamma
  parameter serves both the display and the camera. (c) Lens vignetting darkens the edges of wide-angle images, so
  a gaze area near the edge reads darker than it is. (d) The full-scale value scales inversely with exposure time.
  (e) The lux sensor and the camera see comparable parts of the scene when calibrating.
- **To check:** record a static scene at two exposure times with the lux sensor: the calibrated full-scale values
  should differ by the exposure ratio, with a small spread in each. A grey card at the image centre and edge would
  measure vignetting.
- **Status:** needs data.

### 36. Display photometry and participant sensitivity cannot be separated on one sequence
- **Where:** manual calibration in 1.x (Lmin, Lmax, gains, gamma per participant); Table 2a.
- **Problem:** Watson & Yellott depend on luminance × field area only, so a brighter display and a more sensitive
  participant give identical pupils; with the Varjo pupil scale also unknown, per-participant Lmax values mix the
  two. This is a likely reason for the 1500–6500 cd/m² spread of calibrated Lmax in Table 2a on one headset.
- **2.0:** the display photometry (Lmin, Lmax, gamma) is the user's nominal description of the headset, kept in its
  own file; each participant gets a fitted light sensitivity (a factor on luminance) and channel weights. The
  sensitivity includes any common error of the display photometry, so sensitivities are comparable only between
  participants calibrated with the same display photometry. Old participant files keep their Lmin/Lmax/gamma and
  reproduce their results.
- **Open:** if the headset can be measured later, the sensitivities become absolute; a pooled fit over several
  participants could also estimate a common display correction.
- **First real recording (Varjo XR-4, April 2026, default display photometry Lmin 0.02, Lmax 70 cd/m², γ 2.2):**
  - sequence at 16.4 s with 10 s steps; ΔPD RMS in the sequence 0.517 mm with defaults, 0.358 mm with the old fit
    alone (latency 0 s), **0.146 mm** with light sensitivity, then latency from onsets, time constants, scale and
    offset;
  - latency 0.32 s (interquartile range 0.27–0.34 s, 10 onsets), constriction τ 0.20 s, dilation τ 3.7 s;
  - light sensitivity about 40 (95 % interval roughly 9–150), channel weights R 1.55, G 0.41, B 1.04, pupil scale
    correction about 0.63 (so diameter ≈ 1.26 × the reported value, rather than 2 ×);
  - the whole-trace fit clearly prefers high sensitivity: after fitting timing, scale and offset, the sequence RMS is
    0.436 mm at sensitivity 1, 0.337 at 3, 0.249 at 10 and 0.167 at 45 (photopic weights). The pupil is near its
    smallest from grey 73 upwards, which the model reproduces only in its saturated range. Sensitivity and pupil
    scale still trade off (sensitivity 10 with scale 0.94 gives 0.21 mm), so the absolute split between them is
    uncertain; ΔPD in SD units or relative to rest is unaffected.
  - The saturated colour steps constrict the pupil almost as much as white (blue 255: 2.74 mm, where photopic
    luminance predicts 3.67 mm), consistent with the melanopsin-driven pupil response; hence the wide colour prior.
- **Status:** decided (display photometry separate, sensitivity per participant); needs more participants to see how
  consistent sensitivities are; paper text to follow.

### 37. Pupil scale fitted by regressing the model on the measurement
- **Where:** 2.0 `fit.fit_calibration` (and the first version of the light sensitivity fit).
- **Problem:** fitting `k · measured + b ≈ expected` biases the scale towards zero whenever the measured pupil varies
  in ways the model does not (regression dilution): 0.40 instead of 0.62 on the April 2026 recording. In the light
  fit it also let an extreme sensitivity compress both sides.
- **2.0:** both fits map the model onto the measurement (`measured ≈ c · expected + d`, k = 1/c).
- **Status:** fixed in 2.0.

### 38. Latency fitted to 0 s
- **Where:** 2.0 `fit.fit_calibration` on the April 2026 Varjo recording (and synthetic data with re-dilation).
- **Problem:** the fit error hardly depends on latency, and re-dilation after each constriction, which the model does
  not describe, pushed the fitted latency to the lower limit.
- **2.0:** with the sequence, the latency is measured from constriction onsets (20–50 % line extended to baseline):
  0.32 s on that recording.
- **Status:** fixed in 2.0. The model's lack of re-dilation remains (it limits how well any response shape fits).

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
