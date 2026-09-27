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

Issues about the paper text only (10, 24, 25, 28, 31) were removed in September 2026, to be taken up when the paper
is revised; they remain in the git history of this file.

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
- **Seven participants (Varjo XR-4, calibration recordings a–g, a on 14 April and b–g on 21 April 2026):** video
  re-analysed with the current code; default display photometry; built-in sequence located by *Find in recording*
  (10 s steps, colour match error 9–10 %), except e, placed at 1.8 s by hand (issue 39); then *1. Fit light
  sensitivity* (channel weights, gamma fixed) and *2. Fit latency, scale and offset* (with time constants), as the
  app runs them. a is the recording above; with the new video analysis it gives sensitivity 38 and 0.150 mm.

  | | sensitivity (95 %) | weights R/G/B | light RMS | latency (onsets) | τ dil. / constr. | scale k (diam. / reported) | offset | ΔPD RMS default → light → both |
  |---|---|---|---|---|---|---|---|---|
  | a | 38 (9.5–153) | 1.54 / 0.40 / 1.06 | 0.37 | 0.32 s (10) | 3.9 / 0.21 s | 0.63 (1.25) | +0.63 | 0.517 → 0.250 → 0.150 |
  | b | 0.0063 (0.0010–0.039) | 0.56 / 0.08 / 2.35 | 1.11 | 0.34 s (14) | 1.6 / 0.17 s | 0.94 (1.89) | +3.59 | 0.734 → 0.602 → 0.487 |
  | c | 8.1 (2.0–33) | 0.31 / 0.20 / 2.49 | 0.38 | 0.31 s (13) | 3.2 / 0.09 s | 0.78 (1.57) | +0.53 | 0.517 → 0.384 → 0.213 |
  | d | 0.27 (0.069–1.1) | 0.25 / 0.23 / 2.53 | 0.68 | 0.30 s (14) | 2.8 / 0.15 s | 1.25 (2.49) | −0.21 | 0.662 → 0.604 → 0.506 |
  | e | 5.7 (1.4–23) | 0.68 / 0.05 / 2.27 | 0.77 | 0.26 s (9) | 2.1 / 0.22 s | 0.92 (1.84) | −0.16 | 0.698 → 0.470 → 0.352 |
  | f | 39 (8.0–191) | 0.54 / 0.42 / 2.05 | 0.75 | 0.36 s (14) | 5.4 / 0.13 s | 0.73 (1.47) | +0.40 | 0.720 → 0.302 → 0.188 |
  | g | 0.044 (0.0085–0.23) | 0.37 / 0.37 / 2.27 | 0.51 | 0.27 s (14) | 3.4 / 0.12 s | 0.66 (1.31) | +2.21 | 0.834 → 0.440 → 0.322 |

  Light RMS: steady-state levels after the light fit, mm. Offset in mm on the model's scale. Fitted with the
  sensitivity prior, since removed (issue 42): without it the sensitivities are a 48.5, b 0.0022, c 9.5, d 0.49,
  e 9.0, f 57, g 0.049 (d from its later video analysis, scene circle radius 0.95), and the spread is the same. e lost tracking in most
  red and blue steps (64 % valid samples): 3 steps skipped, 9 onsets.

  - **Latency is consistent:** 0.30–0.36 s in the six complete recordings (0.26 s in e), the same with the step
    estimator below; constriction τ 0.09–0.22 s, dilation τ 1.6–5.4 s. Every participant also has 1–3 negative
    onsets (issue 41).
  - **Channel weights are consistent:** blue weighs 2.0–2.5 and green least (0.05–0.42) in b–g; a, the only
    recording from another day, is the exception (R 1.54, B 1.06).
  - **Sensitivity is not:** it spans four orders of magnitude (0.006–39), and the 95 % intervals of b, g and d do not
    overlap those of a and f. Profiling the light fit over fixed sensitivities (weights, scale and offset refitted):
    between 0.1 and 10, χ² changes by only 11 for b and 14 for d, against 35–190 for the others. The intervals are
    also too narrow: the steady-state residuals (0.55–1.25 mm in the profile) are far above the 0.1 mm noise the
    fit assumes, i.e. the model does not describe the steps within their stated uncertainty.
  - **Most steps are extrapolated:** 11–18 of 20 steps per participant had not settled, and the extrapolated
    levels are often implausible (issue 40). With each step's level taken as the mean of its last 30 % instead, the
    light-fit RMS falls to 0.13–0.32 mm (b 0.62), but the sensitivities still spread: a 43, b 0.76, c 2.9, d 0.050,
    e 7.4, f 105, g 0.033. So extrapolation adds noise but does not explain the spread.
  - **What the sensitivity follows:** the grey staircase. a and f flatten from grey 109 upwards (high sensitivity);
    d and g still shrink at 219–255 (low sensitivity). Because the greys ascend in time, that flattening also
    coincides with 30–80 s into the sequence, so adaptation or re-dilation cannot be told from sensitivity with this
    order.
  - **Sensitivity, scale and offset trade off:** the low sensitivities come with large positive offsets (b +3.6,
    g +2.2 mm; with the step means d +1.4, g +2.6), i.e. a model pupil 1.4–3.6 mm larger than measured. The light fit
    has no prior on the offset. The scale k ranges 0.63–1.25 (diameter 1.25–2.5 × the reported value), so these data
    do not settle the device scale (issue 1) per participant either.
  - ΔPD RMS in the sequence improves for everyone (0.52–0.83 → 0.15–0.51 mm), least for b and d, whose steps the
    model fits worst.
