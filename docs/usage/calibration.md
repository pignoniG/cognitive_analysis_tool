# Participant calibration

Individual differences in pupil size, light sensitivity and response speed, and the imperfectly known luminance of a
headset's display, limit how well the expected pupil matches the measured one. Each participant watches a full-field
**calibration sequence**, and one automatic fit, on the pupil's time course over the sequence, sets together:

1. **The light response**: how strongly this participant's pupil responds to the display's light, and to its red, green
   and blue channels (with glasses and a lux sensor: to the sensor's luminance, and the pupil offset).
2. **The timing**: the response latency, and how fast the pupil dilates and constricts.

No photometry of the display is needed: the fitted values are effective for the headset model and its settings (below).
The fit is saved in the participant's parameter file and applied to their other recordings with the same device.

## The sequence

The default sequence is the [calibration presenter](calibration-tool.md)'s **time-course calibration**: eight greys from
12 to 255 (no black); dimming after moderate and after bright light; red, green and blue at 128 and 255, each after a grey
of the same luminance; two greys repeated; 30 steps, 281 s, in a pseudo-random order (`calibration.TIME_COURSE`). The
presenter usually scrambles it again for each participant, seeded by their ID: load the run file it saves (**Load
sequence…**), which records the order played, or regenerate it with
`calibration.scrambled(calibration.TIME_COURSE, "<participant ID>")`. Recordings made before November 2026 used the **full
calibration** (34 steps, 291 s, with black steps: `calibration.DEFAULT`, also in the **Built-in** menu).

The 20-step staircase used before October 2026 (greys 0 to 255, then red, green and blue at 64 to 255, 6 s each,
ascending) is still available (**Built-in** menu, `calibration.STAIRCASE_20`) for recordings made with it; its fixed
ascending order confounds luminance with time (open issues 36, 41, 43). Other sequences are loaded from a CSV:

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

## 0. Display photometry (optional)

The analysis maps the video's colours onto a luminance with the display's black (**Lmin**), white (**Lmax**) and
**gamma**. Their nominal values (Lmax 100 cd/m², a 10000:1 contrast, gamma 2.2) are enough: the calibration fit cannot
tell a dimmer headset from a less sensitive participant, or the display's primaries from the eye's colour weighting, so
it absorbs whatever the nominal values get wrong into the participant's sensitivity and colour weights. Those are then
*effective* values, valid for this headset model and its settings.

What matters is to use the same values for all participants and recordings with the same headset. To use measured
values instead, enter them in **Display photometry** and **File → Save display photometry…**: the file is remembered for
that device, and a photometry file saved in a recording's folder is loaded with it. Compare sensitivities only between
participants calibrated with the same values.

## 1. Locate the sequence

Open the recording and click **Find in recording**. It finds the step changes in the analysed video colour, tries
each as a start, and scores how well the sequence's colours explain the measured ones (with one gain per channel,
since recorded levels are below nominal). If the steps are evenly spaced it also tries the recording's actual
step length, so a sequence played with 10 s steps is found even though the built-in one uses 6 s. Stretches where
eye tracking was lost have no analysed colour and are left out of the score; the status bar says how much of the
sequence fell in such gaps.

The overlay turns on and the start is set. Adjust it by dragging its handle under the plots if needed.

## 2. Fit the calibration

Click **Fit the calibration**. The fit compares the expected pupil with the measured one, sample by sample over the
sequence, and finds together:

| Parameter | Determined by |
|---|---|
| **Light sensitivity** | where along the grey steps the pupil stops shrinking |
| **Red/green/blue weight** (display) | the size of the responses to the colour steps, relative to the greys |
| **Latency** | the constriction onsets at the brightening steps (reported with their spread), else the whole fit |
| **Dilation and constriction τ** | how fast the pupil follows each step (*Include the time constants*, on by default) |
| **Pupil offset** (lux sensor) | the level of the measured pupil against the model |

Options: *Also fit the two parts of the dilation* (the share and time constant of its fast part, otherwise held at 60 % and
1 s; only with the time-course calibration, which dims after moderate as well as after bright light), *Also fit the
transient constriction after brightening* (off by default: on the first Varjo run it explained
the slow dilation after the black steps instead, and made the session's ΔPD worse), and on a display *Also fit gamma* and
*Also fit the black level*, which the sequence rarely determines. A step that is still dilating at its end, or a step at the
tracker's ceiling, is simply part of the curve (or a lower bound): it does not need to settle.

The result window gives the fit error before and after, the ΔPD RMS in the sequence, the fitted values with the
sensitivity's 95 % interval, and warnings (a weakly determined sensitivity, a value at the end of its range, a poor
correlation, constrictions that started before the change). **Apply** sets the values, and switches the dynamics on.

A sensitivity of 2 means this participant's pupil responds to the display as the standard observer would to twice the
nominal luminance, or equally that the display is twice as bright as its nominal values say.

!!! note "The pupil scale is not fitted"
    `pupil_correction`, the multiplier on the device's pupil scale, stays the value you set (1 by default). One
    sequence does not determine it: it trades off with the light sensitivity and the black point, and a fitted value
    far from 1 was not evidence of a wrong scale ([open issue 1](../OPEN_ISSUES.md)). Set it by hand when there is a
    reason, such as a known-size reference, or enter the participant's measured iris on the Varjo
    ([Varjo](../devices/varjo.md)).

See [Calibration fit](../processing/calibration-fit.md#the-fit-on-the-time-course) for how it works.

## Glasses with a lux sensor

Pupil Core, Neon and Glasses 3 have no display: the light comes from the lux sensor (distributed with the scene video).
With a lux log (and the presenter played on the computer that recorded the tracker), **Load sequence…** takes the
presenter's run file, which places the sequence, and **Fit the calibration** fits the light sensitivity, the pupil offset,
the latency and the time constants on it (*Also fit the fixation weight* adds the gaze circle's weight, for a scene
where the gaze area and the background differ). Check first that the sensor sees the screen: a sensor dominated by room
light barely follows the steps, and the fit says so.

## 3. Save

**File → Save parameters as…** and name the file after the participant. Load it with their other recordings, or
pass it to `cwtool --params` (with the display photometry file as `--display`). Participant files do not contain the display photometry, so loading one keeps the
display photometry currently in use. (Files from before this change still carry Lmin, Lmax and gamma; loading them
reproduces their original results.)

!!! tip "Adjusting by hand"
    Every fitted value stays editable. Watching the expected curve against the measured one and the **ΔPD RMS in
    sequence** while changing the sensitivity or channel weights is still a useful check of the fit.
