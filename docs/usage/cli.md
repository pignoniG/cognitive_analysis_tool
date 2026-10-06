# Command line

```text
cwtool RECORDING [--device {pupil_core,pupil_neon,tobii_g3,varjo}] [--params FILE] [--display FILE]
                 [--lux FOLDER] [--sensors FOLDER] [--start S] [--end S] [--exclude FROM TO]
                 [--out FOLDER] [--reanalyse] [--workers N] [--plot]
```

| Option | Meaning |
|---|---|
| `RECORDING` | recording folder |
| `--device` | skip auto-detection |
| `--params` | participant parameter file (JSON) saved by the app; defaults otherwise |
| `--display` | display photometry file (JSON) saved by the app (Varjo); participant files do not hold Lmin, Lmax and gamma, so without it the defaults are used |
| `--lux` | folder with lux sensor logs (glasses), searched with its subfolders; default: the recording folder or its `lux` subfolder |
| `--sensors` | [sensor logger](logger.md) session folder (Shimmer, EmotiBit) to add to the export, trimmed like the rest; default: any logger files in the recording folder |
| `--start`, `--end` | leave out everything before or after this time, in seconds on the exports' `timestamp_relative` axis |
| `--exclude FROM TO` | leave out FROM to TO seconds, for example a calibration; repeat for several segments |
| `--out` | export folder; default `RECORDING/cwtool_export` |
| `--reanalyse` | ignore the cached video analysis |
| `--workers` | parallel video chunks; default one per CPU core |
| `--plot` | also save a PDF plot (needs the `plot` extra) |

The command prints the device, the ΔPD RMS and SD, and any warnings, then writes the
[output files](../reference/outputs.md). The analysis always runs on the whole recording; `--start`, `--end` and
`--exclude` only trim what is written. Without them, the export range saved by the app next to the recording
(`cwtool_trim.json`) is used.

## Batch processing

A shell loop over participants, each with their own parameter file:

```bash
for p in P01 P02 P03; do
  for rec in data/$p/*/; do
    cwtool "$rec" --params "params/$p.json" --display params/varjo_xr4.json --out "results/$p/$(basename "$rec")"
  done
done
```

## From Python

Everything the app does is available as functions:

```python
from pathlib import Path
from cwtool import devices, pipeline
from cwtool.params import DisplayPhotometry, Parameters, VideoSettings
from cwtool.video import VideoResult, analyse_video

rec = devices.load(Path("data/P01/rec1"))              # auto-detects the device
params = Parameters.load("params/P01.json", rec.profile)
params = DisplayPhotometry.load("params/varjo_xr4.json").apply(params)   # display devices
settings = VideoSettings().for_recording(rec)

video = VideoResult.load_cached(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)
if video is None:
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, settings, frame_times=rec.scene_frame_times)
    video.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)

result = pipeline.run(rec, video, params)
print(result.cw_rms, result.warnings)
pipeline.export(result, rec, params, Path("out"))

# one package for a participant, trimmed, with the sensor logger's files
from cwtool import sensors
from cwtool.trim import Trim
found = sensors.load_sensors(Path("session"), rec.epoch_start + rec.time[0], rec.time[-1] - rec.time[0])
pipeline.export(result, rec, params, Path("package"), sensors=found,
                trim=Trim(start=60.0, exclude=[(310.0, 600.0)]))   # leave out the first minute and a calibration
```
