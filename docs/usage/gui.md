# Desktop app

Start it with `cwtool-gui`, optionally followed by a recording folder, or with `python -m cwtool.gui`.

## Layout

The window has the controls on the left, the plots on the right, and the video preview under the controls.

| Area | Contents |
|---|---|
| Rail (far left) | Four tabs: **Data**, **Params**, **Calibrate**, **Export** (Ctrl+1 to Ctrl+4). A red dot under a tab's name says it needs attention, for example **Data** when a glasses recording has no lux readings |
| Tab page | **Data**: the recording, the **Set-up** checklist, the scene video and its analysis settings, and the sensor data (the lux log of glasses, the Shimmer, the EmotiBit). **Params**: the parameters, in pills (below). **Calibrate**: numbered steps. **Export**: the export range and the Export button |
| Video preview | Under the page, 16:9, following the cursor. **Values** shows the colours and luminance measured at the cursor, **Pop out** moves it to a window of its own, **Hide** (or **P**) gives its room back to the page. Drag the divider above it to resize |
| Status strip | One short line over the plots: ΔPD RMS and SD, and the light left in ΔPD. **Details** (on its right) opens the expected pupil at the display's black and white points (display devices) or where the luminance comes from (with the lux sensor: its median luminance × the median video ratio and its 10th–90th percentile range), the pupil scale and offset applied, the sampling rates and the share of the recording in gaps. A red **⚠ N warnings** button opens the list of warnings. Hover the line for what each number means |
| Plots | Measured vs expected pupil, luminance, the video ratio (lux sensor with the video only) and ΔPD, sharing the time axis, with the imported sensor signals under them. They use the whole width of the window; the drop-downs under them switch each plot on and off (pupil diameter and ΔPD, and the RMSSD once computed, are on at first) |

The last tab, pill, preview state and sizes are remembered between sessions.

### Params: pills

| Pill | Holds |
|---|---|
| **Participant** | age, eyes, and the **Dynamics** drop-down (latency, time constants, transient: fitted per participant) |
| **Light** | only what applies to the device: display photometry and the participant's light response (Varjo), or the lux sensor and the scene camera without a lux log (glasses) |
| **Signal** | the pupil signal (scale, alignment, offset, time lag, gaps, artefacts) and ΔPD (window, smoothing) |

A dot after a pill's name means something in it differs from the defaults. **Restore this group's defaults** (under
the last block of the pill, with a confirmation) puts the open pill's settings back. **Load…**, **Save**, **Save as…** and **Revert** at the top
of the tab are the participant's parameter file.

## Menus

**File**

- **Open recording…** (Ctrl+O): choose a recording folder. The device is detected automatically. **Open recent** lists the
  last ten recordings (newest first); **Clear the list** empties it.
