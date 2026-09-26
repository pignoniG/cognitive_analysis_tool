import numpy as np
import pytest

from cwtool.params import VideoSettings
from cwtool.video import VideoResult, analyse_frame, analyse_video


def test_two_areas_on_synthetic_frame():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[45:56, 45:56] = [200, 100, 50]  # bright patch at the centre
    s = VideoSettings(circular_mask=True, field_radius=1.0, fixation_ratio=0.05)  # fixation radius 2 px
    fix, bg = analyse_frame(frame, np.array([[50, 50], [10, 50]]), s)
    assert fix[0] == pytest.approx([200, 100, 50])
    assert fix[1] == pytest.approx([0, 0, 0])
    assert 0 < bg[0][0] < 200 and bg[0] == pytest.approx(bg[1])


def test_background_can_exclude_fixation():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[40:61, 40:61] = 255
    s = VideoSettings(circular_mask=True, field_radius=1.0, fixation_ratio=0.2, background_excludes_fixation=True)
    fix, bg = analyse_frame(frame, np.array([[50, 50]]), s)
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
    assert np.allclose(cached.fixation_rgb, res.fixation_rgb, atol=1e-5)
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
    _, bg = analyse_frame(frame, np.array([[50, 50]]), VideoSettings(circular_mask=True, field_radius=0.9))
    assert bg[0] == pytest.approx([100] * 3)


def test_without_mask_background_is_whole_frame():
    frame = np.zeros((60, 100, 3), dtype=np.uint8)
    frame[:, :50] = 200  # left half bright, including the corners
    _, bg = analyse_frame(frame, np.array([[50, 30]]), VideoSettings())
    assert bg[0] == pytest.approx([100] * 3)

    corners = np.full((60, 100, 3), 200, dtype=np.uint8)
    corners[10:50, 10:90] = 0
    _, full = analyse_frame(corners, np.array([[50, 30]]), VideoSettings())
    _, masked = analyse_frame(corners, np.array([[50, 30]]), VideoSettings(circular_mask=True, field_radius=0.6))
    assert full[0][0] > 50 and masked[0][0] == pytest.approx(0)
