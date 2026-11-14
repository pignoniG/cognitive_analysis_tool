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
- **Preset** loads a sequence. The default is the **time-course calibration** (below); the **full calibration**, the
  default until November 2026, follows it; the others are from Eckert et al.
  (2022): 8 gray levels, 6 s each, pseudo-random (their most robust sequence); dark-to-light and light-to-dark ramps at
  3, 6 and 10 s; blue and red ramps (shades, then tints) at 3 s; and the 20-step staircase cwtool used before October 2026. The paper describes
  its orders rather than listing them, so the pseudo-random order here is generated (fixed seed), not copied from its
  Fig. 1. The realistic *room* scene of Eckert et al. is not supported.
- **Generate…** builds gray, blue, red, green or gray + RGB primaries ramps of any length, order and duration.
- **Export CSV** / **Import CSV…** use the format of *Load sequence…* in cwtool (`time,r,g,b,label,duration`), so the
  same file drives the presenter and the analysis.

## The default: time-course calibration

Made for cwtool's calibration fit on the pupil's time course (`cwtool.calfit`), after the first validation run in the
Varjo (November 2026). It is `calibration.TIME_COURSE` in cwtool, with the same steps and the same seeded order (the
presenter's JavaScript and cwtool are checked against each other); `calibration.scrambled` gives a participant's order.
About 5 minutes, 30 steps, 281 s:

| Part | Steps | Why |
|---|---|---|
| Gray, 8 levels (12, 24, 40, 64, 96, 140, 196, 255) | 14, 12, 10, 9, 8, 7, 6 and 8 s | the light-response curve, the levels about 2.3 times apart in luminance. No black: in the dark the pupil can exceed what a tracker reports (the Varjo stopped at 6 mm, open issue 52), and a black step never settles in 8 s |
| Dimming after moderate light | Gray 128 → Gray 24 (7 + 15 s), Gray 96 → Gray 12 (6 + 16 s), each pair linked | the pupil re-dilates quickly after moderate light: the fast part of the dilation |
| Dimming after bright light | Gray 255 → Gray 24 (6 + 18 s), Blue 255 → Gray 12 (7 + 20 s), linked | after bright, and especially blue, light it re-dilates slowly: the slow part (open issue 56). The old sequence dimmed only after bright light, so it measured only this |
| Red, green, blue at 128 and 255 | 7 to 9 s, each after a linked gray of the same luminance (Gray 60, 110, 33, 127, 220, 76) | the colour weights, as the change from a gray of equal luminance; no black reset before each colour |
| Gray 64 and 196 again | 9 and 7 s | repeats |

- **Order:** pseudo-random as before (no two consecutive levels next to each other in brightness), seeded by the participant.
  Each probe carries its context as a linked first step, so it works in whatever order the seed gives.
- **Irregular lengths** (6 to 20 s): the steps cannot be anticipated (three constrictions on the first run started before
  the change), and the long ones are where the pupil dilates.

## Full calibration (default until November 2026)

This is `calibration.DEFAULT` in cwtool (in the preset order); `calibration.scrambled` gives the order the presenter plays
for a seed, with the same seeded shuffle.

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
- **Compatible VR rendering** (on by default): the page draws into the classic WebXR layer (`XRWebGLLayer`), which every
  runtime shows. Switched off, three.js draws into a WebXR Layers projection layer where the browser offers one. A
  Quest 3 over Link in Chrome does not show that layer: the headset stays dark ("this page is not responding") while
  the run goes on and saves a complete file. The run file names the layer used (`xr_render_path`).
- **A run nobody saw:** the page cannot know what the headset shows, because a headset that shows nothing may still
  deliver every frame. It counts the frames in which the session's view was not "visible" or had no head pose
  (`xr_frames_view_not_visible`, `xr_frames_without_head_pose`), and warns in the status line and in the file
  (`xr_view_possibly_not_shown`) when that is most of them. No warning is not proof: with a new headset or browser,
  ask the participant what they saw.
- **Only the headset's frames move the run:** the sequence advances on the frames the headset asks the page for. If
  none has come 5 s after entering VR, the run is stopped and the session ended, with a message in the status line,
  instead of going on with nothing shown.

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

!!! note "The light in the headset is not measured yet"
    The VR session has been run in a headset, but the colour of the sphere was only checked on a normal canvas. Check
    the light in the headset with the [lux sensor](../hardware/lux-sensor.md) before relying on the nominal levels;
    see open issue 46.
