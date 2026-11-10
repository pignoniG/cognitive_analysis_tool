"""Tests of the alignment of the presenter's log to the scene video: a known offset between the two clocks is recovered from
the changes of the picture, and moving the log's clock puts events, sensors and Unix times where the video is."""

import numpy as np
import pytest

from cwtool import alignment, devices
from cwtool.devices import varjo
from cwtool.recording import Event, Recording
from cwtool.video import GAMMA_GRID, VideoResult
from conftest import write_varjo_recording

EPOCH = 1_700_000_000.0
FPS = 30.0


def _video(levels, seconds, fps=FPS, rate=200.0, jitter=0.0):
    """A video analysed at ``rate`` Hz whose background shows ``levels[i]`` (a gray code) from ``seconds[i]`` on, in frames."""
    t = np.arange(0, seconds[-1] + 10.0, 1 / rate)
    frame_time = np.floor(t * fps) / fps                                  # the picture changes only at frame instants
    idx = np.searchsorted(np.asarray(seconds), frame_time, side="right") - 1
    y = np.where(idx >= 0, np.asarray(levels, dtype=float)[np.clip(idx, 0, None)], levels[0])
    rgb = np.repeat(y[:, None], 3, axis=1) + np.random.default_rng(0).normal(0, jitter, (len(t), 3))
    z = np.zeros((len(t), len(GAMMA_GRID), 3))
    return VideoResult(time=t, fixation_rgb=rgb, background_rgb=rgb, fixation_lin=z, background_lin=z, frame_lin=z)


