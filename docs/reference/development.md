# Development

## Setup

```bash
pip install -e ".[gui,plot,logger,dev]"
pytest
```

The tests build synthetic recordings for every device (`tests/conftest.py`: `write_varjo_recording`,
`write_core_recording`, `write_neon_recording`) with known pupil, gaze and scene colours, so they run without real
data. The GUI tests need a display or `QT_QPA_PLATFORM=offscreen`.

## Conventions

- The analysis (`cwtool/`, except `gui/`) does not import Qt, so it runs headless and in scripts.
- Readers return NaN for invalid samples; the pipeline never sees device-specific validity flags.
- Parameters that do not change the video pass belong in `Parameters`; those that do belong in `VideoSettings` (and
  are part of the cache key).
- Every `Parameters` field needs an editor in `gui/param_panel.py`; a check at start-up enforces it.
- Changing what the video pass stores means bumping `CACHE_FORMAT` in `video.py`.
- Inconsistencies found in the code, the data or the papers go in `docs/OPEN_ISSUES.md`.

## Documentation

This site is built with [MkDocs](https://www.mkdocs.org/) and the Material theme from `docs/` and `mkdocs.yml`.

```bash
pip install -r docs/requirements.txt
mkdocs serve          # live preview at http://127.0.0.1:8000
mkdocs build --strict # what the deployment runs
```

Pushes to `v2.0` that touch the docs publish the site to GitHub Pages through `.github/workflows/docs.yml`
(repository **Settings → Pages → Source: GitHub Actions**).
