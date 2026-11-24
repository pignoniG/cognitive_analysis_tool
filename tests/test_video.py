"""Tests of the video analysis: the fixation and background areas, the gamma handling, the cache and the decoding
backends.
"""

import numpy as np
import pytest

from cwtool.params import VideoSettings
from cwtool.video import VideoResult, analyse_frame, analyse_video


def test_two_areas_on_synthetic_frame():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[45:56, 45:56] = [200, 100, 50]  # bright patch at the centre
    s = VideoSettings(circular_mask=True, field_radius=1.0, vertical_fov=100, fixation_radius_deg=2.5,
                      background_excludes_fixation=False)  # 2 px
    fix, bg, *_ = analyse_frame(frame, np.array([[50, 50], [10, 50]]), s)
    assert fix[0] == pytest.approx([200, 100, 50])
    assert fix[1] == pytest.approx([0, 0, 0])
    assert 0 < bg[0][0] < 200 and bg[0] == pytest.approx(bg[1])


def test_background_can_exclude_fixation():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[40:61, 40:61] = 255
    s = VideoSettings(circular_mask=True, field_radius=1.0, vertical_fov=100, fixation_radius_deg=10, background_excludes_fixation=True)
    fix, bg, *_ = analyse_frame(frame, np.array([[50, 50]]), s)
    assert fix[0] == pytest.approx([255] * 3)
    assert bg[0][0] < analyse_frame(frame, np.array([[50, 50]]), VideoSettings(circular_mask=True, field_radius=1.0, vertical_fov=100, fixation_radius_deg=10,
                                                                           background_excludes_fixation=False))[1][0][0]


def test_analyse_video_follows_levels_and_caches(varjo_folder):
    from cwtool import devices
    rec = devices.load(varjo_folder)
    s = VideoSettings().for_recording(rec)
    assert s.circular_mask
    res = analyse_video(rec.scene_video, rec.time, rec.gaze, s)
    assert len(res.time) == len(rec.time)
    level_at = lambda t: res.fixation_rgb[np.argmin(abs(res.time - t)), 0]
    assert level_at(0.5) == pytest.approx(0, abs=3)
    assert level_at(1.5) == pytest.approx(128, abs=3)
    assert level_at(2.5) == pytest.approx(255, abs=3)

    res.save(varjo_folder, s, rec.scene_video)
    cached = VideoResult.load_cached(varjo_folder, s, rec.scene_video)
    assert np.allclose(cached.fixation_rgb, res.fixation_rgb, atol=1e-4)
    assert np.allclose(cached.fixation_lin, res.fixation_lin, rtol=1e-5, atol=1e-9)
    assert VideoResult.load_cached(varjo_folder, VideoSettings(field_radius=0.9), rec.scene_video) is None
    assert VideoResult.load_cached(varjo_folder, VideoSettings(), rec.scene_video) is None  # mask differs


