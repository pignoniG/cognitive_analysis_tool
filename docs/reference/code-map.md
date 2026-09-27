# Code map

```text
cwtool/
├── recording.py        Recording, DeviceProfile, Event: the device-independent data model
├── params.py           Parameters (signal pass) and VideoSettings (video pass); JSON load/save and 1.x conversion
├── devices/
│   ├── __init__.py     READERS, detect(), load()
│   ├── common.py       event logs, markers → events, binning, sample rate, pinhole field of view
│   ├── varjo.py        Varjo XR-4 (Varjo Base)
│   ├── pupil_core.py   Pupil Core (Pupil Player export)
│   └── neon.py         Pupil Neon (Pupil Cloud export, native format)
├── lux.py              lux log files: find, read, smooth, lux → average luminance
├── video.py            scene video pass: frame clock, decoding (PyAV/OpenCV), parallel chunks, two-area
│                       measurement, gamma grid, cache
├── luminance.py        code values → linear, relative and absolute luminance
├── model.py            Watson & Yellott, Stanley & Davies, delay, attack/release
├── pipeline.py         prepare(), run(), export(): from recording + video pass + parameters to ΔPD
├── calibration.py      calibration sequences: built-in, CSV, locate in a recording
├── fit.py              participant fit on the calibration sequence
├── cli.py              the cwtool command
├── plot.py             matplotlib figure for exports
└── gui/
    ├── main_window.py  window, menus, recording/video/calibration panels, background tasks
    ├── param_panel.py  parameter editors (every Parameters field must have one)
    ├── plots.py        pyqtgraph plots, sequence overlay, cursor
    ├── video_preview.py
    └── workers.py      QThread wrapper for the video pass and the fit

tools/
├── lux_logger.py       lux sensor over USB serial → hourly CSVs
├── event_logger.py     experiment phases → event_log CSV
└── example_protocol.csv

tests/                  pytest suite with synthetic recordings for every device (conftest.py)
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
| `pipeline.export(result, rec, params, folder)` | CSVs and parameters |
| `calibration.locate(time, rgb, sequence, gamma)` | find the calibration sequence |
| `fit.fit_calibration(rec, video, params, start, end)` | participant fit |