- **Proposal:** do not compare sensitivities between participants yet. Options, in order of effort:
  - a prior on the offset in the light fit (it should be near 0 once the scale is fitted);
  - one sensitivity pooled over all participants of a headset, with only weights, scale and offset per participant
    (the "Open" point above);
  - a pseudo-random step order (Eckert et al., 2022) so that luminance is not confounded with time, and a dark
    step between colours;
  - fix the step level estimator (issue 40).
- **Status:** decided (display photometry separate, sensitivity per participant); the per-participant sensitivity is
  not reliable on the current sequence (seven participants, September 2026); paper text to follow.

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

### 39. Find in recording accepts a sequence that runs past the end of the recording
- **Where:** 2.0 `calibration.locate`.
- **Problem:** a candidate start is scored only on the part of the sequence inside the recording. On calibration
  recording e (September 2026), where tracking, and so the video analysis, is missing during most red and blue steps,
  the true start (1.8 s, 10 s steps) scores 25 % because the gaps are interpolated. A start at 159.9 s with 6 s steps
  scores 18 %: its window runs to 280 s in a 206 s recording, and the 46 s inside happen to match. The app accepts
  anything below 35 %, so the wrong start is set silently.
- **2.0:** a candidate must lie within the recording, give or take its first and last step; only times within
  0.5 s of an analysed video sample are scored, and at least half of the window must have one. Recording e is now
  found at 1.74 s with 10 s steps (error 9.5 %, 70 % of the sequence analysed); the other six starts are unchanged.
  The status bar reports the share of the sequence in tracking gaps.
- **Status:** fixed in 2.0.

### 40. Step levels extrapolated from unsettled steps are unstable
- **Where:** 2.0 `photometry.step_asymptote`, which gives the light sensitivity fit one level per step.
- **What it does:** a step counts as settled when the pupil changes by less than 0.1 mm over its last 30 %; its level
  is then the mean of that part. Otherwise an exponential is fitted from the step's turning point to its end and its
  asymptote used, capped at 1 mm beyond the last second, with half the extrapolated distance added to the step's
  uncertainty.
