# Calibration presenter

A self-contained web page that shows the [calibration sequence](calibration.md) to the participant, on a screen or
inside a VR headset, and logs every run. It is static (one HTML file and a small three.js build), so it works from
GitHub Pages: [open the presenter](../calibration-tool/index.html){ target=_blank }. Nothing is uploaded; sequences and
runs stay in the browser until you download them.

## Sequence editor

The sequence is a **timeline**: one block per step, coloured with the step's colour, as wide as its length.

- Drag a block to move it; drag its right edge to change its length (0.5 s steps, **Alt** for 0.1 s).
- Select a block to edit its label, RGB colour and length, or duplicate or delete it. Arrow keys select,
  **Alt**+arrows move, **+**/**−** change the length, **Ctrl/Cmd+Z** undoes.
- **Preset** loads a sequence. The default is the **full calibration** (below); the others are from Eckert et al.
  (2022): 8 gray levels, 6 s each, pseudo-random (their most robust sequence); dark-to-light and light-to-dark ramps at
  3, 6 and 10 s; blue and red ramps (shades, then tints) at 3 s; and the 20-step staircase cwtool used before October 2026. The paper describes
  its orders rather than listing them, so the pseudo-random order here is generated (fixed seed), not copied from its
  Fig. 1. The realistic *room* scene of Eckert et al. is not supported.
- **Generate…** builds gray, blue, red, green or gray + RGB primaries ramps of any length, order and duration.
- **Export CSV** / **Import CSV…** use the format of *Load sequence…* in cwtool (`time,r,g,b,label,duration`), so the
  same file drives the presenter and the analysis.

## The default: full calibration

This is also cwtool's default sequence (`calibration.DEFAULT`, in the preset order); `calibration.scrambled` gives
the order the presenter plays for a seed, with the same seeded shuffle.

One sequence for both of cwtool's fits, about 5 minutes (34 steps, 291 s), built from Eckert et al. (2022) and from what the
recordings showed (open issues 36, 40, 43):

| Part | Steps | Why |
|---|---|---|
| Gray, 8 levels (0, 36, 73, 109, 146, 182, 219, 255) | 20, 15, 10, 8, 6, 6, 6 and 12 s | Eckert et al.'s levels; the light sensitivity comes from where the pupil stops shrinking. Darker grays last longer because dilation is slow (time constants 1.6 to 9.6 s), so the end of the step is near its steady state; 255 is long to show the sustained level after the initial constriction |
| Red, green, blue at 64, 128, 191, 255 | 8 s each, every one after a linked black step of 8 s | the channel weights; the black step gives a known dark start, so the colour step is a brightening from the same state, and its end is near steady state |
| Gray 73 and 182 again | 8 s | repeats, so a reproducible model error can be told from the participant's state at that moment |

- **Order:** pseudo-random, no two consecutive levels next to each other in brightness (Eckert et al.), so luminance
  is not confounded with time (in the old ascending staircase, sensitivity could not be told from adaptation).
  Colours are mixed in with the grays. A colour and its black step are **linked** (*Keep with the previous step*):
  scrambling moves them together.
- **Irregular lengths and many changes:** 12 brightening steps from black and about as many darkening steps, of
  different sizes and lengths, give the latency (from onsets), the two time constants and the transient a range to be
  fitted on, as issue 43 asks for.
- **Adjustable:** the lengths are in the timeline. A black step after the gray 0 step just lengthens the dark.

## Running

Choose **On screen** or **In VR**, enter the **participant ID** and press start.

- **Order:** *as designed*, *scrambled, seeded by participant* (the same ID always gives the same order, so it can be
  regenerated; type a seed to override) or *scrambled with a new random seed each run*. *Keep neighbouring
  brightness levels apart* forbids two consecutive steps that are neighbours in brightness. The order for the run is
  previewed, and **Save this order as CSV** exports it.
- **Lead-in:** a neutral gray field before the first step (5 s, level 128 by default), optionally after a start
  signal (**Space**, a click, or the VR controller trigger) so the participant starts when ready.
- **On screen:** the field fills the window in full screen with the cursor hidden. **Esc** aborts.
- **In VR:** the participant is at the centre of a sphere painted in one colour (three.js, WebXR
  `immersive-vr`, no shading or tone mapping, so the field is the requested sRGB value). It needs a
  WebXR browser (a headset browser, or a desktop browser with SteamVR or Varjo Base) and an HTTPS or localhost page.
  Start the run from the desktop window; the status line follows it.

Fix the display first (constant brightness, sRGB, no night shift or HDR): the page sends sRGB values, the light
that results depends on the display.

## Run files

Each run is saved as `calibration_run_<participant>_<mode>_<date-time>.csv`, and kept in the page's list, where you
can also download all runs as one CSV. Lines starting with `#` describe the run (participant, mode, order and
seed, lead-in, start time as Unix milliseconds, frame statistics, display and browser); read them with
`pandas.read_csv(..., comment="#")`. The table has one row per step shown:

| Column | Meaning |
|---|---|
| `time`, `duration` | actual onset and length in s from the first step; the onset is the timestamp of the frame that carried the new colour, so the display adds about one frame |
| `r`, `g`, `b`, `label` | the step's colour |
| `index`, `source_index` | position played, and position in the designed sequence |
| `planned_start_s`, `planned_duration_s` | what was asked |
| `onset_unix_ms` | onset on the computer's clock, to match with recordings |
| `Y` | nominal luminance of the sRGB colour (Eckert et al. 2022, eq. 1) |
| `completed` | `false` for a step cut short by an abort |

The file loads in cwtool's *Load sequence…* as it is, giving the sequence as actually presented. Its `onset_unix_ms`
column is on the presenting computer's clock, so when that is the computer that recorded the eye tracker, cwtool
places the sequence in the recording from it without searching.

!!! note "Not yet checked in a headset"
    The colour of the sphere was checked on a normal canvas only. Check the light in the headset with the
    [lux sensor](../hardware/lux-sensor.md) before relying on the nominal levels; see open issue 46.
