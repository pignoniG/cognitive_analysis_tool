"""Static matplotlib plot of a result, for the CLI."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from cwtool import palette  # noqa: E402
from cwtool.pipeline import Result  # noqa: E402
from cwtool.recording import Recording  # noqa: E402
from cwtool.trim import Trim  # noqa: E402


def plot_result(result: Result, rec: Recording, trim: Trim | None = None):
    """Figure with the raw, smoothed and expected pupil, ΔPD and the events; saved by ``--plot``
    and by the GUI's export. Parts the export leaves out (``trim``) are shaded grey."""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(result.time, result.measured_raw, color="0.6", lw=0.5, label="Measured PD (raw)")
    ax.plot(result.time, result.measured, color="black", lw=0.8, label="Measured PD")
    ax.plot(result.time, result.expected, color=palette.EXPECTED, lw=1.2, label="Expected PD")
    ax.plot(result.cw_time, result.cw, color=palette.DELTA_PD, lw=1, label="ΔPD")
    ax.axhline(result.expected_black, color=palette.EXPECTED, ls=":", lw=1)
    ax.axhline(result.expected_white, color=palette.EXPECTED, ls=":", lw=1)
    for e in rec.events:
        ax.axvspan(e.start, e.end, alpha=0.12, color=palette.EVENT)
    if trim is not None and trim.active and len(result.time):
        for a, b in trim.left_out_spans(float(result.time[0]), float(result.time[-1])):
            ax.axvspan(a, b, color="0.5", alpha=0.25, lw=0)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Pupil diameter (mm)")
    ax.set_title(f"{rec.name}  ΔPD RMS {result.cw_rms:.3f} mm")
    ax.legend(loc="upper right")
    return fig