- **On the seven calibration recordings** (September 2026, current code, no sensitivity prior):
  - 104 of 137 steps (76 %) count as unsettled: all first steps, 82 of 109 after a brighter step, 15 of 21 after a
    darker one;
  - the direction does not follow the physiology: after brightening, 40 unsettled steps are still dilating and 42
    still constricting, where re-dilation (issue 43) would make most of them dilate. The 0.1 mm criterion is at the
    level of the pupil's own fluctuation within a step (0.08–0.24 mm RMS, issue 43), so a random wobble over the
    last 3 s is often taken for a trend and extrapolated;
  - the extrapolation reaches a median 0.34 mm beyond the last second, and 35 % of unsettled steps hit the 1 mm cap;
    the extrapolated levels differ from the end-of-step means by a median 0.41 mm;
  - 33 of 137 steps (2–7 per participant, 7 of 20 in f and g) get an uncertainty above 1 mm, which silently drops
    them from the fit;
  - grey levels go the wrong way (a brighter grey with a larger level, by more than 0.05 mm) 11 times, against 6
    with end-of-step means.
- **Effect on the light fit** (extrapolated levels → mean of each step's last 30 %):

  | | sensitivity (95 %) | steady-state RMS | weights R/G/B | scale k |
  |---|---|---|---|---|
  | a | 48.5 (11–210) → 52.7 (14–190) | 0.342 → 0.123 mm | 1.55/0.41/1.04 → 1.45/0.56/0.99 | 0.60 → 0.61 |
  | b | 0.0022 (0.0004–0.013) → 1.0 (0.18–5.6) | 0.906 → 0.605 mm | 0.55/0.08/2.37 → 0.67/0.09/2.24 | 0.92 → 1.15 |
  | c | 9.5 (2.1–42) → 3.2 (0.91–11) | 0.363 → 0.149 mm | 0.31/0.19/2.49 → 0.48/0.28/2.25 | 0.60 → 0.75 |
  | d | 0.49 (0.11–2.1) → 0.078 (0.029–0.21) | 0.608 → 0.207 mm | 0.25/0.25/2.50 → 0.42/0.16/2.41 | 0.92 → 0.98 |
  | e | 9.0 (2.0–41) → 9.9 (2.3–44) | 0.723 → 0.297 mm | 0.69/0.04/2.27 → 0.36/0.05/2.59 | 0.93 → 0.91 |
  | f | 57 (11–300) → 142 (33–610) | 0.678 → 0.160 mm | 0.53/0.41/2.06 → 0.48/0.26/2.26 | 0.81 → 0.57 |
  | g | 0.049 (0.010–0.23) → 0.031 (0.009–0.10) | 0.496 → 0.278 mm | 0.38/0.42/2.20 → 0.47/0.31/2.22 | 0.56 → 0.58 |

  The model fits the end-of-step levels much better (33–78 % lower RMS) and the channel weights hardly change (blue
  still dominant). The sensitivity moves by up to a factor of 460 (b) and still spreads over four orders of
  magnitude (0.03–142): the estimator adds noise but is not what makes sensitivities incomparable (issue 36).
- **What the end-of-step mean gives up:** a step that really had not settled (slow dilation after darkening, dilation
  τ 2.7–9.6 s in issue 43) is read short of its steady state, biased towards the previous level. With 10 s steps
  and τ above 3 s this is a real bias, but a consistent and bounded one, unlike the extrapolation.
- **Proposal:**
  - now: use the mean of the step's end (e.g. the last 30 %), and flag steps whose trend is both beyond the noise
    and in the direction the dynamics predict (dilating after darkening) instead of extrapolating them;
  - with the new calibration sequence: longer steps, or a dark/dim step before each measured one, so that the end of
    a step is near its steady state; the extrapolation then becomes unnecessary;
  - later, with step 4 of issue 43: fit the light response on the whole trace with the dynamics, which needs no
    per-step levels at all.
- **2.0 (September 2026):** the level is the mean of the step's last 30 %, never extrapolated; only a step still
  dilating by more than 0.1 mm at its end after a darker step is flagged (its level is short of the steady state),
  with half that trend added to its uncertainty. On a–g 1–3 steps per participant are flagged, all darkening steps
  (grey 0 and the first, dimmest step of each hue).
- **Effect on the whole calibration** (same data and fits, old estimator → new; ΔPD RMS in the sequence after both
  fits, two constriction stages without and with the transient):

  | | sensitivity | two stages | two stages + transient |
  |---|---|---|---|
  | a | 48.5 → 50.9 | 0.140 → 0.142 | 0.132 → 0.132 |
  | b | 0.0022 → 0.017 | 0.382 → 0.583 | 0.348 → 0.529 |
  | c | 9.46 → 1.57 | 0.209 → 0.239 | 0.182 → 0.199 |
  | d | 0.491 → 0.103 | 0.502 → 0.427 | 0.424 → 0.345 |
  | e | 9.04 → 10.1 | 0.333 → 0.308 | 0.296 → 0.264 |
  | f | 57.2 → 48.3 | 0.165 → 0.174 | 0.142 → 0.148 |
  | g | 0.0489 → 0.0499 | 0.334 → 0.305 | 0.270 → 0.240 |

  Better for d, e and g, equal for a, worse for c, f and markedly for b, the participant the model fits worst
  (0.68 mm on its step levels). The light fit is judged on the step levels and the result on the whole trace, and
  while the model misses the step levels by 0.2–0.7 mm (issue 43) a cleaner level estimate does not guarantee a
  better whole-trace fit; the extrapolation's wins look accidental (it fitted fluctuations). Kept for being
  principled and robust; step 4 of issue 43 (fitting on the whole trace) would remove the mismatch.
- **Status:** fixed in 2.0 (estimator); longer or dark-preceded steps in the new sequence remain useful.

### 41. Negative constriction onsets are accepted
- **Where:** 2.0 `fit.onset_latency`.
- **Problem:** 14 of the 87 onsets measured on the seven calibration recordings are between −0.2 and −0.7 s, 1–3
  per participant: the pupil starts constricting before the display changes, which a reflex cannot do. They occur
  at brightening steps of every kind (mostly within a colour, e.g. red 191 → 255, blue 64 → 128; in e also grey
  73 → 109 and 109 → 146), and their constrictions are not small (median 1.07 mm, against 0.85 mm at the others).
- **What the pupil does:** averaged over these steps, it is steady until about 0.5 s before the change, then starts
  constricting: 0.25 mm down at the moment of the change, when the pupil at normal steps has not moved yet. By 1 s
  both reach the same depth. So it is an early constriction, not a slow drift under a flat baseline.
- **Ruled out:**
  - the timing of the change: the detected video change is within 0.09 s of the nominal one at these steps, as at
    the others;
  - drift between the video and gaze clocks (the Varjo video is timed by its frame rate): the video's length
    (frames / 30 fps) matches the gaze span within 0.05 s in every recording, and onsets do not shrink over the
    recording in a, c, d, e and f (slopes within ±0.07 s per 100 s);
  - tracking gaps: 1.9 % of the 3 s before these changes lack pupil data, against 1.5 % before the others.
- **Likely cause: anticipation.** The steps change every 10 s in a fixed, ascending order, so each change is
  predictable. Negative onsets cluster late in the sequence (11 of 46 steps in its second half, 3 of 41 in the first),
  and in g the onsets grow earlier as the sequence goes on (median 0.34 s in the first half, 0.20 s in the second;
  −0.34 s per 100 s), as the participant learns the rhythm. Pupil constriction in anticipation of expected light is
  documented, but these data cannot prove it; a sequence with irregular step lengths would.
- **Effect on the latency:** small, because the median is robust. Leaving the negative onsets out moves the median
  by at most 0.04 s (e 0.26 → 0.30 s, g 0.27 → 0.31 s, c 0.32 → 0.34 s, others ≤ 0.01 s), but the reported
  interquartile ranges shrink markedly (e −0.19–0.34 → 0.26–0.38 s, g 0.20–0.34 → 0.23–0.35 s). Anticipated steps may
  also bias the rest of the fit, as the model cannot constrict before the light does.
- **Proposal:**
  - now: discard onsets below a physiological floor (0.1 s; the shortest pupil latencies reported are about 0.2 s)
    and report how many were discarded;
  - with the new calibration sequence: irregular step lengths (e.g. 7–13 s) and a less predictable order, to remove
    anticipation and test whether it was the cause;
  - later, with a model of re-dilation (issue 43): measure onsets against the model's predicted continuation rather
    than a flat level.
- **Status:** open; part of the dynamics model (issue 43) and the new calibration sequence.

### 42. The sensitivity prior breaks the display–sensitivity equivalence
- **Where:** 2.0 `photometry.fit_light_response` (`PRIOR_LOG_SENSITIVITY`);
  `tests/test_photometry.py::test_display_error_is_absorbed_by_the_sensitivity`, which fails on `v2.0`.
- **The equivalence:** the model sees luminance only through `sensitivity · L`, and `L` scales with the display
  photometry (Lmin, Lmax). Doubling the datasheet luminance and halving the sensitivity gives identical predictions,
  so the data alone cannot tell them apart. The docs rely on this: "doubling the datasheet luminance halves the
  fitted sensitivity and leaves the predictions unchanged", which is why sensitivities absorb any common error of
  the display photometry and are comparable between participants measured with the same photometry.
- **What breaks it:** the fit adds a weak prior, `log(sensitivity) / log(10)`, to keep poorly determined values
  near 1. The centre, sensitivity 1, means "the display photometry is right", so it depends on what the user enters:
  with the luminance doubled the same participant is pulled towards a different effective luminance. The fit is
  then no longer equivariant, and the prior shifts the sensitivity by different amounts at the two photometries.
- **Size:** on the synthetic test participant the ratio is 1.93 instead of 2 and the predictions differ by up to
  0.021 mm (tolerance 0.02 mm). On the seven calibration recordings (default photometry against doubled):

  | | with prior: s, ratio, max Δ prediction | flat: s, ratio | steady-state RMS, prior → flat |
  |---|---|---|---|
  | a | 38.1 / 19.9, 1.92, 0.024 mm | 48.5 / 24.3, 2.00 | 0.368 → 0.342 mm |
  | b | 0.0049 / 0.0027, 1.80, 0.060 mm | 0.0022 / 0.0011, 2.00 | 1.098 → 0.906 mm |
  | c | 8.03 / 4.22, 1.90, 0.028 mm | 9.46 / 4.73, 2.00 | 0.377 → 0.363 mm |
  | d | 0.522 / 0.277, 1.88, 0.037 mm | 0.491 / 0.246, 2.00 | 0.607 → 0.608 mm |
  | e | 7.35 / 3.92, 1.88, 0.037 mm | 9.04 / 4.52, 2.00 | 0.750 → 0.723 mm |
  | f | 39.0 / 20.8, 1.87, 0.033 mm | 57.2 / 28.6, 2.00 | 0.752 → 0.678 mm |
  | g | 0.053 / 0.027, 1.97, 0.011 mm | 0.049 / 0.024, 2.00 | 0.501 → 0.496 mm |

  (d with its current video analysis, scene circle radius 0.95.) The prediction differences are small, but the prior
  also moves the sensitivity itself by up to a factor of 2.2 (b) and 1.5 (f), always towards 1, so a participant's
  value depends on the datasheet luminance through the prior as well as through the equivalence. With a flat prior
  the equivalence is exact, every fit stays inside its range (none reaches the 0.001–1000 limits), and the fit to the
  steady states is as good or better.
- **Options:**
  1. **Flat prior on the sensitivity** (keep the range and the "reached the limit" note): exact equivalence, the
     test passes as written. Sensitivities then rest on the data alone, which issue 36 shows are weak for some
     participants (b, d); their values are uncertain either way, and the reported interval says so.
  2. **Keep the prior, state the equivalence as approximate:** relax the test and the docs. Sensitivities stay
     shrunk towards "the datasheet is right", by an amount that depends on the datasheet.
  3. **Centre the prior on the headset, not on 1:** e.g. on the median sensitivity of the other participants
     calibrated with the same display photometry (the pooled fit proposed in issue 36). The centre scales with the
     photometry, so the equivalence is exact, and weak fits are still stabilised, by a meaningful value.
- **2.0:** option 1 (September 2026): the sensitivity has no prior, only its range and the note when it reaches a
  limit. Doubling the display luminance now halves the fitted sensitivity exactly and the test passes; the synthetic
  participant (sensitivity 3) is recovered as 2.9 instead of 2.7. Option 3 is not planned.
- **Status:** fixed in 2.0.

### 43. The dynamic model cannot describe the measured step responses
- **Where:** 2.0 `model.delay` and `model.attack_release`: the Watson & Yellott steady state, delayed, through a
  one-pole filter with separate dilation and constriction time constants.
- **Problem:** this model moves monotonically from one steady state to the next. On the 91 brightening and 20
  darkening steps of the seven calibration recordings (issue 36):
  - the pupil constricts by 0.83 mm (median), reaching its minimum 1.0 s after the change, then re-dilates by
    0.43 mm, 59 % of the constriction, within the 10 s step; in 16 % of the brightening steps it ends larger than
    before the change ("pupillary escape");
  - dilation has a fast and a slow phase: 0.71 mm in the first 3 s, then another 0.49 mm by the end of the step;
  - the onset of the constriction is gradual (S-shaped), while a one-pole filter starts at full speed, so the fitted
    constriction τ (0.09–0.22 s) and the delay share the shape of the onset between them;
  - the latency does not depend on the step size (r = 0.06 with the log luminance ratio), so a fixed delay is enough.
  Because of the re-dilation and slow dilation the steady states per step must be extrapolated (issue 40), onsets
  are read against a moving baseline (issue 41), and the whole-trace fit leaves residuals the parameters then absorb.
- **Proposal:** in order of expected gain:
  1. a transient pathway: a constriction proportional to increases in log luminance that decays with an escape time
     constant of a few seconds, added to the sustained response (two parameters);
  2. dilation as the sum of a fast and a slow one-pole (one more time constant and a share);
  3. a second-order (two-pole) constriction, so the delay is the true latency and the onset is S-shaped;
  4. with such a model, fit the light sensitivity on the whole trace together with the dynamics, instead of from
     per-step steady states (removing issue 40), and fit the latency from the model's prediction around each change
     (removing issue 41).
  The new calibration sequence should allow these to be identified: irregular step lengths, return-to-dark steps,
  and some long steps.
- **2.0, step 1 (transient pathway):** with `transient` above 0 the expected pupil is reduced by
  `transient · h / (h + 0.2)`, where `h` is the increase of log luminance over its low-pass with time constant
  `escape` (only increases), delayed like the rest and smoothed with the constriction τ. A transient proportional to
  `h` fitted poorly: the measured escape saturates with the step size (0.25 mm at 0.1 log units, 0.31 at 0.2, 0.43 at
  0.45, 0.52 at 1), so a gain matching small steps overshoots large ones (fitted escape τ collapsed to 0.2–0.5 s or ran
  to 20–30 s). A fitted half-saturation varied from 0.03 to 0.41 between participants without improving the fit, so
  it is fixed at 0.2. Step 2 of the calibration fits `transient` and `escape` optionally. On a–g (light sensitivity
  fit first, latency from onsets, then time constants, scale and offset without → with the transient):

  | | ΔPD RMS in sequence | RMS 0–4 s after brightening | residual at 1 s | transient | escape τ | constr. τ |
  |---|---|---|---|---|---|---|
  | a | 0.150 → 0.143 | 0.151 → 0.129 | −0.12 → +0.02 | 1.15 mm | 0.30 s (limit) | 0.21 → 0.76 s |
  | b | 0.462 → 0.420 | 0.416 → 0.325 | −0.46 → −0.02 | 0.91 mm | 1.13 s | 0.17 → 0.30 s |
  | c | 0.214 → 0.186 | 0.253 → 0.190 | −0.41 → −0.05 | 0.81 mm | 0.73 s | 0.09 → 0.22 s |
  | d | 0.501 → 0.424 | 0.604 → 0.470 | −0.83 → −0.22 | 1.71 mm | 1.07 s | 0.15 → 0.48 s |
  | e | 0.346 → 0.308 | 0.403 → 0.330 | −0.47 → −0.11 | 1.03 mm | 1.42 s | 0.23 → 0.49 s |
  | f | 0.188 → 0.160 | 0.184 → 0.139 | −0.24 → −0.02 | 0.43 mm | 1.07 s | 0.13 → 0.25 s |
  | g | 0.336 → 0.272 | 0.343 → 0.278 | −0.48 → −0.16 | 1.16 mm | 7.16 s | 0.12 → 0.17 s |

  Residual: mean measured − expected relative to the second before brightening steps, mm. Every participant
  improves; the dip at 1 s is mostly removed. The whole-sequence gain is limited because the dip lasts 1–3 s of each
  10 s step. Latency (from onsets), pupil scale (−0.06 to 0) and offset barely change.
- **What it does not yet separate:** the constriction τ rises in every participant (to 0.17–0.76 s): a transient
  that decays quickly, smoothed by a slower constriction, forms the dip, and together they also reshape the
  constriction onset, which step 3 (a two-pole constriction) is meant to model. In a, which has almost no dip, the
  escape τ ends on its lower limit and the transient only does that. In g the escape τ (7.2 s) and dilation τ (3.6 →
  9.6 s) trade off. The transient and escape values are therefore not yet physiological estimates.
- **2.0, step 3 (two-stage constriction):** with `constriction_stages` = 2 a second stage with the constriction τ
  acts during constriction only, so it starts gradually; the transient gets the same smoothing. The latency from
  onsets is corrected by where the 20–50 % construction puts the model's own onset (−0.09 τ for one stage, +0.25 τ for
  two), so `delay` is the latency to the first movement; this also moves one-stage latencies by +0.01–0.02 s.
  On a–g (same light fits; one or two stages, without or with the transient):

  | | ΔPD RMS 1 → 2 stages | with transient 1 → 2 | latency 1 → 2 stages (transient) | constr. τ with transient 1 → 2 | transient, escape τ with 2 stages |
  |---|---|---|---|---|---|
  | a | 0.150 → 0.150 | 0.146 → 0.141 | 0.36 → 0.28 s | 0.94 → 0.18 s | 0.35 mm, 0.55 s |
  | b | 0.463 → 0.463 | 0.421 → 0.421 | 0.36 → 0.29 s | 0.28 → 0.16 s | 0.89 mm, 1.15 s |
  | c | 0.214 → 0.214 | 0.186 → 0.185 | 0.33 → 0.28 s | 0.20 → 0.12 s | 0.77 mm, 0.76 s |
  | d | 0.501 → 0.501 | 0.424 → 0.423 | 0.33 → 0.24 s | 0.41 → 0.21 s | 1.47 mm, 1.22 s |
  | e | 0.346 → 0.345 | 0.309 → 0.307 | 0.29 → 0.20 s | 0.43 → 0.24 s | 0.93 mm, 1.53 s |
  | f | 0.188 → 0.187 | 0.160 → 0.160 | 0.38 → 0.33 s | 0.22 → 0.13 s | 0.41 mm, 1.12 s |
  | g | 0.336 → 0.336 | 0.272 → 0.272 | 0.29 → 0.24 s | 0.16 → 0.13 s | 1.16 mm, 7.17 s |

  - The RMS hardly changes: the onset shape occupies a few hundred milliseconds per step.
  - With the transient, two stages remove the trade-off noted above: the constriction τ per stage falls back to
    0.12–0.24 s, and in a the transient no longer ends on a limit (0.35 mm, escape 0.55 s instead of 1.41 mm with
    escape on its 0.3 s limit and τc 0.94 s). The residual 0.5 s after brightening steps is closer to 0 in a, b, c, f
    and g (g +0.13 → +0.03 mm) and slightly further in d and e (−0.08 → −0.11, −0.13 → −0.15 mm).
  - Latency is 0.20–0.33 s with two stages instead of 0.29–0.38 s: the onset lies after the true start of a gradual
    constriction.
  - In g, escape τ (7.2 s) and dilation τ (9.6 s) still trade off; that is step 2 (two-phase dilation).
