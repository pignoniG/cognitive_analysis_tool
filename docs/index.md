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
| [Varjo XR-4](devices/varjo.md) | Varjo Base eye tracking recorder | mm (radius ×2 in older exports, diameter in newer ones) | the headset's display, via the scene capture, the display photometry and the participant's fitted light sensitivity |
| [Pupil Core](devices/pupil-core.md) | Pupil Player export | mm (3D model) or px | external lux sensor, distributed with the scene video |
| [Pupil Neon](devices/pupil-neon.md) (experimental) | Pupil Cloud Timeseries export or native format | mm | external lux sensor, distributed with the scene video |
| [Tobii Pro Glasses 3](devices/tobii-g3.md) (experimental) | recording folder from the SD card | mm | external lux sensor, distributed with the scene video |

One recording is analysed at a time. A new device needs only a reader module; the analysis is shared
(see [Devices](devices/index.md)).

## What is in the package

- `cwtool`: the analysis, as a Python package that runs without a GUI.
- `cwtool-gui`: a Qt desktop app for Windows, macOS and Linux, with live plots, the video preview, the calibration
  sequence overlay and the participant calibration fit.
- `cwtool`: a command-line tool for batch processing.
- `cwtool-logger`: a Qt app that records the lux sensor, a Shimmer and an EmotiBit, with experiment events
  ([Sensor logger](usage/logger.md)).
- `tools/`: the original command-line lux sensor logger and experiment event logger.

## Where to start

- New user: [Installation](getting-started/installation.md), then [First analysis](getting-started/first-analysis.md).
- Varjo study: [Participant calibration](usage/calibration.md).
- Understanding the numbers: [Pipeline overview](processing/overview.md).
- Known problems and decisions still open: [Open issues](OPEN_ISSUES.md).

!!! note "Version 2.0 is in development"
    This documentation describes the `master_v2.0` branch. Version 1.x lives on the legacy branches:
    `legacy-pupilCore` (the macOS application for the Pupil Core), `legacy-varjo` (the Varjo build) and
    `legacy-TobiiProIII` (the Tobii Pro Glasses 3 build).

## Publications

- Pignoni G., Komandur S., Volden F. (2021). *Accounting for Effects of Variation in Luminance in Pupillometry for
  Field Measurements of Cognitive Workload*. IEEE Sensors Journal. The lux sensor method used for the glasses trackers.
- Pignoni G., Grandi F., Peruzzini M. *Toward Reliable Pupillometry in Extended Reality Environments*. Manuscript in preparation, not yet published. The
  Varjo method: display photometric calibration and the two-circle luminance estimate.

Earlier and related publications (2019–2022), the models and related work are listed in
[References](reference/references.md).
