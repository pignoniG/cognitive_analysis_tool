"""Tests of a Neon worn inside a Meta Quest: the Quest's capture is found next to the recording and becomes the scene video
(XR route), its frames are timed from the container, the gaze is placed by its direction, and the capture's own clock is
aligned from the presenter's log or from the pupil's response (open issue 61)."""

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from cwtool import alignment, devices
from cwtool.devices import quest
from cwtool.video import GAMMA_GRID, VideoResult
from conftest import write_neon_recording

START_NS = 1_700_000_000_000_000_000
FRAME_TIMES = np.arange(90) / 30
GRAYS = [40] * 45 + [220] * 45


def _capture_name(unix: float, app="com.oculus.vrshell") -> str:
    return f"{app}-{datetime.fromtimestamp(unix).strftime('%Y%m%d-%H%M%S')}-0.mp4"


def _write_capture(path: Path, grays, fps=30, size=(64, 36)):
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for g in grays:
        writer.write(np.full((h, w, 3), g, dtype=np.uint8))
    writer.release()
    return path


def test_capture_names():
    name = "com.meta.pclinkservice.server-20261116-112913-0.mp4"
    assert quest.is_capture(Path(name)) and quest.app_of(Path(name)) == "com.meta.pclinkservice.server"
    assert not quest.is_capture(Path("a1b2c3d4_0-10.mp4")) and not quest.is_capture(Path("._" + name))
    # read in a given zone (s east of UTC): 11:29:13 at UTC+1 is 10:29:13 UTC
    assert quest.capture_start(Path(name), 3600) == datetime(2026, 11, 16, 10, 29, 13).replace(
        tzinfo=__import__("datetime").timezone.utc).timestamp()
    assert quest.capture_start(Path("other.mp4"), 0) is None


def test_gaze_straight_ahead_is_the_middle_of_the_capture():
    xy = quest.gaze_to_capture(np.array([0.0, 55.0, 0.0]), np.array([0.0, 0.0, -39.0]))
    assert xy[0] == pytest.approx([0.5, 0.5])
    assert xy[1] == pytest.approx([1.0, 0.5])               # half the field to the right: the right edge
    assert xy[2] == pytest.approx([0.5, 1.0])               # half the field down: the bottom edge


def _xr_recording(tmp_path, frame_name="Quest3 XR", capture_offset=0.4, with_capture=True):
    """A Cloud Neon export in a folder whose parent holds a Quest capture started ``capture_offset`` s after the Neon's
    first eye sample (the name is truncated to the second, as the Quest writes it)."""
    local = datetime.fromtimestamp(START_NS / 1e9).strftime("%Y-%m-%d_%H-%M-%S")    # the export is named in local time
    folder = write_neon_recording(tmp_path / "session" / f"{local}-a1b2c3d4", GRAYS, FRAME_TIMES)
    info = json.loads((folder / "info.json").read_text())
    if frame_name:
        info["frame_name"] = frame_name
    (folder / "info.json").write_text(json.dumps(info))
    capture = None
    if with_capture:
        start = START_NS / 1e9 + capture_offset
        capture = _write_capture(folder.parent / _capture_name(start), [10] * 30 + [250] * 30)
    return folder, capture


def test_the_capture_next_to_the_recording_makes_it_xr(tmp_path):
    folder, capture = _xr_recording(tmp_path)
    rec = devices.load(folder)
    assert rec.device == "pupil_neon_xr" and rec.route.startswith("XR: Meta Quest capture (com.oculus.vrshell)")
    assert rec.profile.luminance_source == "display" and rec.lux_values is None
    assert rec.scene_video == capture and rec.separate_video_clock
    assert rec.scene_frame_times[0] == 0 and len(rec.scene_frame_times) == 60
    assert np.diff(rec.scene_frame_times) == pytest.approx(1 / 30, abs=1e-3)
    # time zero is the capture's start as named: the whole second before the Neon's first sample + 0.4 s
    named = quest.capture_start(capture, None)
    assert rec.epoch_start == pytest.approx(named)
    assert rec.time[0] == pytest.approx(START_NS / 1e9 - named, abs=0.01)
    ok = np.isfinite(rec.gaze[:, 0])
    assert ok.any() and np.allclose(rec.gaze[ok], rec.gaze[ok][0])   # a constant gaze stays constant
    assert any("Neon inside a headset" in n for n in rec.notes)


def test_a_headset_frame_without_a_capture_says_so(tmp_path):
    folder, _ = _xr_recording(tmp_path, with_capture=False)
    rec = devices.load(folder)
    assert rec.route.startswith("XR: no Quest capture") and rec.scene_video is None
    assert not rec.separate_video_clock and any("no Quest capture" in n for n in rec.notes)


def test_glasses_route_is_named(tmp_path):
    rec = devices.load(write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES))
    assert rec.device == "pupil_neon" and rec.route == "glasses: Neon scene camera and no lux log"
    assert not rec.separate_video_clock


