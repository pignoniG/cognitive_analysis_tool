"""Project palette, shared by the desktop app, its plots and the exported PDF plot
(the documentation and the calibration presenter use the same colours)."""

GREEN = "#96D35F"
RED = "#E32400"
ORANGE_1 = "#FF7A4E"
ORANGE_2 = "#E6643B"
ORANGE_3 = "#C1441E"
ORANGE_4 = "#9C2101"

# Roles
EXPECTED = GREEN        # expected pupil and its black / white point lines
DELTA_PD = RED          # ΔPD
WARNING = RED           # warning text
CURSOR = ORANGE_4       # current frame bar
EVENT = ORANGE_1        # event shading
EVENT_TEXT = ORANGE_3   # event labels
ACCENT = ORANGE_3       # selection, focus and checked controls in the app


def rgb(colour: str) -> tuple[int, int, int]:
    """(r, g, b) 0-255 of a "#RRGGBB" colour."""
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
