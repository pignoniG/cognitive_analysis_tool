"""Command-line entry point: ``cwtool RECORDING [options]``."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from cwtool import devices, pipeline, sensors
from cwtool.params import DisplayPhotometry, Parameters, VideoSettings
from cwtool.trim import TRIM_FILE, Trim
from cwtool.video import VideoResult, analyse_video


def main(argv: list[str] | None = None) -> int:
    """Load a recording, analyse its video (or reuse the cached analysis), run the pipeline and
    export. Returns the exit code."""
    ap = argparse.ArgumentParser(prog="cwtool", description="Luminance-compensated pupillometry")
    ap.add_argument("recording", type=Path, help="recording folder")
    ap.add_argument("--device", choices=sorted(devices.READERS), help="default: auto-detect")
    ap.add_argument("--params", type=Path, help="participant parameters JSON")
    ap.add_argument("--display", type=Path,
                    help="display photometry JSON (display devices; participant files do not hold it)")
    ap.add_argument("--lux", type=Path, help="folder with lux sensor logs (glasses; default: in the recording)")
    ap.add_argument("--out", type=Path, help="export folder (default: RECORDING/cwtool_export)")
    ap.add_argument("--sensors", type=Path, metavar="FOLDER",
                    help="sensor logger session folder (Shimmer, EmotiBit) to add to the export, trimmed like the "
                         "rest (default: any in the recording folder)")
    ap.add_argument("--start", type=float, metavar="S", help="leave out everything before S seconds (export only)")
    ap.add_argument("--end", type=float, metavar="S", help="leave out everything after S seconds (export only)")
    ap.add_argument("--exclude", type=float, nargs=2, action="append", default=[], metavar=("FROM", "TO"),
                    help="leave out FROM..TO seconds, e.g. a calibration (repeatable). Seconds are those of "
                         "timestamp_relative. Without --start, --end and --exclude, the trim saved by the "
                         "app with the recording is used")
    ap.add_argument("--reanalyse", action="store_true", help="ignore the cached video analysis")
    ap.add_argument("--workers", type=int, default=0, help="parallel video chunks (default: one per CPU core)")
    ap.add_argument("--plot", action="store_true", help="save a PDF plot (needs matplotlib)")
    args = ap.parse_args(argv)

    rec = devices.load(args.recording, args.device, lux_folder=args.lux)
    params = Parameters.load(args.params, rec.profile) if args.params else Parameters()
    if args.display:
        params = DisplayPhotometry.load(args.display).apply(params)
    settings = VideoSettings().for_recording(rec)
    print(f"{rec.device} recording {rec.name}: {len(rec.time)} samples, {rec.time[-1] - rec.time[0]:.1f} s")

    if rec.scene_video is None:
        print("No scene video found", file=sys.stderr)
        return 1
    video = None if args.reanalyse else VideoResult.load_cached(rec.folder, settings, rec.scene_video,
                                                                      rec.scene_frame_times, rec.gaze)
    if video is None:
        print(f"Analysing {rec.scene_video.name} ...")
        video = analyse_video(rec.scene_video, rec.time, rec.gaze, settings,
                              progress=lambda p: print(f"\r{p:5.0%}", end="", flush=True), workers=args.workers,
                              frame_times=rec.scene_frame_times)
        print()
        video.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)

    result = pipeline.run(rec, video, params)
    print(f"ΔPD RMS: {result.cw_rms:.3f} mm, SD: {result.cw_sd:.3f} mm "
          f"({result.measured_rate:.0f} Hz resampled to {result.rate:.0f} Hz, {result.gap_fraction:.1%} in gaps)")
    if math.isfinite(result.leak_r2):
        print(f"Light left in ΔPD: R² {result.leak_r2:.2f}, {result.leak_slope:+.3f} mm per tenfold luminance")
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.out or rec.folder / "cwtool_export"
    if args.start is None and args.end is None and not args.exclude:
        trim = Trim.load(rec.folder / TRIM_FILE)
        if trim.active:
            print(f"Using the trim saved with the recording ({TRIM_FILE})")
    else:
        trim = Trim(args.start, args.end, [tuple(x) for x in args.exclude])
    found = []
    if len(rec.time) and math.isfinite(rec.epoch_start):
        span = float(rec.time[-1] - rec.time[0])
        found = sensors.load_sensors(args.sensors or rec.folder, rec.epoch_start + float(rec.time[0]), span)
    elif args.sensors:
        print("The recording has no absolute time: sensor data cannot be aligned", file=sys.stderr)
    for p in pipeline.export(result, rec, params, out, trim=trim, sensors=found):
        print(f"wrote {p}")
    if args.plot:
        from cwtool.plot import plot_result
        p = out / f"{rec.name}_plot.pdf"
        plot_result(result, rec).savefig(p, bbox_inches="tight")
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
