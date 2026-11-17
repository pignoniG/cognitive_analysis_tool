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
   tie) at which most logged changes have a video change beside them is taken.
3. **Each change.** For every logged change the luminance of the video's background area before and after is measured (the
   median of the stretch from 3 s to 0.8 s before, and from 0.8 s to 3 s after, kept within the neighbouring steps), and the
   moment it crosses the middle of the two levels is found, to better than the video's frame. Changes of less than 10 code
   values are not used. The difference to the logged time is that change's offset.
4. **The estimate.** The median of the offsets (those further than 5 robust standard deviations are dropped), its standard
   error (never below 5 ms, below a frame nothing can be claimed), the spread, and the slope over the recording (Theil–Sen,
   reported; the constant median is the offset used). At least 5 changes are needed; if the log is not found in the video
   (it belongs to another recording, or the clocks are more than 5 s apart) nothing is done and the window says why.

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

- **the pupil** (and the tracker's own events) is placed on the capture by **its response** to the picture;
- **what the computer wrote** (the run file, the logger's lux and sensors, the exported Unix times) by the run file's own offset,
  when a run file is next to the capture or the export; the difference between the two is reported as the clocks' difference.

Only when the pupil's response cannot be used (a picture that hardly changes) does the run file place the pupil too, with a
warning that it assumes the two clocks agree. The pupil's response is estimated as follows: the lag at which the pupil's speed best follows the changes of the picture's log luminance (low-passed with
0.4 s), searched from −2.5 to +3.5 s, less an assumed latency of 0.5 s; its uncertainty is half the width of the correlation's
peak. It needs at least 5 large changes of the picture and a correlation of 0.2, and it is coarser: the fitted latency of the
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
