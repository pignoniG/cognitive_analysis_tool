"""Device readers.

Each reader module exposes ``NAME``, ``detect(folder) -> bool`` and
``load(folder, **options) -> Recording``. Add a device by writing a module
with that interface and listing it in ``READERS``.
"""

from __future__ import annotations

from pathlib import Path

from cwtool.recording import Recording
from cwtool.devices import varjo

READERS = {varjo.NAME: varjo}


def detect(folder: str | Path) -> str | None:
    folder = Path(folder)
    for name, reader in READERS.items():
        if reader.detect(folder):
            return name
    return None


def load(folder: str | Path, device: str | None = None, **options) -> Recording:
    folder = Path(folder)
    device = device or detect(folder)
    if device is None:
        raise ValueError(f"No supported recording found in {folder}")
    if device not in READERS:
        raise ValueError(f"Unknown device {device!r}; supported: {', '.join(READERS)}")
    return READERS[device].load(folder, **options)