def _circle_scene(h=100, w=100, inside=100):
    """Varjo-style frame: grey scene disc, black corners."""
    import cv2
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(frame, (w // 2, h // 2), h // 2, (inside,) * 3, -1)
    return frame


def test_circular_mask_excludes_black_corners():
    frame = _circle_scene()
    _, bg, *_ = analyse_frame(frame, np.array([[50, 50]]), VideoSettings(circular_mask=True, field_radius=0.9))
    assert bg[0] == pytest.approx([100] * 3)


def test_without_mask_background_is_whole_frame():
    frame = np.zeros((60, 100, 3), dtype=np.uint8)
    frame[:, :50] = 200  # left half bright, including the corners
    _, bg, *_ = analyse_frame(frame, np.array([[50, 30]]), VideoSettings(background_excludes_fixation=False))
    assert bg[0] == pytest.approx([100] * 3)

    corners = np.full((60, 100, 3), 200, dtype=np.uint8)
    corners[10:50, 10:90] = 0
    _, full, *_ = analyse_frame(corners, np.array([[50, 30]]), VideoSettings())
    _, masked, *_ = analyse_frame(corners, np.array([[50, 30]]), VideoSettings(circular_mask=True, field_radius=0.6))
    assert full[0][0] > 50 and masked[0][0] == pytest.approx(0)


def test_textured_area_is_linearised_per_pixel():
    # Fixation area half black, half white: the linear mean is 0.5, whereas decoding
    # the mean code value (127.5) would give about 0.22.
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:, 50:] = 255
    s = VideoSettings(field_radius=1.0, vertical_fov=100, fixation_radius_deg=15)
    fix_rgb, _, fix_lin, _, _ = analyse_frame(frame, np.array([[50, 50]]), s)
    white = fix_rgb[0][0] / 255            # share of white pixels in the disc (about half)
    assert white == pytest.approx(0.5, abs=0.05)
    res = VideoResult(np.zeros(1), fix_rgb, fix_rgb, fix_lin, fix_lin, fix_lin)
    lin, _ = res.linear(2.2)
    assert lin[0] == pytest.approx([white] * 3, abs=1e-3)   # linear mean = share of white
    assert white ** 2.2 < 0.25                               # decoding the mean code value instead


def test_gamma_interpolation_matches_exact_mean():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, (60, 80, 3)).astype(np.uint8)
    s = VideoSettings(field_radius=1.0, vertical_fov=100, fixation_radius_deg=25, background_excludes_fixation=False)
    fix_rgb, bg_rgb, fix_lin, bg_lin, frame_lin = analyse_frame(frame, np.array([[40, 30]]), s)
    res = VideoResult(np.zeros(1), fix_rgb, bg_rgb, fix_lin, bg_lin, frame_lin)
    for gamma in (1.4, 1.95, 2.2, 2.47, 3.0):
        _, bg = res.linear(gamma)
        exact = ((frame.reshape(-1, 3) / 255.0) ** gamma).mean(axis=0)
        assert bg[0] == pytest.approx(exact, abs=1e-3)


def test_old_cache_format_is_ignored(varjo_folder):
    import json
    from cwtool import devices
    from cwtool.video import CACHE_CSV, CACHE_JSON
    rec = devices.load(varjo_folder)
    s = VideoSettings().for_recording(rec)
    (varjo_folder / CACHE_CSV).write_text("time,fix_r,fix_g,fix_b,bg_r,bg_g,bg_b\n0,1,1,1,1,1,1\n")
    (varjo_folder / CACHE_JSON).write_text(json.dumps({"settings": __import__("dataclasses").asdict(s),
                                                       "video": rec.scene_video.name}))
    assert VideoResult.load_cached(varjo_folder, s, rec.scene_video) is None


def test_fixation_radius_in_degrees_follows_device_fov():
    from cwtool.video import radii
    varjo_like = VideoSettings(vertical_fov=105.0, fixation_radius_deg=5.25)
    assert radii(1000, varjo_like)[1] == 50                     # 5 % of the frame height
    narrow = VideoSettings(vertical_fov=52.5, fixation_radius_deg=5.25)
    assert radii(1000, narrow)[1] == 100                        # same angle covers more pixels


def test_background_excludes_gaze_circle_by_default():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[45:56, 45:56] = 255
    s = VideoSettings(vertical_fov=100, fixation_radius_deg=8)
    assert s.background_excludes_fixation
    fix, bg, *_ = analyse_frame(frame, np.array([[50, 50]]), s)
    assert fix[0][0] > 100 and bg[0][0] == pytest.approx(0, abs=1)  # the whole patch is inside the disc


@pytest.mark.parametrize("backend", ["pyav", "opencv"])
def test_backends_agree(varjo_folder, backend):
    if backend == "pyav":
        pytest.importorskip("av")
    from cwtool import devices
    rec = devices.load(varjo_folder)
    s = VideoSettings().for_recording(rec)
    ref = analyse_video(rec.scene_video, rec.time, rec.gaze, s, backend="opencv")
    res = analyse_video(rec.scene_video, rec.time, rec.gaze, s, backend=backend)
    assert np.array_equal(res.time, ref.time)
    assert np.allclose(res.fixation_rgb, ref.fixation_rgb, atol=3)   # colour conversion may differ by a code
    assert np.allclose(res.background_lin, ref.background_lin, atol=0.02)