def _steps(n=24, length=8.0, start=20.0):
    levels = [0, 200, 60, 255, 20, 120, 255, 0, 90, 180, 30, 220] * (n // 12 + 1)
    return levels[:n], [start + i * length for i in range(n)]


def _recording(video, events=(), lux=None, name="varjo"):
    profile = varjo.PROFILE if name == "varjo" else varjo.PROFILE.__class__(**{**varjo.PROFILE.__dict__, "name": name})
    return Recording(name="synthetic", profile=profile, folder=None, time=np.asarray(video.time), epoch_start=EPOCH,
                     pupil_left=np.full(len(video.time), 3.0), pupil_right=np.full(len(video.time), 3.0),
                     gaze=np.full((len(video.time), 2), 0.5), events=list(events), lux_time=lux)


def _logged(seconds, offset):
    """Unix times at which a presenter whose clock is `offset` s behind the video's logs the changes (video = log + offset)."""
    return EPOCH + np.asarray(seconds) - offset


@pytest.mark.parametrize("offset", [-0.34, 0.0, 0.21, -2.6, 3.9])
def test_the_offset_between_the_clocks_is_recovered(offset):
    levels, seconds = _steps()
    video = _video(levels, seconds, jitter=0.5)
    al, message = alignment.estimate(_recording(video), video, _logged(seconds, offset), "test.csv")
    assert al is not None, message
    assert al.offset == pytest.approx(offset, abs=0.02)                    # within a frame of the video
    assert al.n == len(seconds) - 1 and al.candidates == len(seconds) and al.source == "test.csv"   # the first step changes nothing
    assert al.uncertainty >= alignment.MIN_UNCERTAINTY and al.sd < 0.02
    assert abs(al.drift) < 0.02


def test_an_offset_beyond_the_search_is_not_guessed():
    levels, seconds = _steps()
    video = _video(levels, seconds)
    al, message = alignment.estimate(_recording(video), video, _logged(seconds, 6.5))
    assert al is None or abs(al.offset) <= alignment.COARSE_RANGE            # never a made-up value outside the search


def test_logged_changes_that_did_not_happen_and_missing_ones_do_not_matter():
    levels, seconds = _steps()
    video = _video(levels, seconds)
    logged = _logged(seconds, -0.34)
    logged = np.concatenate([np.delete(logged, [3, 4]), EPOCH + np.array([33.3, 90.1, 150.7])])   # two lost, three invented
    al, message = alignment.estimate(_recording(video), video, logged)
    assert al is not None, message
    assert al.offset == pytest.approx(-0.34, abs=0.02)
    assert al.n <= al.candidates - 3                                       # the invented ones show no change in the video


def test_it_declines_when_the_log_is_not_in_the_video():
    levels, seconds = _steps()
    video = _video(levels, seconds)
    rec = _recording(video)
    al, message = alignment.estimate(rec, video, EPOCH + np.arange(0.37, 150, 7.31))      # a log of another recording
    assert al is None and "not found" in message
    al, message = alignment.estimate(rec, video, EPOCH + np.array([20.0, 28.0, 36.0]))
    assert al is None and "found" in message                                              # three changes are too few
    al, message = alignment.estimate(rec, video, np.zeros(0))
    assert al is None and "no presenter log" in message


def test_a_drift_is_reported_and_the_constant_median_is_used():
    levels, seconds = _steps(n=40, length=10.0)
    video = _video(levels, seconds)
    # the log's clock runs 0.2 s fast over the 400 s: the offset goes from -0.3 to -0.1
    offsets = -0.3 + 0.2 * (np.asarray(seconds) - seconds[0]) / (seconds[-1] - seconds[0])
    al, message = alignment.estimate(_recording(video), video, EPOCH + np.asarray(seconds) - offsets)
    assert al is not None, message
    assert al.drift == pytest.approx(0.2, abs=0.04) and al.offset == pytest.approx(-0.2, abs=0.04)
    assert any("drifts" in n for n in al.notes())


def test_aligning_moves_the_log_clock_onto_the_video():
    levels, seconds = _steps()
    video = _video(levels, seconds)
    events = [Event("Rest", 20.0, 36.0), Event("Task", 36.0, 52.0)]
    lux = np.array([1.0, 2.0, 3.0])
    rec = _recording(video, events, lux)
    al, _ = alignment.estimate(rec, video, _logged(seconds, -0.34))
    out = alignment.align(rec, al)
    assert out.epoch_start == pytest.approx(EPOCH + 0.34, abs=0.02)
    assert [(e.label, e.start) for e in out.events] == [("Rest", pytest.approx(20.0 - 0.34, abs=0.02)),
                                                        ("Task", pytest.approx(36.0 - 0.34, abs=0.02))]
    assert out.lux_time == pytest.approx(lux - 0.34, abs=0.02)
    # a logged Unix time lands on the video's clock: the change logged at `u` is seen at `u - epoch - 0.34 + ...`
    u = _logged(seconds, -0.34)[5]
    assert u - out.epoch_start == pytest.approx(seconds[5], abs=0.02)
    assert out.log_alignment["n"] == al.n and any("log aligned to the video" in n for n in out.notes)
    assert rec.epoch_start == EPOCH and rec.events[0].start == 20.0         # the original is untouched


def test_the_logs_of_a_recordings_folder_give_the_changes(tmp_path):
    (tmp_path / "s__visual_log.csv").write_text(
        "Event,Start Time,End Time,Duration (s),Start (unix s),End (unix s)\n"
        "calibration,a,b,5,1700000010.000,1700000015.000\nscenes,a,b,7.5,1700000020.500,1700000028.000\n")
    (tmp_path / "s__calibration_run_x.csv").write_text(
        "# tool: t\ntime,duration,r,g,b,label,onset_unix_ms\n0,5,0,0,0,Black,1700000010000\n5,5,9,9,9,Gray,1700000015000\n")
    (tmp_path / "s__nback_log.csv").write_text("block,n,item,digit,onset_unix_ms\n1,2,1,5,1700000099000\n")
    (tmp_path / "._s__visual_log.csv").write_bytes(b"\xb0\x00")
    on, source = alignment.log_onsets(tmp_path)
    assert on == pytest.approx([1700000010.0, 1700000015.0, 1700000020.5])      # the same change in two logs counts once
    assert "visual_log" in source and "calibration_run" in source and "nback" not in source
    assert alignment.log_onsets(tmp_path / "missing")[0].size == 0


def test_only_devices_with_the_presenters_clock_are_aligned():
    levels, seconds = _steps()
    video = _video(levels, seconds)
    assert alignment.applicable(_recording(video))
    other = _recording(video, name="neon")
    assert not alignment.applicable(other)
    assert alignment.find(other, video)[0] is None
    assert "not offered" in alignment.find(other, video)[1]


def test_a_real_recording_folder_with_its_logs(tmp_path):
    """The whole path on a synthetic Varjo recording: its video shows the colours, its folder holds a visual log written
    0.3 s late, and the alignment finds that."""
    colours = [0, 255, 0, 200, 0, 120, 255, 0, 90, 180, 0, 255]
    folder = write_varjo_recording(tmp_path / "rec", colours, seconds_per_level=5.0, fps=30, pupil_mm=3.0)
    rec = devices.load(folder)
    rows = ["Event,Start Time,End Time,Duration (s),Start (unix s),End (unix s)"]
    for i in range(len(colours)):
        rows.append(f"step,a,b,5,{rec.epoch_start + 5.0 * i + 0.3:.3f},0")               # logged 0.3 s after the video changed
    (folder / "x__visual_log.csv").write_text("\n".join(rows) + "\n")
    from cwtool.params import VideoSettings
    from cwtool.video import analyse_video
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, VideoSettings().for_recording(rec))
    al, message = alignment.find(rec, video)
    assert al is not None, message
    assert al.offset == pytest.approx(-0.3, abs=0.04) and al.n >= 8
