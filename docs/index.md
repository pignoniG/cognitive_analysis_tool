# Cognitive Workload Tool

The pupil dilates with cognitive workload, but it reacts far more strongly to light. This tool estimates how
large the pupil *should* be for the light reaching the eye, and reports what is left: the **ΔPD**
(pupil diameter difference), a measure of cognitive workload that can be used outside the laboratory's constant
lighting.

\[
\Delta PD(t) = PD_\text{measured}(t) - PD_\text{expected}\big(L(t)\big)
\]

The expected pupil comes from the Watson & Yellott unified formula, driven by an estimate of the luminance \(L\)
the participant is looking at. That estimate is built from the eye tracker's scene video and gaze: a small circle
around the gaze point weighted against the rest of the view. With glasses-type trackers the absolute level comes
from an external lux sensor worn on the tracker.

## Supported devices

| Device | Recording | Pupil | Luminance from |
|---|---|---|---|
| [Varjo XR-4](devices/varjo.md) | Varjo Base eye tracking recorder | mm (reported radius ×2) | the headset's display, via the scene capture, the display photometry and the participant's fitted light sensitivity |
| [Pupil Core](devices/pupil-core.md) | Pupil Player export | mm (3D model) or px | external lux sensor, distributed with the scene video |
| [Pupil Neon](devices/pupil-neon.md) | Pupil Cloud Timeseries export or native format | mm | external lux sensor, distributed with the scene video |

One recording is analysed at a time. A new device needs only a reader module; the analysis is shared
(see [Devices](devices/index.md)).

## What is in the package

- `cwtool`: the analysis, as a Python package that runs without a GUI.
- `cwtool-gui`: a Qt desktop app for Windows, macOS and Linux, with live plots, the video preview, the calibration
  sequence overlay and the participant calibration fit.
- `cwtool`: a command-line tool for batch processing.
- `tools/`: the lux sensor logger and an experiment event logger.

## Where to start

- New user: [Installation](getting-started/installation.md), then [First analysis](getting-started/first-analysis.md).
- Varjo study: [Participant calibration](usage/calibration.md).
- Understanding the numbers: [Pipeline overview](processing/overview.md).
- Known problems and decisions still open: [Open issues](OPEN_ISSUES.md).

!!! note "Version 2.0 is in development"
    This documentation describes the `v2.0` branch. Version 1.x (the macOS application for the Pupil Core and
    the Varjo build) lives on `master` and `develop-varjo`.

## Publications

- Pignoni G., Komandur S., Volden F. (2021). *Accounting for Effects of Variation in Luminance in Pupillometry for
  Field Measurements of Cognitive Workload*. IEEE Sensors Journal. The lux sensor method used for the Pupil devices.
- Pignoni G., Grandi F., Peruzzini M. *Toward Reliable Pupillometry in Extended Reality Environments* (draft). The
  Varjo method: display photometric calibration and the two-circle luminance estimate.

See [References](reference/references.md) for the models and related work.
