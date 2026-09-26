import numpy as np
import pytest

from cwtool.params import VideoSettings
from cwtool.video import VideoResult, analyse_frame, analyse_video


def test_two_areas_on_synthetic_frame():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[45:56, 45:56] = [200, 100, 50]  # bright patch at the centre
    s = VideoSettings(circular_mask=True, field_radius=1.0, fixation_ratio=0.05)  # fixation radius 2 px
    fix, bg, *_ = analyse_frame(frame, np.array([[50, 50], [10, 50]]), s)
    assert fix[0] == pytest.approx([200, 100, 50])
    assert fix[1] == pytest.approx([0, 0, 0])
    assert 0 < bg[0][0] < 200 and bg[0] == pytest.approx(bg[1])


def test_background_can_exclude_fixation():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[40:61, 40:61] = 255
    s = VideoSettings(circular_mask=True, field_radius=1.0, fixation_ratio=0.2, background_excludes_fixation=True)
    fix, bg, *_ = analyse_frame(frame, np.array([[50, 50]]), s)
    assert fix[0] == pytest.approx([255] * 3)
    assert bg[0][0] < analyse_frame(frame, np.array([[50, 50]]), VideoSettings(circular_mask=True, field_radius=1.0, fixation_ratio=0.2))[1][0][0]


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
    _, bg, *_ = analyse_frame(frame, np.array([[50, 30]]), VideoSettings())
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
    s = VideoSettings(field_radius=1.0, fixation_ratio=0.3)
    fix_rgb, _, fix_lin, _ = analyse_frame(frame, np.array([[50, 50]]), s)
    white = fix_rgb[0][0] / 255            # share of white pixels in the disc (about half)
    assert white == pytest.approx(0.5, abs=0.05)
    res = VideoResult(np.zeros(1), fix_rgb, fix_rgb, fix_lin, fix_lin)
    lin, _ = res.linear(2.2)
    assert lin[0] == pytest.approx([white] * 3, abs=1e-3)   # linear mean = share of white
    assert white ** 2.2 < 0.25                               # decoding the mean code value instead


def test_gamma_interpolation_matches_exact_mean():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, (60, 80, 3)).astype(np.uint8)
    s = VideoSettings(field_radius=1.0, fixation_ratio=0.5)
    fix_rgb, bg_rgb, fix_lin, bg_lin = analyse_frame(frame, np.array([[40, 30]]), s)
    res = VideoResult(np.zeros(1), fix_rgb, bg_rgb, fix_lin, bg_lin)
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
