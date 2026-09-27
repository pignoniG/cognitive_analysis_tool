# Command line

```text
cwtool RECORDING [--device {pupil_core,pupil_neon,varjo}] [--params FILE] [--lux FOLDER]
                 [--out FOLDER] [--reanalyse] [--workers N] [--plot]
```

| Option | Meaning |
|---|---|
| `RECORDING` | recording folder |
| `--device` | skip auto-detection |
| `--params` | participant parameter file (JSON) saved by the app; defaults otherwise |
| `--lux` | folder with lux sensor logs (Pupil devices); default: the recording folder or its `lux` subfolder |
| `--out` | export folder; default `RECORDING/cwtool_export` |
| `--reanalyse` | ignore the cached video analysis |
| `--workers` | parallel video chunks; default one per CPU core |
| `--plot` | also save a PDF plot (needs the `plot` extra) |

The command prints the device, the ΔPD RMS and SD, and any warnings, then writes the
[output files](../reference/outputs.md).

## Batch processing

A shell loop over participants, each with their own parameter file:

```bash
for p in P01 P02 P03; do
  for rec in data/$p/*/; do
    cwtool "$rec" --params "params/$p.json" --out "results/$p/$(basename "$rec")"
  done
done
```

## From Python

Everything the app does is available as functions:

```python
from pathlib import Path
from cwtool import devices, pipeline
from cwtool.params import Parameters, VideoSettings
from cwtool.video import VideoResult, analyse_video

rec = devices.load(Path("data/P01/rec1"))              # auto-detects the device
params = Parameters.load("params/P01.json", rec.profile)
settings = VideoSettings().for_recording(rec)

video = VideoResult.load_cached(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)
if video is None:
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, settings, frame_times=rec.scene_frame_times)
    video.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)

result = pipeline.run(rec, video, params)
print(result.cw_rms, result.warnings)
pipeline.export(result, rec, params, Path("out"))
```