- **Status:** steps 1 (transient) and 3 (two-stage constriction) done, both optional and off by default; steps 2
  and 4 open.
- **What remains (September 2026)**, with two stages and the transient fitted on a–g:
  - after brightening, the mean residual is gone (within ±0.06 mm at every time from 0.5 to 9.5 s);
  - after darkening, the pupil still dilates later than the model: −0.12, −0.15 and −0.13 mm at 0.5, 1 and 1.5 s,
    fading by 4 s (a delayed dilation onset rather than a missing slow phase); but only 20 darkening steps exist
    (about 3 per participant), and their first 4 s hold 3–17 % of the remaining squared error;
  - the error is spread roughly in proportion to time: 18–38 % in the 4 s after brightening (32 % of the time),
    3–17 % after darkening (6 %), 50–74 % in the settled rest of the steps (62 %);
  - in the settled parts, 46–86 % of the error is a constant offset per step (a wrong step level), the rest
    fluctuation within the step (0.08–0.24 mm RMS, which no light model predicts);
  - the per-step offsets (SD 0.11–0.38 mm) follow neither time in the sequence (a linear drift explains 2–36 %) nor
    the step's hue (9–59 %, after the fitted channel weights); they jump irregularly from step to step (b +1.35 mm at
    grey 0; g −0.39 at grey 0, +0.41 at grey 36). With each colour shown once, in a fixed order, a reproducible model
    error cannot be told from the participant's state at that moment.
