"""The full-field calibration sequence used with the Unity calibration scene."""

from __future__ import annotations

from dataclasses import dataclass

STEP_SECONDS = 6.0


@dataclass(frozen=True)
class Step:
    start: float        # s from sequence start
    rgb: tuple[int, int, int]
    label: str


def _build() -> list[Step]:
    colours = [(f"Gray {v}", (v, v, v)) for v in (0, 36, 73, 109, 146, 182, 219, 255)]
    for name, axis in (("Red", 0), ("Green", 1), ("Blue", 2)):
        for v in (64, 128, 191, 255):
            rgb = [0, 0, 0]
            rgb[axis] = v
            colours.append((f"{name} {v}", tuple(rgb)))
    return [Step(i * STEP_SECONDS, rgb, label) for i, (label, rgb) in enumerate(colours)]


SEQUENCE: list[Step] = _build()
DURATION = len(SEQUENCE) * STEP_SECONDS
