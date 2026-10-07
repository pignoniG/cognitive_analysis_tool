# Development

## Setup

```bash
pip install -e ".[gui,plot,logger,dev]"
pytest
```

The logger's tests (`tests/test_logger.py`) use simulated sensors, a fake lux board and a slow disk, so they need no
hardware and no Bluetooth; the Shimmer and EmotiBit paths were checked by hand on real devices. To run the logger's
window headless, set `QT_QPA_PLATFORM=offscreen`.

The tests build synthetic recordings for every device (`tests/conftest.py`: `write_varjo_recording`,
`write_core_recording`, `write_neon_recording`, `write_tobii_g3_recording`) with known pupil, gaze and scene colours, so they run without real
data. The GUI tests need a display or `QT_QPA_PLATFORM=offscreen`.

## Conventions

- The analysis (`cwtool/`, except `gui/` and `logger/gui.py`) does not import Qt, so it runs headless and in scripts.
- Qt code imports PySide6 before pyqtgraph (`logger/gui.py` also sets `PYQTGRAPH_QT_LIB`): with PyQt6 also installed,
  pyqtgraph would load it and two Qt copies in one process crash.
- Hardware calls that can block (device discovery, connecting) run in a background task, never in the window's
  thread; disk writes of the logger run in their own thread.
- Readers return NaN for invalid samples; the pipeline never sees device-specific validity flags.
- Parameters that do not change the video pass belong in `Parameters`; those that do belong in `VideoSettings` (and
  are part of the cache key).
- Every `Parameters` field needs an editor in `gui/param_panel.py`; a check at start-up enforces it.
- Changing what the video pass stores means bumping `CACHE_FORMAT` in `video.py`.
- Inconsistencies found in the code, the data or the papers go in `docs/OPEN_ISSUES.md`.

## Icons

The windows use Tabler's outline icons (MIT; the licence is in `cwtool/gui/icons/`), stored as SVG files and drawn
by `cwtool.gui.icons.icon(name, size)` in the colours of the current palette, at twice the resolution on high-DPI
screens. To add one, copy its SVG from [tabler.io/icons](https://tabler.io/icons) (outline) into `cwtool/gui/icons/`,
add its name to `NAMES` in `icons.py` and use `icon("name")`; a test checks that every named icon has a clean file
and that no file is left unnamed. The SVGs are included in the installed package (`package-data` in `pyproject.toml`).

## Documentation

This site is built with [MkDocs](https://www.mkdocs.org/) and the Material theme from `docs/` and `mkdocs.yml`.

```bash
pip install -r docs/requirements.txt
mkdocs serve          # live preview at http://127.0.0.1:8000
mkdocs build --strict # what the deployment runs
```

Pushes to `master_v2.0` that touch the docs publish the site to GitHub Pages through `.github/workflows/docs.yml`
(repository **Settings → Pages → Source: GitHub Actions**).