- **What this means for the open steps:**
  - step 2 (two-phase dilation): the data point to a delayed dilation onset (a dilation latency, or two stages on
    dilation as well) more than to a second slow phase, and the possible gain is small (the darkening phases hold
    3–17 % of the error). It needs a sequence with many more darkening steps; until then it is not worth fitting.
  - step 4 (fit the light response with the dynamics on the whole trace): the largest remaining error is in the step
    levels, which step 4 targets. It would also replace the extrapolated steady states (issue 40). But if the
    offsets are state fluctuations rather than model error, no fit removes them; the new sequence should show each
    colour at least twice, in different orders, so the two can be separated.
- **For the new calibration sequence:** each level at least twice, in a pseudo-random order; irregular step lengths
  (anticipation, issue 41); several returns to dark or to a dim level (dilation); some long steps (slow phases,
  issue 40).
- **Switch (September 2026):** the transient is applied only with `dynamics` on, together with the time constants
  and constriction stages, and the app fits it whenever it fits the dynamics (one option). A parameter file with
  `transient` above 0 and `dynamics` off now leaves the transient out.

### 44. Reference age exposed as a participant setting
- **Where:** 2.0 `Parameters.reference_age` and the parameter panel (until September 2026).
- **Problem:** \(y_0\) = 28.58 years in Watson & Yellott's age correction is the mean age of the observers behind the
  Stanley & Davies formula, a constant of the model; 1.x hard-codes it. Exposing it invited changing it per
  participant.
- **2.0:** `model.REFERENCE_AGE`; removed from the parameters and the panel. Parameter files that still carry
  `reference_age` load (the field is ignored); only a file with a value other than 28.58 would give different results.
- **Status:** fixed in 2.0.
