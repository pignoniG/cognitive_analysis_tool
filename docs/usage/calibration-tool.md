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
- **Preset** loads the **time-course calibration** (below), the only calibration sequence. The timeline can still be
  edited or a sequence imported, for tests.
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

## Why only this sequence

The earlier sequences are gone from the presenter, cwtool and the validation task (24 November 2026):

- **The full calibration** was the default until November 2026: 34 steps with 12 black steps, each colour after black.
  - Its black steps never settled in 8 s, and in the Varjo they pushed the pupil beyond what the tracker reports
    (open issues 52 and 55).
  - Every dimming followed bright light, so only the slow part of the dilation was measured (issue 56).
  - Its regular 8 s steps were anticipated (issue 57).
- **The 20-step staircase** cwtool used before October 2026 played in a fixed ascending order, which confounds luminance
  with time (issues 36, 41 and 43).
- **The ramps of Eckert et al. (2022)** (grays, blue and red at 3 to 10 s) each measure one thing. They do not give the
  fit on the time course what it needs: the time constants, both parts of the dilation, the colour weights and the
  transient, all from one recording.

The time-course calibration does all of this in about 5 minutes. One sequence everywhere also means that a recording, a
participant's seed and the fit's defaults always refer to the same steps.

Recordings made with the earlier sequences are analysed from the run files the presenter saved with them, since a
run file records every step played (**Load sequence…** in the app).

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

## Gaze check

With **Gaze check at the start** (on by default), the gaze check comes right after the lead-in, on the lead-in grey, and
the light steps follow it:

1. a short tone (880 Hz, 0.2 s) to call the participant's attention, then 1 s of grey with no dot, so the pupil's
   response to the sound is over before the dots (and long before the light steps, which the fits use);
2. a black dot with a white centre moving through 9 places, **Seconds per point** each (3 s by default, 27 s in all),
   the centre first, then the corners and the edges' middles clockwise from the top left.

It comes first so that it is done while the participant is fresh and is there even in a run cut short, and its 28 s on
the lead-in grey adapt the pupil before the first light step. Until November 2026 it came after the light steps; cwtool
reads run files in either order.

Ask the participant to look at the dot's centre wherever it goes. The tone needs the computer's sound on (in VR over
Link it plays in the headset); the run file says if it could not be played (`gaze_cue`).

- **On screen** the places are at ±35 % of the screen from its centre; the dot is 2.4 % of the screen's shorter side.
- **In VR** they are directions from the head, ±15° horizontally and ±12° vertically, and the dot (0.8° radius, drawn
  multisampled so its edges are smooth) is fixed to the head: it stays at the same place in the headset's picture, and so in its video capture (the Varjo's, the
  Quest's), whatever the head does.

The run file logs each place (below), so cwtool can find the dot in the scene video, compare it with the gaze and
propose an offset ([open issue 61](../OPEN_ISSUES.md)). The gaze check is not part of the light sequence: cwtool's
*Load sequence…* and the log alignment leave its rows out.

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
| `phase` | `light` for the sequence's steps, `gaze` for the gaze check's (its first row, "Gaze check cue (tone)", is the tone and the second of grey, with no target) |
| `target_u`, `target_v` | gaze check: the place on the unit grid (right, down; −1, 0 or 1) |
| `target_x`, `target_y` | gaze check on screen: the dot's centre as a fraction of the screen from its top left |
| `target_az_deg`, `target_el_deg` | gaze check in VR: the dot's direction from the head's straight ahead, in degrees (right, up) |

The file loads in cwtool's *Load sequence…* as it is, giving the sequence as actually presented. Its `onset_unix_ms`
column is on the presenting computer's clock, so when that is the computer that recorded the eye tracker, cwtool
places the sequence in the recording from it without searching.

!!! note "The light in the headset is not measured yet"
    The VR session has been run in a headset, but the colour of the sphere was only checked on a normal canvas. Check
    the light in the headset with the [lux sensor](../hardware/lux-sensor.md) before relying on the nominal levels;
    see open issue 46.
