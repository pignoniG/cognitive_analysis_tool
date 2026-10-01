# Participant calibration

Individual differences in pupil size, light sensitivity and response speed, and the imperfectly known photometry
of a headset's display, limit how well the expected pupil matches the measured one. For the Varjo XR-4 each
participant watches a full-field **calibration sequence**, which is used in two automatic fits:

1. **Light sensitivity**: how strongly this participant's pupil responds to the display's light, and to its red,
   green and blue channels.
2. **Latency and dynamics**: response latency, dilation and constriction speed.

Both start from the **display photometry**: the headset's nominal black and white luminance and gamma, which you
provide (e.g. from the datasheet) and keep in their own file. The fits are saved in the participant's parameter
file and applied to their other recordings.

## The sequence

The built-in sequence has 20 full-field steps: grey levels 0, 36, 73, 109, 146, 182, 219, 255, then red, green and
blue at 64, 128, 191, 255. The built-in timing is 6 s per step (120 s). Other orders and timings, such as the
pseudo-random order recommended by Eckert et al. (2022), are loaded from a CSV (**Load sequence…**), which the
[calibration presenter](calibration-tool.md) can build, scramble per participant and play on a screen or in VR:

```text
time,r,g,b,label
0,0,0,0,Black
6,36,36,36,Gray 36
...
```

Accepted layouts: a header with a time column (`time`, `t`, `timestamp`, `start`, `onset`; seconds, or
milliseconds if the header says `ms`) and `r`/`red`, `g`/`green`, `b`/`blue` columns, optionally `duration` and
`label`; or four unlabelled columns time, R, G, B. Colours may be 0–255 or 0–1. Each step lasts until the next
starts; the last uses its duration, or the median step length.

## 0. Display photometry (once per headset and settings)

In **Display photometry (datasheet)** enter the headset's black luminance (**Lmin**), white luminance (**Lmax**) and
**gamma**, then **File → Save display photometry…**. The file is remembered for that device and loaded
automatically with its recordings; load another one with **File → Load display photometry…** if the headset's
settings or firmware change.

These values do not have to be exact. The sequence cannot tell a dimmer headset from a less sensitive participant,
so any error common to all participants ends up in each participant's light sensitivity (see below). What matters
is using the same display photometry for all participants and recordings made with the same headset settings.

## 1. Locate the sequence

Open the recording and click **Find in recording**. It finds the step changes in the analysed video colour, tries
each as a start, and scores how well the sequence's colours explain the measured ones (with one gain per channel,
since recorded levels are below nominal). If the steps are evenly spaced it also tries the recording's actual
step length, so a sequence played with 10 s steps is found even though the built-in one uses 6 s. Stretches where
eye tracking was lost have no analysed colour and are left out of the score; the status bar says how much of the
sequence fell in such gaps.

The overlay turns on and the start is set. Adjust it by dragging the grey line if needed.

## 2. Fit the light sensitivity

Click **1. Fit light sensitivity** (tick *Also fit gamma* only if the datasheet gamma clearly fails). For every step
the fit takes the pupil's level at the end of the step (the mean of its last 30 %) and finds the values that make
the model match them:

| Parameter | Determined by |
|---|---|
| **Light sensitivity** | where along the grey steps the pupil stops shrinking |
| **Red/green/blue weight** | the size of the responses to the colour steps, relative to the greys |
| **Gamma** (optional) | the spacing of the grey steps |
| **Black level** (optional) | the pupil on the black steps, with the white held at its nominal value |

The pupil offset is not fitted: with the sensitivity and the display's black and white free, an offset would hide an error of them. It stays the value set by hand.
The black level needs steps long enough to dark-adapt: with short steps the black looks brighter than it is, and the fit reports the contrast it implies against the nominal one.

The result window plots the level of each step in its colour against the model before and after, with the
sensitivity's 95 % interval and warnings (e.g. when steps were still dilating at their end, or when the sensitivity
is weakly determined). **Apply** sets the values.

A sensitivity of 2 means this participant's pupil responds to the display as the standard observer would to twice
the luminance, or equally that the display is twice as bright as its photometry says. Compare sensitivities only
between participants calibrated with the same display photometry.

## 3. Fit latency and dynamics

Click **2. Fit latency and offset** (tick *Include dynamics (time constants and transient)* to fit the
dilation and constriction time constants together with the constriction beyond the steady state after brightening
steps and its re-dilation, and turn the dynamics on).
The latency is measured from the constriction onsets at the sequence's brightening steps (the result reports it with
its spread); the rest is fitted on the sequence window, and the ΔPD RMS before and after is reported. Applying it
sets:

- `delay` (latency),
- with dynamics: `dynamics` = on, `attack` and `release` (dilation and constriction time constants), `transient` and
  `escape`,

If a value ends on a search limit, a warning explains it: usually the light sensitivity fit needs another look
(sequence start, display photometry).

!!! note "The pupil scale is not fitted"
    `pupil_correction`, the multiplier on the device's pupil scale, stays the value you set (1 by default). One
    sequence does not determine it: it trades off with the light sensitivity and the black point, and a fitted value
    far from 1 was not evidence of a wrong scale ([open issue 1](../OPEN_ISSUES.md)). Set it by hand when there is a
    reason, such as a known-size reference or a device whose millimetres are known to be off. See
[Calibration fit](../processing/calibration-fit.md) for how it works.

## Glasses with a lux sensor

Pupil Core, Neon and Glasses 3 have no display photometry, so the two fits above are not available. With a lux log
(and the presenter played on the computer that recorded the tracker), **Load sequence…** takes the presenter's run
file, which places the sequence, and **Fit sensitivity and offset** fits the light sensitivity and the pupil offset
on it: see [Calibration fit](../processing/calibration-fit.md#glasses-with-a-lux-sensor). Check first that the sensor
sees the screen: a sensor dominated by room light barely follows the steps, and the fit says so.

## 4. Save

**File → Save parameters as…** and name the file after the participant. Load it with their other recordings, or
pass it to `cwtool --params` (with the display photometry file as `--display`). Participant files do not contain the display photometry, so loading one keeps the
display photometry currently in use. (Files from before this change still carry Lmin, Lmax and gamma; loading them
reproduces their original results.)

!!! warning "Light sensitivity first"
    The latency fit takes the light response as given. Running it first makes the latency and time constants absorb
    luminance errors: on the April 2026 Varjo sample, default settings gave a latency of 0 s, which is not
    physiological.

!!! tip "Adjusting by hand"
    Every fitted value stays editable. Watching the expected curve against the measured one and the **ΔPD RMS in
    sequence** while changing the sensitivity or channel weights is still a useful check of the fit.
