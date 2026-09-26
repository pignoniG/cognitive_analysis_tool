"""Scene video frame at the cursor time, with the analysis areas drawn on it."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from cwtool.params import VideoSettings
from cwtool.pipeline import Result
from cwtool.recording import Recording
from cwtool.video import VideoResult, frame_index, prepare_frame, radii

DISPLAY_WIDTH = 900
SCENE_COLOUR = (255, 200, 0)    # RGB
FIXATION_COLOUR = (255, 60, 60)


class VideoPreview(QWidget):
    """Shows the frame analysed at a given time, the scene circle (circular
    videos), the fixation circle at the gaze and the values measured there.
    Circles use the current video settings, so they can be checked before
    re-running the analysis."""

    time_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rec: Optional[Recording] = None
        self._settings = VideoSettings()
        self._video: Optional[VideoResult] = None
        self._result: Optional[Result] = None
        self._cap = None
        self._fps = 0.0
        self._n_frames = 0
        self._time = 0.0
        self._frame_cache: tuple[int, np.ndarray] | None = None

        self.image = QLabel("Open a recording and click on the plot to preview the video.")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(240, 240)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.info = QLabel()
        self.info.setTextFormat(Qt.RichText)
        self.info.setWordWrap(True)
        self.prev_button = QPushButton("◀ Frame")
        self.next_button = QPushButton("Frame ▶")
        self.prev_button.clicked.connect(lambda: self._step(-1))
        self.next_button.clicked.connect(lambda: self._step(1))
        self.time_label = QLabel()

        nav = QHBoxLayout()
        nav.addWidget(self.prev_button)
        nav.addWidget(self.time_label, 1, Qt.AlignCenter)
        nav.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.image, 1)
        layout.addLayout(nav)
        layout.addWidget(self.info)
        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        self.prev_button.setEnabled(on)
        self.next_button.setEnabled(on)

    def set_recording(self, rec: Optional[Recording], settings: VideoSettings) -> None:
        if self._cap is not None:
            self._cap.release()
        self._rec, self._settings, self._video, self._result = rec, settings, None, None
        self._cap, self._frame_cache = None, None
        if rec is not None and rec.scene_video is not None:
            cap = cv2.VideoCapture(str(rec.scene_video))
            if cap.isOpened() and cap.get(cv2.CAP_PROP_FPS) > 0:
                self._cap = cap
                self._fps = cap.get(cv2.CAP_PROP_FPS)
                self._n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._set_enabled(self._cap is not None)
        if self._cap is None:
            self.image.setText("No scene video." if rec is not None else "")
            self.info.clear()
            self.time_label.clear()
            return
        self.show_time(float(rec.time[0]) if len(rec.time) else 0.0)

    def set_settings(self, settings: VideoSettings) -> None:
        self._settings = settings
        self.refresh()

    def set_analysis(self, video: Optional[VideoResult], result: Optional[Result]) -> None:
        self._video, self._result = video, result
        self.refresh()

    def refresh(self) -> None:
        if self._cap is not None:
            self.show_time(self._time)

    def _step(self, frames: int) -> None:
        if self._fps:
            # Middle of the neighbouring frame, so rounding cannot land on the same one.
            idx = int(frame_index(self._time, self._fps)) + frames
            idx = int(np.clip(idx, 0, max(self._n_frames - 1, 0)))
            self.show_time((idx + 0.5) / self._fps)
            self.time_changed.emit(self._time)

    def _read(self, idx: int) -> Optional[np.ndarray]:
        if self._frame_cache is not None and self._frame_cache[0] == idx:
            return self._frame_cache[1]
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self._cap.read()
        if not ok:
            return None
        self._frame_cache = (idx, frame)
        return frame

    def show_time(self, t: float) -> None:
        self._time = t
        if self._cap is None or self._rec is None:
            return
        idx = int(np.clip(frame_index(t, self._fps), 0, max(self._n_frames - 1, 0)))
        self.time_label.setText(f"{t:.2f} s  ·  frame {idx}")
        frame = self._read(idx)
        if frame is None:
            self.image.setText(f"Cannot read frame {idx}")
            return
        self._draw(frame, t)

    def _nearest_sample(self, t: float) -> Optional[int]:
        rec = self._rec
        valid = np.flatnonzero(np.isfinite(rec.gaze).all(axis=1))
        if not len(valid):
            return None
        # Only samples that fall on the displayed frame were analysed on it.
        same = valid[frame_index(rec.time[valid], self._fps) == frame_index(t, self._fps)]
        pool = same if len(same) else valid
        return int(pool[np.argmin(np.abs(rec.time[pool] - t))])

    def _draw(self, frame_bgr: np.ndarray, t: float) -> None:
        s = self._settings
        # Radii as computed on the downscaled analysis frame, then scaled to the display.
        analysis_h = max(int(frame_bgr.shape[0] * s.analysis_width / frame_bgr.shape[1]), 1)
        field_r, fix_r = radii(analysis_h, s)

        disp_w = min(DISPLAY_WIDTH, frame_bgr.shape[1])
        disp = prepare_frame(frame_bgr, replace(s, analysis_width=disp_w), smooth=True)
        h, w = disp.shape[:2]
        k = h / analysis_h
        thick = max(2, w // 300)

        if s.circular_mask:
            outside = np.ones((h, w), bool)
            yy, xx = np.ogrid[:h, :w]
            outside &= (xx - w // 2) ** 2 + (yy - h // 2) ** 2 > (field_r * k) ** 2
            disp[outside] = (disp[outside] * 0.35).astype(np.uint8)
            cv2.circle(disp, (w // 2, h // 2), int(field_r * k), SCENE_COLOUR, thick)

        i = self._nearest_sample(t)
        lines = []
        if i is None:
            lines.append("No valid gaze near this time.")
        else:
            gx, gy = self._rec.gaze[i] * [w, h]
            centre = (int(gx), int(gy))
            cv2.circle(disp, centre, max(int(fix_r * k), 2), FIXATION_COLOUR, thick)
            cv2.drawMarker(disp, centre, FIXATION_COLOUR, cv2.MARKER_CROSS, 4 * thick, thick)
            lines.append(f"gaze sample at {self._rec.time[i]:.3f} s "
                         f"({self._rec.gaze[i][0]:.3f}, {self._rec.gaze[i][1]:.3f})")
        lines += self._values(t)
        self.info.setText("<br>".join(lines))

        img = QImage(disp.data, w, h, disp.strides[0], QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(img)
        self.image.setPixmap(pix.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _values(self, t: float) -> list[str]:
        out = []
        if self._video is not None and len(self._video.time):
            j = int(np.argmin(np.abs(self._video.time - t)))
            f, b = self._video.fixation_rgb[j], self._video.background_rgb[j]
            out.append(f"<span style='color:#d33'>fixation</span> RGB {f[0]:.0f}, {f[1]:.0f}, {f[2]:.0f}"
                       f" &nbsp; <span style='color:#c90'>background</span> RGB {b[0]:.0f}, {b[1]:.0f}, {b[2]:.0f}")
        if self._result is not None and len(self._result.time):
            j = int(np.argmin(np.abs(self._result.time - t)))
            r = self._result
            out.append(f"luminance {r.luminance[j]:.1f} cd/m² &nbsp; measured {r.measured[j]:.2f} mm"
                       f" &nbsp; expected {r.expected[j]:.2f} mm")
        return out

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh()
