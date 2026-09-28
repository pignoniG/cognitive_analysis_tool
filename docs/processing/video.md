# Scene video analysis

`cwtool/video.py`. For every valid gaze sample, the frame shown at that moment is measured in two areas:

- the **gaze circle** (fixation area): a disc of `fixation_radius_deg` (default 5.25°) around the gaze point;
- the **background**: the rest of the visible scene. On circular Varjo captures the visible scene is a centred
  circle of `field_radius` × half the frame height (default 0.8), which excludes the black corners; on other
  devices it is the whole frame. By default the gaze circle is removed from the background
  (`background_excludes_fixation`), as in the paper and Eckert et al.

The luminance used later is a weighted sum of the two (default 65 % gaze circle, 35 % background).

## Geometry

Frames are downscaled to `analysis_width` (500 px) before measuring. The gaze circle's radius in pixels is

\[
r = \frac{\text{fixation\_radius\_deg}}{\text{vertical field of view}} \cdot h
\]

with \(h\) the analysed frame height and the vertical field of view from the device profile. This assumes a linear
lens mapping ([open issue 33](../OPEN_ISSUES.md) for the wide-angle cameras of glasses trackers). 5.25° equals the
earlier default of 1/8 of the scene circle on the Varjo XR-4.

## Linearising before averaging

Video code values are gamma-encoded. The mean of a textured area must be taken on linear values: the mean of
\((C/255)^\gamma\), not the mean code value raised to \(\gamma\). A black-and-white checkerboard, for example, has a
mean code value of 128, which decodes to 22 % of white, while its real mean luminance is 50 %.

So that gamma can still change in the app without re-reading the video, each area's per-channel histogram is turned
into linear means for every gamma on a grid (1.4 to 3.0 in steps of 0.2). The signal pass interpolates between grid
points in log space, with an error below 0.001 of full scale. Frames are downscaled with nearest-neighbour sampling
for the same reason: it keeps real pixel values instead of averaging code values.

Per sample the pass stores the mean 8-bit colour of each area (for display), the linear means of the gaze circle,
the background and the whole visible scene for each gamma.

## Matching gaze samples to frames

- Devices with **recorded frame timestamps** (Pupil Core, Neon): each gaze sample uses the frame whose timestamp is
  nearest, as Pupil Player does. Scene cameras drop frames, so a fixed frame rate would drift.
- Devices with a **constant frame rate** (Varjo, Tobii Pro Glasses 3): frame \(n\) covers \([n/\text{fps}, (n+1)/\text{fps})\).

Samples outside the video, or with invalid gaze, are skipped.

## Speed

Every frame has to be decoded (compressed video needs it), but only frames with gaze samples are converted and
measured.

- Decoding uses PyAV, which scales and converts to RGB inside FFmpeg with its own threads; OpenCV is the fallback.
- The frame range is split into chunks (at least 150 frames each, one per CPU core by default) decoded in parallel
  threads. The result does not depend on the number of chunks.
- Frames are numbered by their presentation timestamps, so chunk seeks land on exactly the right frame.

For reference: 251 s of 4K H.264 Varjo capture in 49 s on 4 cores; 100 s of Pupil Core world video in about 15 s.

## Cache

The result is saved as `cwtool_video.csv` with `cwtool_video.json` next to the recording. It is reused only if the
format version, gamma grid, video settings, video file name, frame timestamps and gaze samples all match, so it is
never silently stale. See [Output files](../reference/outputs.md#video-cache).
