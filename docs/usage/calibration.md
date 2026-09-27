# Participant calibration

Individual differences in pupil size and response speed, and the unknown photometry of a headset's display,
limit how well the expected pupil matches the measured one. For the Varjo XR-4 the procedure is a full-field
**calibration sequence** shown to each participant, used in two stages:

1. **Photometric calibration** (by hand): the display's black and white luminance, channel balance and gamma, so
   the model's luminance matches what the eye receives.
2. **Participant fit** (automatic): response latency, dilation and constriction speed, pupil scale and offset.

The result is saved as the participant's parameter file and applied to their other recordings.

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

## 1. Locate the sequence

Open the recording and click **Find in recording**. It finds the step changes in the analysed video colour, tries
each as a start, and scores how well the sequence's colours explain the measured ones (with one gain per channel,
since recorded levels are below nominal). If the steps are evenly spaced it also tries the recording's actual
step length, so a sequence played with 10 s steps is found even though the built-in one uses 6 s.

The overlay turns on and the start is set. Adjust it by dragging the grey line if needed.

## 2. Photometric calibration

With the overlay visible, adjust in **Photometric calibration** while watching the blue expected curve against
the black measured one and the **ΔPD RMS in sequence**:

| Parameter | Effect on the expected pupil |
|---|---|
| **Lmin** | level on the black step and darkest greys |
| **Lmax** | level on the white step; too high and the model keeps shrinking while the measured pupil has stopped |
| **gain R/G/B** | relative size of the responses to the red, green and blue steps |
| **gamma** | spacing of the grey steps between black and white |

Aim for the expected curve to follow the measured steps in shape. A constant vertical difference does not matter
(it becomes the offset), nor does the timing of the edges (the fit handles it).

## 3. Fit the participant

Click **Fit latency, scale and offset** (tick *Include dilation/constriction time constants* to fit dynamics).
The fit runs on the sequence window and reports the ΔPD RMS before and after. Applying it sets:

- `delay` (latency), `attack` and `release` (dilation and constriction time constants) with dynamics on,
- `pupil_correction` (scale multiplier) and `pupil_offset`,
- `alignment` = `fixed`, so the offset is applied as fitted in other recordings, instead of being re-estimated.

If a value ends on a search limit, or the fitted scale is implausible, a warning explains it: usually the
photometric calibration needs another pass. See [Calibration fit](../processing/calibration-fit.md) for how it
works.

## 4. Save

**File → Save parameters as…** and name the file after the participant. Load it with their other recordings, or
pass it to `cwtool --params`.

!!! warning "Photometry first"
    The fit takes the photometric parameters as given. Fitting before adjusting them makes the latency and time
    constants absorb luminance errors: on the April 2026 Varjo sample, default photometry gave a latency of 0 s,
    which is not physiological.
