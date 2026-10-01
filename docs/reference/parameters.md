# Parameters

Two sets, both in `cwtool/params.py`.

- **`Parameters`**: everything applied after the video pass. Saved per participant as JSON from the app
  (**File → Save parameters**) and loaded with `--params`. Changing them re-runs only the fast signal pass.
- **`VideoSettings`**: the geometry of the video pass. Changing them requires re-analysing the video.

## Participant

| Name | Default | Meaning |
|---|---|---|
| `age` | 25 | participant's age (years), for Watson & Yellott |
| `eyes` | 2 | eyes adapted to the light (1 or 2) |
| `eye` | both | pupil analysed: `left`, `right` or `both` |

## Display photometry (display devices)

The headset's nominal values, e.g. from its datasheet. Saved in their own file (**File → Save display photometry…**),
not in participant files.

| Name | Default | Meaning |
|---|---|---|
| `l_min` | 0.01 cd/m² | panel black point (white over the datasheet's 10000:1 contrast) |
| `l_max` | 100 cd/m² | panel white point; warned about above 110 % of the device's claimed peak (Varjo: 200 cd/m²), [open issue 48](../OPEN_ISSUES.md) |
| `gamma` | 2.2 | decoding exponent, 1.4–3.0 |

## Participant light response

| Name | Default | Meaning |
|---|---|---|
| `sensitivity` | 1 | factor on the luminance entering Watson & Yellott; also absorbs common errors of the display photometry (fitted) |
| `gain_r`, `gain_g`, `gain_b` | 1 | channel weights for the pupil, normalised by their mean (fitted) |
| `fixation_weight` | 0.26 | weight of the gaze circle (Eckert et al. 2022; 1.x used 0.65); the background gets 1 − weight (also used with lux devices) |

## Lux sensor (glasses)

| Name | Default | Meaning |
|---|---|---|
| `lux_gain` | 1 | recalibration of the sensor's lux (1.x: 1.706061, a field-of-view correction from one test) |
| `lux_offset` | 0 | recalibration offset, lux (1.x: 0.66935) |
| `lux_solid_angle` | 2.2 | illuminance / average luminance ("Lux ÷ luminance (Ω)" in the app) for the sensor in its housing (not a solid angle; see [Lux sensor](../hardware/lux-sensor.md)) |
| `lux_use_video` | on | distribute the sensor's average over the view with the scene video |
| `lux_ratio_limit` | 10 | the video ratio (gaze-weighted / whole frame) is kept between 1/limit and limit ("Max video ratio"); 0 = no bound. A note says when it is reached in more than 5 % of the video samples |

## Scene camera without a lux log (glasses)

| Name | Default | Meaning |
|---|---|---|
| `camera_exposure` | auto | `auto`: relative luminance mapped onto Lmin–Lmax; `fixed`: the exposure was fixed, pixel values are proportional to luminance |
| `camera_white` | 1000 cd/m² | luminance at full scale (code 255) for the reference exposure; set it with **Calibrate camera from lux** |
| `camera_reference_ms` | 0 | exposure time `camera_white` refers to; 0 = the recording's |
| `camera_exposure_ms` | 0 | the recording's exposure time; full scale is scaled by reference / recording; 0 = same as the reference |

## Pupil signal

| Name | Default | Meaning |
|---|---|---|
| `pupil_correction` | 1 | participant multiplier on the device's pupil scale, set by hand and never fitted: one sequence does not determine it (it trades off with the sensitivity and the black point) |
| `alignment` | recording | offset mode: `recording`, `baseline`, `fixed`, `none` |
| `baseline_events` | Riposo, Rest, Baseline | event labels used by `baseline` alignment |
| `pupil_offset` | 0 mm | offset used by `fixed` alignment (set by hand; the fits leave it alone unless asked) |
| `timelag` | 0 s | subtracted from luminance timestamps (video and lux) |
| `analysis_rate` | 100 Hz | uniform grid rate; 0 = the device's native rate |
| `max_gap` | 0.5 s | longer gaps are left out of ΔPD |
| `max_pupil_speed` | 10 mm/s | faster changes are artefacts; 0 disables |
| `artefact_padding` | 0.05 s | removed around each artefact |

## Dynamics

| Name | Default | Meaning |
|---|---|---|
| `delay` | 0.5 s | response latency, always applied (fitted) |
| `dynamics` | on | apply the dynamics: attack/release filter, constriction stages and transient |
| `attack` | 6 s | dilation time constant (fitted) |
| `release` | 0.5 s | constriction time constant, per stage (fitted) |
| `constriction_stages` | 2 | 1: constriction starts at full speed; 2: gradually (S-shaped); files without it load as 1 |
| `transient` | 0 mm | largest transient constriction after brightening, with the dynamics; 0 = none (fitted) |
| `escape` | 2 s | re-dilation time constant of the transient (fitted) |

## ΔPD

| Name | Default | Meaning |
|---|---|---|
| `cw_window` | 0.2 s | averaging window |
| `cw_smoothing` | 1 | Savitzky–Golay half-width, in windows |

## Video settings

| Name | Default | Meaning |
|---|---|---|
| `fixation_radius_deg` | 16.35° | gaze circle radius (Eckert et al. 2022; 1.x used 5.25°) |
| `field_radius` | 0.8 | scene circle radius as a fraction of half the frame height (circular videos) |
| `background_excludes_fixation` | on | remove the gaze circle from the background |
| `analysis_width` | 500 px | frames are downscaled to this width |
| `circular_mask`, `vertical_fov` | from the device | set automatically from the recording |

## File format and older files

A participant file is the JSON of `Parameters` without the display photometry, with a `version` field (currently 3).
Loading one keeps the display photometry in use; files that do contain `l_min`, `l_max` or `gamma` (older ones, and
the parameters written with an export, which record everything used) set them too.

A display photometry file holds `kind` ("cwtool display photometry"), `device`, `l_min`, `l_max`, `gamma` and a free
`source` text.

Files from version 1.x are converted on load:

- `field` (the adapting field value used directly in the flux) is removed and `l_min`, `l_max` are rescaled by
  `field / device field area`, which gives identical expected pupils;
- the absolute `pupil_scale` becomes `pupil_correction` relative to the device's scale;
- `align_mean` becomes `alignment` (`recording` or `none`).

Unknown fields are ignored, so files stay readable as parameters are added.
