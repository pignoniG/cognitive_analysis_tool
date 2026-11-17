"""Device readers.

Each reader module exposes ``NAME``, ``detect(folder) -> bool`` and
``load(folder, **options) -> Recording``. Add a device by writing a module
with that interface and listing it in ``READERS``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from cwtool.devices import neon, pupil_core, tobii_g3, varjo
from cwtool.recording import Recording

READERS = {varjo.NAME: varjo, pupil_core.NAME: pupil_core, neon.NAME: neon, tobii_g3.NAME: tobii_g3}


def detect(folder: str | Path) -> str | None:
    """Name of the first reader that recognises ``folder``, or None."""
    folder = Path(folder)
    for name, reader in READERS.items():
        if reader.detect(folder):
            return name
    return None


def resolve(folder: str | Path) -> Path:
    """``folder``, or the one recording inside it when ``folder`` is not one itself: a session folder that holds a Neon's
    Cloud export next to a Meta Quest capture is opened as that export. Unchanged when no subfolder, or several, are
    recognised."""
    folder = Path(folder)
    if detect(folder) is not None or not folder.is_dir():
        return folder
    found = [sub for sub in sorted(folder.iterdir())
             if sub.is_dir() and not sub.name.startswith(".") and detect(sub) is not None]
    return found[0] if len(found) == 1 else folder


def load(folder: str | Path, device: str | None = None, **options) -> Recording:
    """Read ``folder`` with the reader for ``device`` (default: detected); a folder holding a single recording is read as
    that recording (:func:`resolve`). Only the ``options`` the reader's ``load`` accepts, and that are not None, are passed
    on (e.g. ``lux_folder``). The session's gaze offset saved with the recording is applied, or ``gaze_offset`` (deg;
    right, down) instead when given ((0, 0): none)."""
    folder = resolve(folder) if device is None else Path(folder)
    device = device or detect(folder)
    if device is None:
        raise ValueError(f"No supported recording found in {folder}")
    if device not in READERS:
        raise ValueError(f"Unknown device {device!r}; supported: {', '.join(READERS)}")
    reader = READERS[device]
    gaze_offset = options.pop("gaze_offset", None)       # (right, down) deg; None: the one saved with the recording
    accepted = inspect.signature(reader.load).parameters
    rec = reader.load(folder, **{k: v for k, v in options.items() if k in accepted and v is not None})
    from cwtool import gazecheck            # the session's gaze offset, saved with the recording
    return gazecheck.apply_offset(rec, gaze_offset)
