"""Command-line entry point: ``cwtool RECORDING [options]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cwtool import devices, pipeline
from cwtool.params import Parameters, VideoSettings
from cwtool.video import VideoResult, analyse_video


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cwtool", description="Luminance-compensated pupillometry")
    ap.add_argument("recording", type=Path, help="recording folder")
    ap.add_argument("--device", choices=sorted(devices.READERS), help="default: auto-detect")
    ap.add_argument("--params", type=Path, help="participant parameters JSON")
    ap.add_argument("--out", type=Path, help="export folder (default: RECORDING/cwtool_export)")
    ap.add_argument("--reanalyse", action="store_true", help="ignore the cached video analysis")
    ap.add_argument("--plot", action="store_true", help="save a PDF plot (needs matplotlib)")
    args = ap.parse_args(argv)

    rec = devices.load(args.recording, args.device)
    params = Parameters.load(args.params, rec.profile) if args.params else Parameters()
    settings = VideoSettings().for_recording(rec)
    print(f"{rec.device} recording {rec.name}: {len(rec.time)} samples, {rec.time[-1] - rec.time[0]:.1f} s")

    if rec.scene_video is None:
        print("No scene video found", file=sys.stderr)
        return 1
    video = None if args.reanalyse else VideoResult.load_cached(rec.folder, settings, rec.scene_video)
    if video is None:
        print(f"Analysing {rec.scene_video.name} ...")
        video = analyse_video(rec.scene_video, rec.time, rec.gaze, settings,
                              progress=lambda p: print(f"\r{p:5.0%}", end="", flush=True))
        print()
        video.save(rec.folder, settings, rec.scene_video)

    result = pipeline.run(rec, video, params)
    print(f"ΔPD RMS: {result.cw_rms:.3f} mm, SD: {result.cw_sd:.3f} mm "
          f"({result.measured_rate:.0f} Hz resampled to {result.rate:.0f} Hz, {result.gap_fraction:.1%} in gaps)")
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    out = args.out or rec.folder / "cwtool_export"
    for p in pipeline.export(result, rec, params, out):
        print(f"wrote {p}")
    if args.plot:
        from cwtool.plot import plot_result
        p = out / f"{rec.name}_plot.pdf"
        plot_result(result, rec).savefig(p, bbox_inches="tight")
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
