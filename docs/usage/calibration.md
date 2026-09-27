# Participant calibration

Individual differences in pupil size, light sensitivity and response speed, and the imperfectly known photometry
of a headset's display, limit how well the expected pupil matches the measured one. For the Varjo XR-4 each
participant watches a full-field **calibration sequence**, which is used in two automatic fits:

1. **Light sensitivity**: how strongly this participant's pupil responds to the display's light, and to its red,
   green and blue channels.
2. **Latency, scale and offset**: response latency, dilation and constriction speed, pupil scale and offset.

Both start from the **display photometry**: the headset's nominal black and white luminance and gamma, which you
provide (e.g. from the datasheet) and keep in their own file. The fits are saved in the participant's parameter
file and applied to their other recordings.

## The sequence

The built-in sequence has 20 full-field steps: grey levels 0, 36, 73, 109, 146, 182, 219, 255, then red, green and
blue at 64, 128, 191, 255. The built-in timing is 6 s per step (120 s). Other orders and timings, such as the
pseudo-random order recommended by Eckert et al. (2022), are loaded from a CSV (**Load sequence…**):

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
the fit estimates the steady-state pupil (extrapolated when the pupil had not settled by the end of the step) and
finds the values that make the model match them:

| Parameter | Determined by |
|---|---|
| **Light sensitivity** | where along the grey steps the pupil stops shrinking |
| **Red/green/blue weight** | the size of the responses to the colour steps, relative to the greys |
| **Gamma** (optional) | the spacing of the grey steps |
| Pupil scale and offset | the overall size of the responses (refined by the next fit) |

The result window plots the steady-state pupil of each step in its colour against the model before and after,
with the sensitivity's 95 % interval and warnings (e.g. when many steps had not settled, or when the sensitivity is
weakly determined). **Apply** sets the values.

A sensitivity of 2 means this participant's pupil responds to the display as the standard observer would to twice
the luminance, or equally that the display is twice as bright as its photometry says. Compare sensitivities only
between participants calibrated with the same display photometry.

## 3. Fit latency, scale and offset

Click **2. Fit latency, scale and offset** (tick *Include dilation/constriction time constants* to fit dynamics).
The latency is measured from the constriction onsets at the sequence's brightening steps (the result reports it with
its spread); the rest is fitted on the sequence window, and the ΔPD RMS before and after is reported. Applying it
sets:

- `delay` (latency), `attack` and `release` (dilation and constriction time constants) with dynamics on,
- `pupil_correction` (scale multiplier) and `pupil_offset`,
- `alignment` = `fixed`, so the offset is applied as fitted in other recordings, instead of being re-estimated.

If a value ends on a search limit, or the fitted scale is implausible, a warning explains it: usually the light
sensitivity fit needs another look (sequence start, display photometry). See
[Calibration fit](../processing/calibration-fit.md) for how it works.

## 4. Save

**File → Save parameters as…** and name the file after the participant. Load it with their other recordings, or
pass it to `cwtool --params`. Participant files do not contain the display photometry, so loading one keeps the
display photometry currently in use. (Files from before this change still carry Lmin, Lmax and gamma; loading them
reproduces their original results.)

!!! warning "Light sensitivity first"
    The latency fit takes the light response as given. Running it first makes the latency and time constants absorb
    luminance errors: on the April 2026 Varjo sample, default settings gave a latency of 0 s, which is not
    physiological.

!!! tip "Adjusting by hand"
    Every fitted value stays editable. Watching the expected curve against the measured one and the **ΔPD RMS in
    sequence** while changing the sensitivity or channel weights is still a useful check of the fit.