- **Logger folder… (lux and sensor data)**: the [sensor logger](logger.md)'s recordings folder, or one of its sessions.
  The logger writes the lux log (`lux.csv`) and the Shimmer and EmotiBit files of a recording into one session folder,
  so one folder serves both: the session that overlaps the recording is found by its time, the lux log is read from it
  (glasses recordings) and the sensor files are imported (see [Sensor data](#sensor-data-optional)). Give the
  recordings folder once: it is remembered between sessions and used for every recording, so nothing is copied into the
  recordings; one session folder is used for the open recording only. It is shown in the Recording box. If it holds
  nothing for a recording, a warning says so (check the folder and the clocks). The same button is in the *Sensor data*
  and *Lux sensor log* boxes of the Data tab.
- **Forget the logger folder**: go back to the recording's own folder and its `lux` subfolder for the lux logs and
  the sensor files.
- **Load parameters… / Save parameters / Save parameters as…**: the participant's parameter file (JSON), without
  the display photometry. Files written by version 1.x are converted when loaded.
- **Load display photometry… / Save display photometry…**: the headset's nominal Lmin, Lmax and gamma. The last
  file used with a device is loaded automatically with its recordings; the window title shows which one is in use.
- **Export results…** (Ctrl+E): one package into a folder of your choice (default `cwtool_export` inside the recording): the
  results CSVs, the sensor files, the parameters used, a manifest and a PDF plot, all trimmed to the
  [export range](#export-range). It runs in the background with a progress bar in the Export tab, so the window stays
  usable; when it ends, the tab keeps "Last export" with a link to the folder.

**View**

- **Reset view** (Ctrl+0): show all the data on the plots again.
- **Show video preview** (P): show or hide the preview under the tab pages.
- **Data tab**, **Params tab**, **Calibrate tab**, **Export tab** (Ctrl+1 to Ctrl+4).

**Help**

- **Gestures and shortcuts…**: the mouse gestures of the plots and the keyboard shortcuts, in one list. The shortcuts
  are Ctrl+O (open), Ctrl+S and Ctrl+Shift+S (save parameters), Ctrl+E (export), Ctrl+H (compute HRV), Z (zoom mode of
  the plots), Ctrl+0 (reset view), Ctrl+1 to Ctrl+4 (tabs), P (preview) and Ctrl+Q.
- **Documentation**: opens this site. **About**: the version.

**Errors**: when something fails the window shows what happened in a sentence, what to try for the causes it knows (a
missing package, file or permission, an unreadable video, no memory or disk space, a damaged parameter file), and the
technical details under **Show Details…**. An analysis error appears once per cause, not at every edit of the parameters.

## Set-up checklist and unsaved parameters

- **Set-up** (top of the Data tab, for a display device and for glasses with a lux sensor) lists what is still needed
  before the ΔPD can be trusted, with ✓ for what is done and ✗ for what is not. A display device: the display photometry
  (loaded, or the nominal defaults in use), the calibration sequence (its overlay shown and its start set), the light
  sensitivity and the latency and offset (each fitted in this session, or from the participant's parameter file). Glasses
  with a lux sensor: the lux readings, the sequence, and the sensitivity and offset. A ✗ line is a link to where it is
  done (the logger folder, the display photometry file, or the Calibrate tab).
- **Revert** (Params tab, next to Load and Save) puts the parameters back to what they were when last loaded or saved
  (or at the start), after asking; it is on only while they differ. The window title says "changed" meanwhile. The display
  photometry is not part of it (it has its own file).
- **Closing the window or opening another recording** with changed parameters asks: **Save** (to the open parameter
  file, or a file you choose), **Discard** (back to the saved state) or **Cancel**. The parameters you tune for one
  participant are kept when you open that participant's next recording; the question is only asked when they have
  changed since they were saved.

## Sensor data (optional)

The Sensor data box holds everything the [sensor logger](logger.md) recorded: the lux log (for a glasses recording, where
it is one of the sensor inputs: the box says how many readings it has, or that none were found), the Shimmer's ECG and
the EmotiBit's EDA, PPG and motion. They can be put next to the pupil data. They are not used by the analysis; they let you see heart and skin responses against ΔPD, and
export everything for one participant as a single package.

- **Logger folder…** (or **File → Logger folder…**): choose the logger's recordings folder, or one session. The
  session that overlaps the recording is found (the one with the longest overlap) and its sensor files imported, and
  its lux log is used for a glasses recording: it is the same folder as for the lux log. When a recording is opened,
  the files in its own folder, or else in the remembered logger folder, are imported automatically. Only the rows that
  overlap the recording are read. The recording must say when it started (its absolute time), as the sensor files are on
  the Unix clock.
- The list under the buttons holds every signal of every file (the Shimmer's channels, the EmotiBit's streams). The
  ticked ones are drawn, one plot each, under ΔPD on the same time axis, cursor and events; at first the ECG channel
  of the Shimmer and the EmotiBit's EDA and PPG. At most six at a time.
- Values are shown as the logger saved them: the Shimmer's are raw ADC counts, not millivolts.
- A Shimmer file whose ECG was sampled below 200 Hz gets a warning under the list (too coarse for
  [heart rate variability](../processing/hrv.md)).
- **Compute HRV** (next to Import and Remove, on when an ECG is imported) finds the heartbeats of the Shimmer's ECG in
  the background and then shows, under the buttons, a table with one row per window (the whole recording and each
  event): heart rate, RMSSD, SDNN and LF/HF, with the other measures in the exported file. The beats are drawn on the
  ECG plot, as green circles where the interval before the beat is trusted and red crosses where it is not, so the
  detection can be checked by eye. A `*` after a window's name means it carries a note (a short window, many untrusted intervals):
  select the row to read it. The table follows the [export range](#export-range) as you edit it, since only the windows
  are worked out again, not the beats. The button then reads *Recompute HRV*; importing other sensor data or opening
  another recording forgets the result. The beats are found by NeuroKit2 (`pip install "cwtool[hrv]"`).
- **Use the data beyond the export range at its edges** (a box under the HRV button, on by default): the heartbeats are
  found on all the data and the export range only cuts which beats count, so the first beat after a cut keeps its
  interval. Off: a strict cut that loses it. See [how the HRV is cut](../processing/hrv.md#cutting-at-the-export-range).
- **Heart rate variability plots**: two plots join the others under ΔPD, on the same time axis and cursor, switched in the
  **Heart rate variability** drop-down under the plots (**Heart rate**, off at first, and **RMSSD**, on): the heart rate (bpm) from the trusted intervals, and the
  RMSSD (ms) of a moving window (30 s, changed in the box next to them; the first point is one window after the first
  beat). Red points on the RMSSD curve mark windows in which more than 10 % of the intervals were not trusted, and a gap
  is a window with too few trusted intervals. These plots are a preview and are not exported; the table is. They follow
  the export range.
- **Remove** forgets the sensor data. All the signals, not only the ticked ones, go into the export.

## Export range

What the export leaves out: the calibration sequence, a break, a test run before the participant started. The
analysis and the plots always use the whole recording (the model needs the history of the light); the range only
decides what is written by **Export results…**, for every file at once (results, lux, sensors, events).

- **Start at / End at**: leave out everything before or after a time. **Cursor** takes the time of the red cursor.
  Both are drawn on the plots as dashed lines, with a handle under the plots to drag (see **Handles** below).
- **Left out**: any number of segments in between, drawn as grey bands. **Leave out from cursor** adds 10 s at the
  cursor to adjust; **Leave out calibration** leaves out the calibration sequence while its overlay is shown. Drag a
  band by the handles under the plots (its two edges and its middle), or double-click a row (or **Edit…**) to type the times. Bands dragged
  over each other merge.
- Times are those of the plots' axis (`timestamp_relative` in the exports).
- The range is saved next to the recording (`cwtool_trim.json`) and comes back when it is opened again; clearing it
  removes the file. It is separate from the participant's parameter file, since it belongs to one recording.

If the heart rate variability was computed (**Compute HRV** in the [Sensor data](#sensor-data-optional) box), the
package also holds the beat times and the HRV measures of the whole recording and of each event, on what the range
keeps ([method](../processing/hrv.md)); the summary above the export button says "+ HRV". Without it the package has no
HRV: the export does not compute it by itself.

ΔPD in SD units (`delta_pd_sd`) is normalised with the SD of what is kept, so a calibration with large swings does not
shrink the other values; see [Output files](../reference/outputs.md).

## Scene video

The video is analysed automatically when a recording is opened, unless a cached analysis made with the same
video, settings, frame timestamps and gaze exists. **Reanalyse video** (**Analyse video** before any analysis) runs
it again, for example after changing the video analysis settings; **Cancel**, shown while it runs, stops it (it is shown for the video analysis and the calibration fit, the two that can stop; the others take seconds).

**Video analysis settings** (drop-down under the buttons: gaze circle radius, scene circle, background, analysis
width) change what is measured in the video: after editing them, click **Reanalyse video**. The video preview
already draws the new circles, so sizes can be checked before re-running.

**Calibrate camera from lux** (glasses recordings with a lux log): measures the luminance that saturates a
fixed-exposure scene camera, for recordings of the same exposure without a lux log (see
[Luminance](../processing/luminance.md#calibrating-the-camera-from-a-lux-log)).

## Parameters

Parameters are in the pills of the **Params** tab, with the groups of [Parameters](../reference/parameters.md): Participant
(with Dynamics in a drop-down), Display photometry, Participant light response, Luminance from lux sensor, Scene camera
without lux log (these four under Light), Pupil signal and ΔPD (under Signal). The video analysis settings are in a
drop-down under the scene video buttons, in the **Data** tab. Every change re-runs the analysis from the cached video
pass, so the plots follow instantly.

Only the options that affect the loaded recording are shown (all of them before a recording is opened); hidden
options keep their values and are still saved in the parameter file:

| Recording | Hidden |
|---|---|
| Varjo | Lux sensor, Scene camera without lux log |
| Pupil Core / Neon / Glasses 3 with a lux log | Lmin, Lmax, Scene camera without lux log, scene circle radius |
| Pupil Core / Neon / Glasses 3 without a lux log | Lux sensor, Calibration sequence, scene circle radius; with camera exposure `auto` the camera full scale and exposure times, with `fixed` Lmin and Lmax |

The **Calibrate** tab depends on the device. A display device (Varjo) has three steps: the sequence, **Fit light
sensitivity** and **Fit latency and offset**. Glasses with a lux log have the sequence and one fit, **Fit sensitivity
and offset**, with a note that they have no display photometry (see below). Glasses without a lux log have no steps,
only a note saying what the sequence would need; their dynamics are set by hand in Params → Participant. Once a fit
is applied, its step shows the result under its title. The lux sensor group starts with a line saying which route the luminance takes (sensor ×
video ratio, or sensor only); the video preview shows the same product for the frame at the cursor, and the weights
of the gaze circle and the background.

## Plots

- **Which plots are shown**: three drop-downs under the plots. **Plots**: **Pupil diameter**, **Luminance**, **Video
  ratio**, **ΔPD**. **Heart rate variability** (once computed): **Heart rate** and **RMSSD**, with the window of the RMSSD. At first the pupil diameter, ΔPD and RMSSD are on. The
  video ratio can only be ticked with a lux sensor and the scene video. **Sensor signals** is the third, with the same
  choice as the list in the Data tab. The plots that remain share the height, and the time axis is on the last one.
- **Time axis**: the view fits the whole recording when it opens and follows it while you change parameters. Drag with
  the left mouse button (or the middle one) to **pan** in time, or swipe sideways; **right-click** to zoom out; the
  wheel zooms around the pointer. The time axis stays inside the recording.
- **Zoom button** (the magnifier, top right of the plots, left of Reset view): while it is pressed, the left button draws a rectangle
  and the plots zoom to it (the rectangle is gray), in time and, for the plot you drew on, in value. That plot keeps its value range as you
  move along the time axis; a right click (or Reset view) fits it to the data again. Press the button again to go back
  to panning.
- **Value axes** cannot be dragged. Unless you zoomed one, each fits the data of the time span in view, so zooming in on
  a part shows that part at full height.
- All the left axes are of the same width, so the plots line up whatever the numbers beside them.
- **Reset view** (the four-arrows button in the top right corner of the plots, **View** menu, Ctrl+0, or a double-click on the
  plots) shows the whole recording again. The calibration overlay, events and reference lines never stretch the
  value axes.
- **Handles**: the bars you can move in time (the current video frame, the export start and end, the edges and middle of
  a left-out band, the calibration start) each have a handle in the strip under the first plot (the pupil diameter), two short vertical segments in the
  bar's colour. The time axis is repeated above that plot, so the handles can be read against it. Drag the handle; the bar follows. The bars themselves cannot be dragged, so a drag on the plots is always a
  pan or a zoom.
- The dark orange bar marks the current video frame; its time is shown at its top. Click on either plot to move it, or drag its handle to
  scrub the video: the preview follows while dragging, skipping frames if decoding cannot keep up. **◀ Frame / Frame ▶**
  in the preview move it frame by frame.
- **Luminance** (second plot): the luminance the model uses, in cd/m². With a lux sensor the sensor's average is drawn
  dashed behind it, so the video's contribution is the difference between the two.
- **Video ratio** (third plot, lux sensor with the video): gaze-weighted over whole-frame relative luminance, the
  factor that turns the sensor's average into the luminance used. It follows where the gaze looks; on a uniform view
  it should stay near 1 on a uniform view, and a wide spread is a prompt to compare with *Distribute with the
  scene video* turned off (the summary line then warns): it helps when the sensor sees little of the changing
  screen and only adds noise on a uniform view.
- The dashed green lines are the expected pupil at the display's black and white points: the range the model can
  explain on that device.
- Events from the event log are shaded orange and labelled in the ΔPD plot.

## Calibration sequence

See [Participant calibration](calibration.md) for the procedure.

- **Load sequence… / Built-in**: the colour sequence to overlay: a built-in one (the presenter's full calibration, or the
  20-step staircase used before October 2026), a CSV, or a run file saved by
  the [calibration presenter](calibration-tool.md). A run file's onset times are on the presenting computer's clock,
  so they place the sequence in the recording (the start and the overlay are set; a run played for another recording
  is reported as outside it).
- **Find in recording**: locates the sequence in the analysed video and adapts its step length.
- **Show sequence overlay**: shades each step in its colour on the pupil plot; drag its handle under the plots to move it.
- **Start**: the sequence start in seconds.
- **ΔPD RMS in sequence**: how well the model fits within the sequence, the value to minimise when calibrating
  by hand.
- **Fit light sensitivity** (step 2): the participant's light sensitivity and channel weights (optionally gamma and the display's black level, *Also fit the black level*), with a
  result window showing each step's steady-state pupil against the model.
- **Fit latency and offset** (step 3): the participant's timing and dynamics (neither the pupil scale nor the offset is fitted: set
  *Pupil scale correction* and *Pupil offset* by hand), optionally with the
  transient constriction after brightening (pupillary escape). Its result shows two errors: the **fit error**, what
  the fit minimises (measured − expected in the sequence, without an offset), and the ΔPD RMS in the sequence with
  the current alignment (with alignment 'recording', after the whole recording's median offset).
- **Also fit the fixation weight** (glasses with a lux log): adds the gaze circle's weight to the fit below; it needs a
  scene where the gaze area and the background differ.
- **Fit sensitivity and offset** (glasses with a lux log): the participant's light sensitivity and the pupil offset by
  least squares on ΔPD over the sequence, with the luminance the analysis builds from the sensor (and the video). The
  result window gives the RMS before and after, the sensitivity with its interval, the correlation and warnings;
  Apply also sets the alignment to `fixed` (see [Calibration fit](../processing/calibration-fit.md#glasses-with-a-lux-sensor)).
- **Dynamics** (Params → Participant, drop-down): the latency, always applied, and one switch for the rest: dilation and constriction time
  constants, constriction stages, transient and escape τ (greyed out while the switch is off).

## Video preview

Shows the scene frame matched to the cursor time (by recorded frame timestamps where the device provides them),
the scene circle used as background on Varjo videos (green), the gaze circle (orange), and, with **Values**, the mean
colour and luminance measured in each. **◀ Frame / Frame ▶** step through frames. It sits under the tab pages; **Pop
out** puts it in its own window to see the frame larger and **Dock back** (or closing that window) returns it.
