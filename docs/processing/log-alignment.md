# Aligning the log to the video

The presenter (the [calibration presenter](../usage/calibration-tool.md) and the validation task) logs when it changed what
it showed, on **its computer's clock**: the event log, the visual log, the calibration run file. The tracker's scene video shows
what was actually displayed, on **the tracker's clock**. The two can differ by a fraction of a second: on the first Varjo
run the video showed each change of colour 0.338 s before the log said it happened. That matters for everything matched
by time: the event markers, the placement of the calibration sequence, and the sensor files the [sensor logger](../usage/logger.md)
wrote on the computer's clock (the ECG against the pupil).

The pupil model itself is not affected: it takes its luminance from the video, so it is on the video's clock already.

## What is done

1. **The logged changes.** The `Start (unix s)` of every row of the visual log (`*visual_log*.csv`) and the `onset_unix_ms` of the
   calibration presenter's run file, in the recording's folder (the n-back log has onset times too, but they are digits, not
   changes of the picture, and are not used).
2. **A first guess.** The changes of the picture are found in the video, and the offset (searched over ±5 s, the smaller on a
   tie) at which most logged changes have a video change beside them is taken. When the calibration presenter's run file
   gives each step's colour, the search reaches **±60 s** and an offset counts only if the picture after the changes has the
   logged colours (their correlation over the steps and channels, at least 0.6; the picture's median from 0.3 to 2 s after
   each change), weighted by how well: steps of one length also line up one step away, and the colours tell them apart. On 23
   November 2026 a capture whose start was 10.5 s from the one assumed was placed 8.01 s away by the ±5 s search, with 22 of
   34 changes agreeing to 5 ms ([open issue 61](../OPEN_ISSUES.md)).
3. **Each change.** For every logged change the luminance of the video's background area before and after is measured (the
   median of the stretch from 3 s to 0.8 s before, and from 0.8 s to 3 s after, kept within the neighbouring steps), and the
   moment it crosses the middle of the two levels is found, to better than the video's frame. Changes of less than 10 code
   values are not used. The difference to the logged time is that change's offset.
4. **The estimate.** The median of the offsets (those further than 5 robust standard deviations are dropped), its standard
   error (never below 5 ms, below a frame nothing can be claimed), the spread, and the slope over the recording (Theil–Sen,
   reported; the constant median is the offset used). At least 5 changes are needed; if the log is not found in the video
   (it belongs to another recording, or the clocks are further apart than the search) nothing is done and the window says
   why.

## What it changes

`video time = log time + offset`. The recording is replaced by a copy whose **Unix time of time zero is moved onto the log's
clock** (`epoch_start − offset`), and whose events and lux log, stored relative to the old zero, move by the offset. Everything the
computer wrote then falls where the pupil and the video are: the events, the sensor files and HRV windows (they are matched by Unix
time), the calibration sequence placed from the run file, and the `timestamp_unix` columns of the export (which are now on the
computer's clock, the same as the logs). The export's `<name>_export.json` records the offset, its uncertainty and the changes
used under `log alignment`.

It is done for the Varjo, whose event log is the presenter's. For the other devices the events come from the device's own clock,
which this offset does not describe, so it is not offered, except for a video on a clock of its own (below).

## A video on a clock of its own: a Neon inside a Meta Quest

The Quest's capture runs on the headset's clock, placed only to a second by its name; the Neon's pupil is on the phone's clock,
and the presenter's log on its computer's ([Neon inside a Meta Quest](../devices/pupil-neon.md#neon-inside-a-meta-quest)). Three
clocks, and the first recording showed the computer's 1.5 s ahead of the phone's: aligned by the run file, the pupil's response
came before the light (the fitted latency went to zero and the fit got worse, 0.36 against 0.24 mm). So:

- **what the computer wrote** (the run file, the logger's lux and sensors, the exported Unix times) by the run file's own offset,
  when a run file is next to the capture or the export;
- **the pupil** (and the tracker's own events), when the run file ends with the [gaze check](gaze-check.md), by **the gaze's
  saccades** to its dots: the gaze (on the tracker's clock) is matched to the logged places (on the computer's), first by its
  correlation with them over ±20 s, then saccade by saccade, at the moment it is half-way from one place to the next. The
  median of those moments after the logged onsets, less a saccade latency of 0.2 s, is how far the tracker's clock is ahead
  of the computer's; at least 4 saccades agreeing within 0.15 s (robust SD) are needed. A saccade's latency is short and
  steady, unlike the pupil's, so the pupil's offset is no longer confounded with its latency. On 23 November 2026 the 8
  saccades came 3.191 s after the onsets (SD 0.017 s): the phone 3.0 s ahead of the computer;
- otherwise the pupil by **its response** to the picture.

The difference between the computer's and the tracker's clocks is reported. Only when neither the gaze check nor the pupil's
response can be used (a picture that hardly changes) does the run file place the pupil too, with a warning that it assumes
the two clocks agree. The pupil's response is estimated as follows: the lag at which the pupil's speed best follows the changes of the picture's log luminance (low-passed with
0.4 s), searched from −8 to +8 s (the name's second and the clocks' difference: 3 s on 23 November), less an assumed latency
of 0.5 s; its uncertainty is half the width of the correlation's peak. It needs at least 5 large changes of the picture and a correlation of 0.2, and it is coarser: the fitted latency of the
calibration then holds what the assumed one misses. The switch reads *Align the capture to the pupil* for these recordings.

## In the window and on the command line

*Align the presenter's log to the video* in the Data tab (on by default for a Varjo recording) runs it when the video analysis
is ready and shows the result under the video line ("the video leads the log by 0.338 s (±0.005 s, 156 changes)"). Turning it off
puts the recording back as it was read. `cwtool RECORDING` does the same, and `--no-align-log` leaves it out.

## What is not known

The offset is measured, not explained. It may come from the Varjo's conversion of its own timestamps to the computer's Unix time,
or from the page's logged times (the log is written from the frame time of the page); the validation task also records the
offset between the page's clock and the server's (`clock_offset.csv`), which does not reach this one (open issue 54). On the
first run the offset was the same in the calibration part (31 changes: 0.338 s, spread 4 ms) and in the 25 minutes of the session
(75 changes: 0.338 s, spread 7 ms), so it was constant there; other runs and other computers are untested.
