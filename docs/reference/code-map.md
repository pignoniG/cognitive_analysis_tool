# Code map

```text
cwtool/
├── recording.py        Recording, DeviceProfile, Event: the device-independent data model
├── params.py           Parameters (signal pass), VideoSettings (video pass), DisplayPhotometry (its own file);
│                       JSON load/save, 1.x conversion, unused_parameters() for the GUI
├── devices/
│   ├── __init__.py     READERS, detect(), load()
│   ├── common.py       event logs, markers → events, binning, sample rate, field of view (pinhole and lens distortion)
│   ├── varjo.py        Varjo XR-4 (Varjo Base)
│   ├── pupil_core.py   Pupil Core (Pupil Player export)
│   ├── neon.py         Pupil Neon (Pupil Cloud export, native format), experimental
│   └── tobii_g3.py     Tobii Pro Glasses 3 (SD card recording folder), experimental
├── lux.py              lux log files (hourly 1.x files and the logger's lux.csv): find, read, smooth, lux → average luminance
├── sensors.py          the sensor logger's Shimmer and EmotiBit files (with their saved settings): find, read, cut, write
├── hrv.py              heart rate variability from a Shimmer's ECG: R peaks (NeuroKit2), trusted intervals, measures per window
├── trim.py             Trim: the part of a recording an export keeps (start, end, left-out segments)
├── video.py            scene video pass: frame clock, decoding (PyAV/OpenCV), parallel chunks, two-area
│                       measurement, gamma grid, gaze weighting (VideoResult.weighted), cache
├── luminance.py        code values → linear, relative and absolute luminance
├── model.py            Watson & Yellott, Stanley & Davies, delay, attack/release (dilation in two parts), transient
├── pipeline.py         prepare(), run(), export(): from recording + video pass + parameters to ΔPD
├── quality.py          tracking quality of a recording: valid samples, dropouts, the tracker's ceiling, the assumed iris
├── alignment.py        the presenter's log aligned to the scene video (the offset between the two clocks; Varjo)
├── calibration.py      calibration sequences: built-in (time-course, full, staircase), CSV and run files, locate in a recording
├── calfit.py           the participant's calibration fit on the pupil's time course: light response and timing together,
│                       for every device and luminance route; its search ranges and priors
├── onsets.py           the response latency from the constriction onsets at the sequence's brightening steps
├── photometry.py       earlier fits, not used by the app: light sensitivity from step levels, and the lux sensor fit
├── fit.py              earlier fit, not used by the app: latency, dynamics and transient after the light response
├── logger/             the multi-sensor logger (no Qt except gui.py); see usage/logger.md
│   ├── base.py         Source (one sensor stream), ClockMapper (device clock → Unix time)
│   ├── session.py      Logger (sources, live buffers, session folder, writer thread), EventLog
│   ├── sinks.py        CsvSink
│   ├── protocol.py     protocol files (name,duration)
│   ├── clockcheck.py   timestamp checks of a recorded session (regularity, Shimmer drift, Shimmer vs EmotiBit offset)
│   ├── gui.py          the window (cwtool-logger), plot scaling, stall watchdog
│   └── sources/        lux (serial), shimmer (pyshimmer), lsl (EmotiBit via the Oscilloscope), simulated;
│                       rfcomm_mac.py + rfcomm_helper.py: direct Bluetooth channel on macOS
├── cli.py              the cwtool command
                        (gui/ and logger/ each have a __main__.py: python -m cwtool.gui, python -m cwtool.logger)
├── plot.py             matplotlib figure for exports
├── palette.py          project colours, shared by the app, its plots and the PDF plot
└── gui/
    ├── main_window.py  window, menus, recording/video/calibration panels, background tasks
    ├── param_panel.py  parameter editors (every Parameters field must have one)
    ├── plots.py        pyqtgraph plots, sequence overlay, cursor, sensor plots, export range overlay
    ├── side_panel.py   the rail of tabs, pills, numbered steps and the preview holder of the left column
    ├── trim_panel.py   the export range editor in the sidebar
    ├── errors.py       plain-language advice for errors and the gestures/shortcuts list of the Help menu (no Qt)
    ├── icons.py        the icon loader (Tabler outline SVGs in icons/, drawn in the palette's colours)
    ├── video_preview.py      scene frame at the cursor with the analysis circles
    └── workers.py      QThread wrapper for the video pass and the fit

tools/
├── lux_logger.py       lux sensor over USB serial → hourly CSVs (1.x format; the sensor logger writes lux.csv)
├── event_logger.py     experiment phases → event_log CSV
└── example_protocol.csv

tests/                  pytest suite with synthetic recordings for every device (conftest.py); one file per area,
                        each with a header saying what it covers
docs/                   this site (MkDocs)
Lux Sensor/             lux logger firmware and 3D-printable mount
```

## Main entry points

| Function | Does |
|---|---|
| `devices.load(folder, device=None, **options)` | read a recording |
| `video.analyse_video(video, time, gaze, settings, frame_times=...)` | video pass |
| `video.VideoResult.load_cached(...)` / `.save(...)` | cache |
| `pipeline.run(rec, video, params)` | signal pass, returns a `Result` |
| `pipeline.export(result, rec, params, folder, trim=, sensors=)` | the export package: CSVs, sensor files, parameters, manifest; trimmed |
| `sensors.load_sensors(folder, epoch_start, duration)` | the logger's sensor files, cut to a recording |
| `calibration.locate(time, rgb, sequence, gamma)` | find the calibration sequence |
| `calfit.fit_calibration(rec, video, params, start, sequence)` | participant fit: light response and timing together, on the pupil's time course (every device) |
| `photometry.fit_light_response(...)`, `fit.fit_calibration(...)`, `photometry.fit_lux_response(...)` | the earlier step-level fits, kept for comparison |
| `pipeline.calibrate_camera(rec, video, params)` | full-scale luminance of a fixed-exposure scene camera |
| `logger.Logger().add(source)` / `.start_recording(folder)` / `.stop_recording()` | record sensors into a session folder |

The processing steps and the functions that carry them out are listed in order in
[Processing at a glance](../processing/pipeline.md).
