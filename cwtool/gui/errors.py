"""Plain-language advice for the errors the window reports, and the list of gestures and shortcuts of the Help menu.

No Qt here: the window shows what these functions return, and the tests check them."""

from __future__ import annotations

import re

DOCS_URL = "https://pignonig.github.io/cognitive_analysis_tool/"

# (pattern in the error text, what it usually means and what to do), the first match is used
_ADVICE = (
    (r"No module named '?([\w.]+)'?|ImportError",
     "A package this step needs is not installed. Install it in the environment that runs cwtool, for example "
     "pip install \"cwtool[hrv]\" for the heart rate variability."),
    (r"No space left on device",
     "The disk is full. Free some space or choose another folder."),
    (r"Permission denied|PermissionError|Operation not permitted",
     "The app is not allowed to read or write there. Choose another folder, or check its permissions."),
    (r"No such file or directory|FileNotFoundError|does not exist|not found",
     "A file or folder that is needed is missing. Check that the recording folder is complete and was not moved or "
     "renamed while the app was open."),
    (r"codec|VideoCapture|could not open video|cannot open video|Invalid data found|moov atom",
     "The scene video could not be read. Check that it plays in another player; if it does not, copy it again from the "
     "device or convert it to H.264."),
    (r"MemoryError|Unable to allocate|out of memory",
     "There is not enough memory. Close other programs, or analyse a shorter recording."),
    (r"JSON|Expecting value|Unterminated string|KeyError|invalid literal",
     "The file is not in the format the app expects (a damaged or hand-edited file, or one from another tool). Open it "
     "in a text editor, or save it again from the app."),
)
FALLBACK = ("Something unexpected went wrong. The details show where; if it happens again with the same recording, "
            "report it with them.")


def advice(message: str) -> str:
    """What to try, for the text of an error (its first line and its traceback)."""
    for pattern, text in _ADVICE:
        if re.search(pattern, message, re.IGNORECASE):
            return text
    return FALLBACK


def split_message(message: str) -> tuple[str, str]:
    """The headline of an error (its first paragraph) and its details (the traceback, if there is one)."""
    head, _, details = message.partition("\n\n")
    return head.strip(), details.strip()


GESTURES = (
    ("Pan the time axis", "drag with the left button (the middle button also works), or swipe sideways"),
    ("Zoom to a rectangle", "press the Zoom button, then drag on a plot: zooms in time and in value"),
    ("Zoom around the pointer", "mouse wheel (zooms in time)"),
    ("Zoom out", "right-click on a plot (also fits the value axis to the data again)"),
    ("Show everything", "the Reset view button, double-click on a plot, or Ctrl+0"),
    ("Move the video cursor", "click on a plot, or drag the red bar"),
    ("Move the calibration start or the export range", "drag its line or band on the plots"),
)
SHORTCUTS = (
    ("Ctrl+O", "Open a recording"),
    ("Ctrl+S / Ctrl+Shift+S", "Save the parameters / save them as…"),
    ("Ctrl+E", "Export results"),
    ("Ctrl+H", "Compute heart rate variability (when the sensor data has an ECG)"),
    ("Z", "Switch the zoom mode of the plots"),
    ("Ctrl+0", "Reset the view of the plots"),
    ("Ctrl+1 … Ctrl+4", "Data, Params, Calibrate and Export tabs"),
    ("P", "Show or hide the video preview"),
    ("Ctrl+Q", "Quit"),
)


def gestures_html() -> str:
    """The gestures and shortcuts as the HTML of the Help dialog."""
    def table(title, rows):
        body = "".join(f"<tr><td style='padding-right:18px'><b>{a}</b></td><td>{b}</td></tr>" for a, b in rows)
        return f"<h3>{title}</h3><table>{body}</table>"
    return table("Plots", GESTURES) + table("Keyboard", SHORTCUTS)
