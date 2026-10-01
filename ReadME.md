# Cognitive Workload Tool 2.0

Luminance-compensated pupillometry: an estimate of cognitive workload from the pupil that can be used outside the
laboratory's constant lighting.

The pupil dilates with cognitive workload but reacts far more strongly to light. The tool estimates the pupil size
the light reaching the eye should produce (Watson & Yellott's unified formula, with the participant's latency and
pupil dynamics), and reports what is left, the **ΔPD**:

```
ΔPD(t) = measured pupil(t) − expected pupil(luminance(t))
```

The luminance is estimated from the eye tracker's scene video and gaze: a circle around the gaze point weighted
against the rest of the view. On a headset it comes from the display's photometry; with glasses trackers, the
absolute level comes from a lux sensor worn on the tracker.

**Documentation:** https://pignonig.github.io/cognitive_analysis_tool/ covers installation, usage, the device
formats and every processing step ([Processing at a glance](https://pignonig.github.io/cognitive_analysis_tool/processing/pipeline/)).
Its source is in `docs/`.

> Version 2.0 is in development. The 1.x tools are kept, for archive only, on the `legacy-*` branches.

## Supported devices

| Device | Recording | Luminance from | Support |
|---|---|---|---|
| Varjo XR-4 | Varjo Base eye tracking recorder | the display: scene capture, display photometry, participant light sensitivity | tested |
| Pupil Core | Pupil Player export | external lux sensor + scene video | tested |
| Pupil Neon | Pupil Cloud Timeseries export or native format | external lux sensor + scene video | experimental |
| Tobii Pro Glasses 3 | recording folder from the SD card | external lux sensor + scene video | experimental |

Experimental readers were written from the manufacturer's documentation and have not yet been checked on a real
recording; every result from them carries a warning.

## Install and run

Python 3.10 or newer, on Windows, macOS or Linux.

```bash
git clone -b master_v2.0 https://github.com/pignoniG/cognitive_analysis_tool.git
cd cognitive_analysis_tool
pip install -e ".[gui]"

cwtool-gui [path/to/recording]                                   # desktop app
cwtool path/to/recording --params participant.json --plot        # command line, batch processing
```

In the app, open a recording folder: the scene video is analysed in the background (or loaded from its cache), and
every parameter change updates the measured and expected pupil and ΔPD plots at once. A video preview shows the
analysed areas on the scene frame at the cursor. Results are exported as CSV files with per-event means.

## What is in the repository

| Path | Content |
|---|---|
| `cwtool/` | the analysis as a Python package that runs without a GUI; `cwtool/gui/` is the Qt app |
| `tools/` | the lux sensor logger and an experiment event logger |
| `docs/` | the documentation site, including the calibration presenter (a web page that plays the calibration sequence on a screen or in VR) |
| `Lux Sensor/` | firmware for the lux logger and the 3D-printable mount for the Pupil Core |
| `tests/` | pytest suite with synthetic recordings for every device |

## Participant calibration (Varjo)

A short full-field colour sequence, shown in the headset, gives each participant's light sensitivity and channel
weights, then their response latency and pupil dynamics (the pupil scale and offset stay values you set). These are saved with the participant's
parameters and applied to their other recordings. The display's own photometry (black and white luminance, gamma) is
kept in a separate file. See [Participant calibration](https://pignonig.github.io/cognitive_analysis_tool/usage/calibration/).

## Development

```bash
pip install -e ".[gui,dev]"
pytest
pip install -r docs/requirements.txt && mkdocs serve   # documentation preview
```

Known problems and decisions still open are tracked in `docs/OPEN_ISSUES.md`.

## Publications

- Pignoni G., Komandur S., Volden F. (2021). *Accounting for Effects of Variation in Luminance in Pupillometry for
  Field Measurements of Cognitive Workload*. IEEE Sensors Journal. The lux sensor method.
- Pignoni G., Grandi F., Peruzzini M. *Toward Reliable Pupillometry in Extended Reality Environments*. Manuscript in preparation, not yet published. The
  Varjo method.

Earlier and related publications (2019–2022) are listed in the documentation's
[References](https://pignonig.github.io/cognitive_analysis_tool/reference/references/). The tool started as part of a
master's thesis in MIXD at NTNU Gjøvik (2018–2019).

## License

MIT License, see [LICENSE.md](LICENSE.md).