def test_a_capture_copied_into_a_cloud_export_is_not_its_scene_video(tmp_path):
    folder = write_neon_recording(tmp_path / "neon", GRAYS, FRAME_TIMES)
    (folder / "a1b2c3d4_0-10.mp4").unlink()
    _write_capture(folder / "2026-11-13 at 17.02.25.mp4", [100] * 50)      # 50 frames, the export has 90 timestamps
    rec = devices.load(folder)
    assert rec.scene_video is None


def _video(levels, seconds, rate=50.0, end=None):
    t = np.arange(0, (end or seconds[-1] + 10.0), 1 / rate)
    idx = np.searchsorted(np.asarray(seconds), t, side="right") - 1
    y = np.where(idx >= 0, np.asarray(levels, dtype=float)[np.clip(idx, 0, None)], levels[0])
    lin = np.repeat(y[:, None, None], len(GAMMA_GRID), axis=1).repeat(3, axis=2)
    rgb = np.repeat((y ** (1 / 2.2) * 255)[:, None], 3, axis=1)
    return VideoResult(time=t, fixation_rgb=rgb, background_rgb=rgb, fixation_lin=lin, background_lin=lin, frame_lin=lin)


@pytest.mark.parametrize("offset", [-0.9, 0.0, 0.6, 1.4])
def test_the_capture_clock_is_found_from_the_pupils_response(tmp_path, offset):
    """A capture whose clock is ``offset`` s from the pupil's (video time = pupil clock + offset): the pupil constricts
    PUPIL_LATENCY s after each bright step, on its own clock."""
    rng = np.random.default_rng(1)
    seconds = list(np.cumsum(rng.uniform(6, 12, 30)))
    levels = [0.02 if k % 2 == 0 else rng.uniform(0.3, 0.9) for k in range(30)]
    video = _video(levels, seconds)
    t = np.arange(0, seconds[-1] + 10, 1 / 200)
    seen = np.interp(t + offset - alignment.PUPIL_LATENCY, video.time, np.log10(video.frame_lin[:, 0, 0]))
    a = np.exp(-(1 / 200) / 0.3)
    smooth = np.empty_like(seen)
    acc = seen[0]
    for i, v in enumerate(seen):
        acc = a * acc + (1 - a) * v
        smooth[i] = acc
    pupil = 5.0 - 1.5 * (smooth - smooth.min()) + rng.normal(0, 0.03, len(t))
    from cwtool.devices import neon
    from cwtool.recording import DeviceProfile, Recording
    rec = Recording(name="x", profile=DeviceProfile(name=neon.XR_NAME, pupil_unit="mm", pupil_scale=1.0,
                                                    luminance_source="display", field_of_view=quest.CAPTURE_FOV),
                    folder=tmp_path, time=t, epoch_start=1_700_000_000.0, pupil_left=pupil, pupil_right=pupil,
                    gaze=np.full((len(t), 2), 0.5), separate_video_clock=True)
    found, message = alignment.find(rec, video)
    assert found is not None, message
    assert found.moves == "pupil" and found.source == alignment.PUPIL_SOURCE
    assert found.offset == pytest.approx(offset, abs=0.1)
    moved = alignment.align(rec, found)
    assert moved.time[0] == pytest.approx(rec.time[0] + found.offset)      # the pupil moves onto the capture's clock
    assert moved.epoch_start == pytest.approx(rec.epoch_start - found.offset)
    assert "capture aligned to the pupil" in found.summary()


def test_a_steady_picture_does_not_place_the_capture(tmp_path):
    from cwtool.devices import neon
    from cwtool.recording import DeviceProfile, Recording
    video = _video([0.3], [0.0], end=120)
    t = np.arange(0, 120, 1 / 200)
    rec = Recording(name="x", profile=DeviceProfile(name=neon.XR_NAME, pupil_unit="mm", pupil_scale=1.0,
                                                    luminance_source="display", field_of_view=quest.CAPTURE_FOV),
                    folder=tmp_path, time=t, epoch_start=1_700_000_000.0, pupil_left=np.full(len(t), 4.0),
                    pupil_right=np.full(len(t), 4.0), gaze=np.full((len(t), 2), 0.5), separate_video_clock=True)
    found, message = alignment.find(rec, video)
    assert found is None and "changes too little" in message


def test_the_session_folder_opens_its_one_recording(tmp_path):
    folder, capture = _xr_recording(tmp_path)
    rec = devices.load(folder.parent)               # the folder with the export and the capture
    assert rec.folder == folder and rec.scene_video == capture
    (folder.parent / "other").mkdir()
    write_neon_recording(folder.parent / "other", GRAYS, FRAME_TIMES)
    with pytest.raises(ValueError, match="No supported recording"):
        devices.load(folder.parent)                  # two recordings: the operator has to choose