@pytest.mark.parametrize("backend", ["pyav", "opencv"])
def test_parallel_chunks_give_identical_results(tmp_path, monkeypatch, backend):
    if backend == "pyav":
        pytest.importorskip("av")
    import cwtool.video as V
    from cwtool import devices
    from conftest import write_varjo_recording
    folder = write_varjo_recording(tmp_path / "rec", [0, 60, 120, 180, 240, 30, 90, 150], fps=10)
    rec = devices.load(folder)
    s = VideoSettings().for_recording(rec)
    one = V.analyse_video(rec.scene_video, rec.time, rec.gaze, s, backend=backend, workers=1)
    monkeypatch.setattr(V, "MIN_CHUNK_FRAMES", 5)       # force several chunks on a short video
    seen = []
    three = V.analyse_video(rec.scene_video, rec.time, rec.gaze, s, backend=backend, workers=3,
                            progress=seen.append)
    assert np.array_equal(one.time, three.time)
    assert np.array_equal(one.fixation_lin, three.fixation_lin)
    assert np.array_equal(one.background_rgb, three.background_rgb)
    assert seen[-1] == 1.0 and all(0 <= p <= 1 for p in seen)


@pytest.mark.parametrize("backend", ["pyav", "opencv"])
def test_channels_are_in_rgb_order(tmp_path, backend):
    """Pure red, green and blue H.264 frames (the Varjo capture's codec) come out as R, G, B."""
    av = pytest.importorskip("av")
    path = tmp_path / "rgb.mp4"
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 128, 0)]
    with av.open(str(path), "w") as c:
        s = c.add_stream("libx264", rate=10)
        s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        for rgb in colours:
            for _ in range(10):
                frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), rgb, np.uint8), format="rgb24")
                for packet in s.encode(frame):
                    c.mux(packet)
        for packet in s.encode():
            c.mux(packet)
    t = np.arange(0, len(colours), 0.1) + 0.05
    res = analyse_video(path, t, np.full((len(t), 2), 0.5), VideoSettings(), backend=backend, workers=1)
    for i, rgb in enumerate(colours):
        got = res.fixation_rgb[np.argmin(np.abs(res.time - (i + 0.5)))]
        assert got == pytest.approx(rgb, abs=6)


def test_gaze_circle_is_limited_to_the_visible_scene():
    """Near the edge of a circular scene the gaze circle does not average in the black corners."""
    from cwtool.video import field_mask
    s = VideoSettings(circular_mask=True, field_radius=0.9, vertical_fov=100, fixation_radius_deg=10)
    mask = field_mask((100, 100), s)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[mask > 0] = 180                                   # the scene circle; black corners outside
    fix, _, fix_lin, _, _ = analyse_frame(frame, np.array([[50, 50], [85, 85]]), s)
    assert fix[0] == pytest.approx([180] * 3)
    assert fix[1] == pytest.approx([180] * 3)               # at the edge: only the visible part
    # Without a circular scene the whole circle counts, as before.
    fix, *_ = analyse_frame(frame, np.array([[85, 85]]), VideoSettings(vertical_fov=100, fixation_radius_deg=10))
    assert fix[0][0] < 180


def test_the_quick_pass_gives_each_frames_colour_on_the_recordings_clock(tmp_path):
    from conftest import write_varjo_recording
    from cwtool import devices
    from cwtool.video import quick_colours
    rec = devices.load(write_varjo_recording(tmp_path / "rec", [40, 200, 120], seconds_per_level=1.0, fps=10))
    quick = quick_colours(rec.scene_video, rec.scene_frame_times)
    assert len(quick.time) == 30 and np.all(np.diff(quick.time) > 0)
    grey = quick.background_rgb.mean(axis=1)
    for level, second in ((40, 0.5), (200, 1.5), (120, 2.5)):
        assert grey[np.argmin(np.abs(quick.time - second))] == pytest.approx(level, abs=6)
    assert quick.frame_lin.shape == (30, len(__import__("cwtool.video", fromlist=["GAMMA_GRID"]).GAMMA_GRID), 3)


def test_a_saved_analysis_at_other_sample_times_is_not_reused(tmp_path):
    """A video on its own clock is analysed with the pupil aligned to it: an analysis made at the unaligned times paired
    its frames with other gaze, and is done again."""
    from conftest import write_varjo_recording
    from cwtool import devices
    rec = devices.load(write_varjo_recording(tmp_path / "rec", [40, 200], seconds_per_level=1.0, fps=10))
    settings = VideoSettings().for_recording(rec)
    video = analyse_video(rec.scene_video, rec.time, rec.gaze, settings)
    video.save(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze)
    load = lambda time: VideoResult.load_cached(rec.folder, settings, rec.scene_video, rec.scene_frame_times, rec.gaze, time)
    assert load(rec.time) is not None and load(None) is not None
    assert load(rec.time + 6.45) is None


