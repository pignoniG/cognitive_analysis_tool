# Installation

The tool needs Python 3.10 or newer and runs on Windows, macOS and Linux.

## From the repository

```bash
git clone -b master_v2.0 https://github.com/pignoniG/cognitive_analysis_tool.git
cd cognitive_analysis_tool
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[gui]"
```

This installs two commands: `cwtool-gui` (desktop app) and `cwtool` (command line).

## Optional extras

| Extra | Installs | Needed for |
|---|---|---|
| `gui` | PySide6, pyqtgraph, matplotlib | the desktop app |
| `plot` | matplotlib | `cwtool --plot` (PDF plots from the command line) |
| `logger` | pyserial | `tools/lux_logger.py` |
| `dev` | pytest | running the tests |

Combine them as needed, e.g. `pip install -e ".[gui,logger,dev]"`.

## Core dependencies

Installed automatically: NumPy, SciPy, OpenCV (`opencv-python`), PyAV (`av`, fast threaded video decoding; the tool
falls back to OpenCV when it is missing) and msgpack (Pupil Core camera intrinsics).

## Checking the installation

```bash
cwtool --help
pytest            # with the dev extra: all tests should pass
```

!!! tip "Linux without a desktop"
    The Qt app needs the system's OpenGL/EGL libraries. On a minimal Debian/Ubuntu install:
    `sudo apt install libegl1 libgl1`. The command line tool does not need them.