def test_only_a_video_on_its_own_clock_is_aligned_before_the_analysis(tmp_path):
    from conftest import write_varjo_recording
    from cwtool import alignment, devices
    rec = devices.load(write_varjo_recording(tmp_path / "rec", [40, 200], seconds_per_level=1.0, fps=10))
    assert alignment.for_analysis(rec) == (rec, None, "")


def _analyse_frame_by_pixels(frame_rgb, gaze_px, settings):
    """The per-frame measurement written plainly: a histogram of each circle's pixels, one sample at a time."""
    from cwtool.video import GAMMA_GRID, _means, field_mask, radii

    def hist(pixels):
        return np.stack([np.bincount(pixels[:, c], minlength=256) for c in range(3)]).astype(float)

    h, w = frame_rgb.shape[:2]
    fix_r = radii(h, settings)[1]
    mask = field_mask((h, w), settings)
    field_hist = hist(frame_rgb[mask > 0])
    m = len(gaze_px)
    fix_rgb, bg_rgb = np.empty((m, 3)), np.empty((m, 3))
    fix_lin, bg_lin = np.empty((m, len(GAMMA_GRID), 3)), np.empty((m, len(GAMMA_GRID), 3))
    yy, xx = np.ogrid[:h, :w]
    for i, (gx, gy) in enumerate(gaze_px):
        gx, gy = int(np.clip(gx, 0, w - 1)), int(np.clip(gy, 0, h - 1))
        x0, x1, y0, y1 = max(gx - fix_r, 0), min(gx + fix_r + 1, w), max(gy - fix_r, 0), min(gy + fix_r + 1, h)
        disc = (xx[:, x0:x1] - gx) ** 2 + (yy[y0:y1, :] - gy) ** 2 <= fix_r ** 2
        crop = frame_rgb[y0:y1, x0:x1]
        overlap = disc & (mask[y0:y1, x0:x1] > 0)
        fix_rgb[i], fix_lin[i] = _means(hist(crop[overlap if overlap.any() else disc]))
        bg_rgb[i], bg_lin[i] = (_means(field_hist - hist(crop[overlap])) if settings.background_excludes_fixation
                                else _means(field_hist))
    return fix_rgb, bg_rgb, fix_lin, bg_lin


@pytest.mark.parametrize("circular", [False, True])
@pytest.mark.parametrize("excludes", [False, True])
def test_frame_measurement_equals_the_plain_per_pixel_one(circular, excludes):
    """The fast measurement (OpenCV histograms, the circle's histogram reused for the background, samples on the same
    pixel measured once) gives exactly what histograms of each circle's pixels give: at the centre, at the edges,
    outside a circular scene, and for several samples on one pixel."""
    rng = np.random.default_rng(3)
    frame = rng.integers(0, 256, (90, 160, 3), dtype=np.uint8)
    s = VideoSettings(circular_mask=circular, field_radius=0.8, vertical_fov=90, fixation_radius_deg=12,
                      background_excludes_fixation=excludes)
    gaze = np.array([[80, 45], [80.4, 45.2], [80, 45], [0, 0], [159, 89], [-20, 50], [3, 3], [120, 30], [120, 30]])
    fast = analyse_frame(frame, gaze, s)
    plain = _analyse_frame_by_pixels(frame, gaze, s)
    for a, b in zip(fast[:4], plain):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-12)


def test_a_saved_analysis_of_a_long_recording_is_reused(tmp_path):
    """Sample times past 100 s that are not on whole milliseconds (a capture aligned by a fraction of a ms) are saved
    precisely enough to be found again among the recording's: with 6 significant digits they were 0.5 ms off and the
    analysis was redone at every opening."""
    from cwtool.video import GAMMA_GRID
    time = np.arange(0, 480, 0.005) - 5.35949524
    n, g = len(time), len(GAMMA_GRID)
    res = VideoResult(time, np.full((n, 3), 100.0), np.full((n, 3), 90.0), np.full((n, g, 3), 0.2), np.full((n, g, 3), 0.1),
                      np.full((n, g, 3), 0.1))
    video = tmp_path / "capture.mp4"
    res.save(tmp_path, VideoSettings(), video)
    cached = VideoResult.load_cached(tmp_path, VideoSettings(), video, time=time)
    assert cached is not None and len(cached.time) == n
