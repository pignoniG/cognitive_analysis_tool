"""Heart rate variability from the ECG of a Shimmer3 ECG unit (a sensor file of the sensor logger, see
:mod:`cwtool.sensors`).

The steps, each a function of this module:

1. :func:`millivolts`: raw ADC counts → mV, with the gain the logger saved in ``session.json`` (``ecg_gain``).
2. :func:`detect_r_peaks`: NeuroKit2 finds the R peaks (its ``neurokit`` method), on each gap-free stretch of the
   recording, on the device's own clock, which is regular (Bluetooth delays do not enter); each peak is moved to the
   maximum of the band-passed ECG nearby and refined below one sample by a parabola.
3. :func:`classify_intervals`: the time between beats, and which of them to trust: not across a gap, not outside
   ±30 % of the local median (a missed or an extra beat).
4. :func:`window_metrics`: time domain (mean heart rate, SDNN, RMSSD, pNN50), Poincaré (SD1, SD2) and frequency domain
   (LF 0.04–0.15 Hz, HF 0.15–0.4 Hz, from the interval series resampled at 4 Hz) of a window, from the trusted
   intervals only.
5. :func:`analyse`: all of it for the whole recording and for each event, respecting an export trim.

The ECG needs a high sampling rate: with 51.2 Hz (the Shimmer's usual rate) the R peak is known to ±10 ms, the same
size as the beat-to-beat differences. 256 Hz or more is required (:data:`MIN_RATE`); below it the result carries a note.
Lead II (LL−RA, ExG1 channel 1) is used, where the R wave is largest. What the numbers mean and their limits
(the window length above all) are in docs/processing/hrv.md.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.ndimage import median_filter
from scipy.signal import butter, sosfiltfilt, welch

from cwtool.sensors import Sensor
from cwtool.trim import Trim

LEAD_II = "exg_ads1292r_1_ch1_24bit"      # LL − RA, the lead used
LEAD_I = "exg_ads1292r_1_ch2_24bit"       # LA − RA
DEVICE_TIME = "device time (s)"
ADC_FULL_SCALE = 2 ** 23 - 1              # 24-bit signed
DEFAULT_GAIN = 4.0                        # the ExG PGA gain when the session does not say
REFERENCE_V = 2.42                        # V, the ADS1292R's internal reference
MIN_RATE = 200.0                          # Hz: the least ECG sampling rate accepted without a note
BAND = (0.5, 40.0)                        # Hz, the band kept for the ECG
RR_TOLERANCE = 0.30                       # an interval this far from the local median is not a normal beat to beat one
RR_LIMITS_S = (0.25, 2.5)                 # s, outside which an interval cannot be (240 to 24 bpm)
LF_BAND, HF_BAND = (0.04, 0.15), (0.15, 0.40)   # Hz
TACHOGRAM_RATE = 4.0                      # Hz, the interval series is resampled at this rate for the spectrum
MIN_SPECTRUM_S = 120.0                    # s of trusted intervals needed for LF and HF
SHORT_WINDOW_S = 60.0                     # s, below which the metrics are flagged as of a short window
MAX_GAP_S = 0.5                           # s: a shorter gap in the stream (lost packets) is bridged by interpolation, a longer
                                          # one ends the stretch of the recording that is analysed together
MIN_AMPLITUDE = 0.35                      # of the median R amplitude: a smaller deflection is not a beat (a T wave, noise)
MIN_BLOCK_S = 5.0                         # s, a gap-free stretch shorter than this is not analysed (the filter needs it)
SIGNAL_NOTE = "weak ECG: the R waves are not much above the noise"


@dataclass
class Beats:
    """The beats found in the ECG of one sensor, on the device's clock and on the Unix clock."""

    device: np.ndarray                 # s on the device's clock, one per beat
    unix: np.ndarray                   # s, Unix time of each beat
    amplitude: np.ndarray              # mV of the filtered ECG at the R peak
    block: np.ndarray                  # index of the gap-free stretch of the recording a beat is in
    rr: np.ndarray                     # s, interval from the previous beat (NaN for the first of a stretch)
    ok: np.ndarray                     # bool, the interval is trusted
    rate: float                        # Hz, sampling rate of the ECG
    gain: float                        # the ECG gain used for the millivolts
    notes: list = field(default_factory=list)


@dataclass
class HrvResult:
    """The HRV measures of one window of the recording (the whole of it, or one event)."""

    label: str
    start: float                       # s, relative clock
    end: float
    seconds: float                     # of the window that is kept (an export trim can leave parts out)
    beats: int
    intervals: int                     # trusted intervals the measures are made of
    artefact_share: float              # of the intervals in the window that were not trusted (0 to 1)
    mean_hr: float = math.nan          # bpm
    mean_nn: float = math.nan          # ms
    sdnn: float = math.nan             # ms
    rmssd: float = math.nan            # ms
    pnn50: float = math.nan            # % of successive differences above 50 ms
    sd1: float = math.nan              # ms, Poincaré
    sd2: float = math.nan              # ms
    lf: float = math.nan               # ms²
    hf: float = math.nan               # ms²
    lf_hf: float = math.nan
    notes: list = field(default_factory=list)


def millivolts(counts, gain: float = DEFAULT_GAIN, reference: float = REFERENCE_V) -> np.ndarray:
    """ECG in mV from the Shimmer's raw ExG counts (24 bit, signed): counts × reference / (2²³ − 1) / gain."""
    return np.asarray(counts, dtype=float) * reference * 1000.0 / ADC_FULL_SCALE / gain


def ecg_gain(sensor: Sensor) -> tuple[float, list]:
    """(gain, notes) of the ExG chip 1 as the logger saved it with the session; the default gain, with a note, if the
    session does not say."""
    exg = sensor.settings.get("exg", {}) if sensor.settings else {}
    chip = exg.get("chip 1", {}) if isinstance(exg, dict) else {}
    gain = chip.get("gain ch1")
    if isinstance(gain, (int, float)) and gain > 0:
        return float(gain), []
    return DEFAULT_GAIN, [f"the session does not give the ECG gain: {DEFAULT_GAIN:g} assumed (only the scale in mV "
                          "depends on it, not the beats)"]


def has_ecg(sensor: Sensor) -> bool:
    """True if the sensor is a Shimmer file with the ECG lead and the device clock."""
    return not sensor.long and LEAD_II in sensor.data and DEVICE_TIME in sensor.data and len(sensor) > 0


def _fill_gaps(x: np.ndarray) -> np.ndarray:
    """The signal with NaN samples interpolated (a few lost values)."""
    bad = ~np.isfinite(x)
    if bad.any() and not bad.all():
        x = x.copy()
        x[bad] = np.interp(np.flatnonzero(bad), np.flatnonzero(~bad), x[~bad])
    return x


def _bandpass(band: tuple[float, float], fs: float):
    """A second-order band-pass filter (second-order sections); an upper edge near or above the Nyquist frequency of a
    slow recording is moved to 80 % of it."""
    return butter(2, (band[0], min(band[1], 0.4 * fs)), btype="band", fs=fs, output="sos")


def _blocks(device: np.ndarray) -> list[tuple[int, int]]:
    """(first, end) sample indices of the stretches without a gap longer than :data:`MAX_GAP_S`."""
    cuts = np.flatnonzero(np.diff(device) > MAX_GAP_S) + 1
    edges = [0, *cuts.tolist(), len(device)]
    return [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b - a > 1]


NEUROKIT_MISSING = ("Heart rate variability needs NeuroKit2 for the detection of the R peaks: "
                    "pip install \"cwtool[hrv]\" (or pip install neurokit2)")


def detect_r_peaks(ecg_mv: np.ndarray, device: np.ndarray, fs: Optional[float] = None):
    """The R peaks of an ECG (mV) sampled at the device times ``device`` (s): returns ``(times, amplitudes, blocks)``
    with the time of each peak (s, device clock, refined below one sample), its amplitude in the band-passed signal
    and the stretch it is in (a gap of more than :data:`MAX_GAP_S` starts a new one; shorter gaps, lost packets, are
    bridged by linear interpolation). Stretches shorter than :data:`MIN_BLOCK_S` are skipped.

    The beats are found by NeuroKit2 (``ecg_clean`` and the ``neurokit`` method of ``ecg_peaks``) on each stretch,
    after flipping a stretch whose larger deflection points down. An own detector with a threshold on the squared slope
    missed the beats that were half as tall as the tallest in a 5-minute recording (breathing changes the height of
    the R wave), where NeuroKit2's found them. NeuroKit2 is also sensitive: a detection below :data:`MIN_AMPLITUDE`
    times the median R amplitude (a T wave, noise) is dropped. Raises ImportError (with the way to install it) if NeuroKit2 is missing."""
    try:
        import neurokit2 as nk
    except ImportError as e:
        raise ImportError(NEUROKIT_MISSING) from e
    device = np.asarray(device, dtype=float)
    if len(device) < 3:
        return np.empty(0), np.empty(0), np.empty(0, dtype=int)
    fs = fs or (len(device) - 1) / (device[-1] - device[0])
    ecg = _fill_gaps(np.asarray(ecg_mv, dtype=float))
    band = _bandpass(BAND, fs)
    times, amps, blocks = [], [], []
    for index, (a, b) in enumerate(_blocks(device)):
        if device[b - 1] - device[a] < MIN_BLOCK_S:
            continue
        # a uniform time grid over the stretch: filters and the detector need regular samples
        grid = device[a] + np.arange(int((device[b - 1] - device[a]) * fs) + 1) / fs
        raw = np.interp(grid, device[a:b], ecg[a:b])
        x = sosfiltfilt(band, raw - np.median(raw))
        # R waves point up in lead II; a block with the larger deflection downwards is flipped
        # (the first and last second are left out of the decision: the filter's start and end transients are large)
        core = x[int(fs):-int(fs)] if len(x) > 4 * fs else x
        sign = -1.0 if -np.percentile(core, 0.5) > np.percentile(core, 99.5) else 1.0
        x = sign * x
        cleaned = nk.ecg_clean(sign * raw, sampling_rate=int(round(fs)), method="neurokit")
        _, info = nk.ecg_peaks(cleaned, sampling_rate=int(round(fs)), method="neurokit")
        reach = max(int(0.02 * fs), 2)
        for p in np.asarray(info["ECG_R_Peaks"], dtype=int):
            lo = max(p - reach, 1)
            p = lo + int(np.argmax(x[lo:p + reach + 1]))               # the peak of the band-passed signal nearby
            if not 0 < p < len(x) - 1:
                continue
            y0, y1, y2 = x[p - 1], x[p], x[p + 1]
            denom = y0 - 2 * y1 + y2
            shift = float(np.clip(0.5 * (y0 - y2) / denom, -1, 1)) if denom != 0 else 0.0
            times.append(grid[p] + shift / fs)
            amps.append(x[p])
            blocks.append(index)
    times, amps, blocks = np.asarray(times), np.asarray(amps), np.asarray(blocks, dtype=int)
    keep = amps >= MIN_AMPLITUDE * np.median(amps) if len(amps) else np.zeros(0, dtype=bool)
    return times[keep], amps[keep], blocks[keep]


def classify_intervals(times: np.ndarray, blocks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(rr, ok)`` for beats at ``times`` (s): the interval from the previous beat (NaN for the first of a gap-free
    stretch) and whether to trust it. An interval is not trusted when it is outside :data:`RR_LIMITS_S` or further than
    :data:`RR_TOLERANCE` from the median of the intervals around it (11 of them), which catches a missed beat (about
    twice the interval) and an extra one (a short interval followed by a long one)."""
    n = len(times)
    rr = np.full(n, np.nan)
    ok = np.zeros(n, dtype=bool)
    if n < 2:
        return rr, ok
    same = blocks[1:] == blocks[:-1]
    rr[1:] = np.where(same, np.diff(times), np.nan)
    valid = np.isfinite(rr)
    if valid.sum() >= 3:
        series = rr[valid]
        local = median_filter(series, size=min(11, len(series) | 1), mode="nearest")
        good = (np.abs(series - local) <= RR_TOLERANCE * local) & (series >= RR_LIMITS_S[0]) & (series <= RR_LIMITS_S[1])
        ok[valid] = good
    return rr, ok


def beats_of(sensor: Sensor, lead: str = LEAD_II) -> Optional[Beats]:
    """Find and classify the beats of a Shimmer sensor's ECG; None if it has no ECG lead or too few samples."""
    if not has_ecg(sensor) or lead not in sensor.data:
        return None
    device = sensor.data[DEVICE_TIME]
    if len(device) < 3 or device[-1] <= device[0]:
        return None
    fs = (len(device) - 1) / (device[-1] - device[0])
    gain, notes = ecg_gain(sensor)
    notes = list(notes)
    if fs < MIN_RATE:
        notes.append(f"the ECG was sampled at {fs:.0f} Hz: below {MIN_RATE:.0f} Hz the R peaks are too coarse for HRV; "
                     "record at 256 Hz or more")
    t_dev, amp, block = detect_r_peaks(millivolts(sensor.data[lead], gain), device, fs)
    if len(t_dev) < 3:
        return Beats(t_dev, t_dev, amp, block, np.full(len(t_dev), np.nan), np.zeros(len(t_dev), bool), fs, gain,
                     notes + ["fewer than three beats found: check the electrodes"])
    # the device clock is regular but its own; the line through (device, Unix) maps it onto the computer's clock
    ok_rows = np.isfinite(sensor.unix) & np.isfinite(device)
    slope, intercept = np.polyfit(device[ok_rows], sensor.unix[ok_rows], 1)
    unix = slope * t_dev + intercept
    rr, ok = classify_intervals(t_dev, block)
    if np.median(amp) < 4 * _noise(sensor, lead, gain, fs):
        notes.append(SIGNAL_NOTE)
    return Beats(t_dev, unix, amp, block, rr, ok, fs, gain, notes)


def _noise(sensor: Sensor, lead: str, gain: float, fs: float) -> float:
    """Noise level of the ECG (mV): the median absolute deviation of its high-passed samples, which the beats hardly
    touch. Used to tell a weak ECG from a clear one."""
    x = millivolts(sensor.data[lead], gain)
    x = _fill_gaps(x)
    if len(x) < 64:
        return 0.0
    hp = sosfiltfilt(butter(2, min(20.0, 0.4 * fs), btype="high", fs=fs, output="sos"), x - np.median(x))
    return float(1.4826 * np.median(np.abs(hp - np.median(hp))))


_integrate = getattr(np, "trapezoid", None) or np.trapz   # renamed in NumPy 2


def spectrum(times: np.ndarray, nn: np.ndarray) -> tuple[float, float]:
    """(LF, HF) power in ms² of an interval series: ``nn`` (ms) at beat times ``times`` (s), resampled at
    :data:`TACHOGRAM_RATE` Hz with a cubic spline, detrended, and estimated by Welch's method."""
    if len(nn) < 10 or times[-1] - times[0] < MIN_SPECTRUM_S / 2:
        return math.nan, math.nan
    grid = np.arange(times[0], times[-1], 1.0 / TACHOGRAM_RATE)
    series = CubicSpline(times, nn)(grid)
    series = series - np.polyval(np.polyfit(grid, series, 1), grid)
    f, p = welch(series, fs=TACHOGRAM_RATE, nperseg=min(len(series), 256), noverlap=min(len(series), 256) // 2)

    def band(lo, hi):
        sel = (f >= lo) & (f < hi)
        return float(_integrate(p[sel], f[sel])) if sel.sum() >= 2 else math.nan
    return band(*LF_BAND), band(*HF_BAND)


def window_metrics(label: str, start: float, end: float, seconds: float, times_rel: np.ndarray, rr: np.ndarray,
                   ok: np.ndarray) -> HrvResult:
    """The HRV measures of one window from its beats: ``times_rel`` (s, relative clock), each beat's interval ``rr`` (s,
    from the previous beat) and whether it is trusted. ``seconds`` is how much of the window is kept. Only trusted
    intervals enter; successive differences only between two trusted intervals in a row."""
    inside = np.isfinite(rr)
    result = HrvResult(label, start, end, seconds, beats=len(times_rel), intervals=int((ok & inside).sum()),
                       artefact_share=float(((~ok) & inside).sum() / inside.sum()) if inside.any() else math.nan)
    nn = rr[ok] * 1000.0
    if len(nn) < 3:
        result.notes.append("too few trusted intervals")
        return result
    result.mean_nn = float(nn.mean())
    result.mean_hr = 60000.0 / result.mean_nn
    result.sdnn = float(nn.std(ddof=1))
    pair = ok[1:] & ok[:-1]                                  # two intervals in a row, both trusted
    diff = (rr[1:] - rr[:-1])[pair] * 1000.0
    if len(diff) >= 2:
        result.rmssd = float(np.sqrt(np.mean(diff ** 2)))
        result.pnn50 = float(100.0 * np.mean(np.abs(diff) > 50.0))
        result.sd1 = float(np.sqrt(0.5) * diff.std(ddof=1))
        result.sd2 = float(np.sqrt(max(2 * nn.var(ddof=1) - 0.5 * diff.var(ddof=1), 0.0)))
    if seconds >= MIN_SPECTRUM_S:
        result.lf, result.hf = spectrum(times_rel[ok], nn)
        if result.hf and math.isfinite(result.hf) and result.hf > 0:
            result.lf_hf = result.lf / result.hf
    if seconds < SHORT_WINDOW_S:
        result.notes.append(f"short window ({seconds:.0f} s): the measures are rough; SDNN and the frequency measures "
                            "need minutes")
    elif seconds < MIN_SPECTRUM_S:
        result.notes.append("LF and HF need at least 2 minutes")
    if result.artefact_share > 0.1:
        result.notes.append(f"{result.artefact_share:.0%} of the intervals were not trusted (movement, a poor contact?)")
    return result


def analyse(sensor: Sensor, epoch_start: float, windows, trim: Optional[Trim] = None,
            lead: str = LEAD_II) -> Optional[tuple[list[HrvResult], Beats]]:
    """HRV of a Shimmer sensor for each window. ``windows`` is a list of ``(label, start, end)`` in seconds on the
    recording's relative clock (``epoch_start`` is the Unix time of its zero); ``trim`` (:class:`Trim`) leaves out the
    parts the export leaves out: their beats are dropped and no interval counts across them. Returns the results and
    the :class:`Beats` (all of them, with trusted flags changed for the trim), or None if the sensor has no ECG."""
    beats = beats_of(sensor, lead)
    if beats is None:
        return None
    rel = beats.unix - epoch_start
    ok = beats.ok.copy()
    rr = beats.rr.copy()
    keep = np.ones(len(rel), dtype=bool)
    span = np.zeros(len(rel), dtype=int)
    if trim is not None and trim.active and len(rel):
        keep = trim.keep_mask(rel)
        for index, (a, b) in enumerate(trim.kept_spans(float(rel.min()) - 1, float(rel.max()) + 1)):
            span[(rel >= a) & (rel < b)] = index
        # an interval counts only if both beats are kept and in the same kept stretch
        both = np.zeros(len(rel), dtype=bool)
        both[1:] = keep[1:] & keep[:-1] & (span[1:] == span[:-1])
        ok &= both
        rr = np.where(both | ~np.isfinite(rr), rr, np.nan)
    beats = Beats(beats.device, beats.unix, beats.amplitude, beats.block, rr, ok, beats.rate, beats.gain, beats.notes)
    results = []
    for label, start, end in windows:
        sel = (rel >= start) & (rel < end) & keep
        if trim is not None and trim.active:
            seconds = sum(max(0.0, min(b, end) - max(a, start)) for a, b in trim.kept_spans(start, end))
        else:
            seconds = end - start
        # the first beat of the window has its interval from a beat before the window: leave that one out
        in_rr = rr[sel].copy()
        in_ok = ok[sel].copy()
        if sel.any():
            first = np.flatnonzero(sel)[0]
            if first > 0 and rel[first - 1] < start:
                in_rr[0], in_ok[0] = np.nan, False
        result = window_metrics(label, float(start), float(end), float(seconds), rel[sel], in_rr, in_ok)
        result.notes = beats.notes + result.notes
        results.append(result)
    return results, beats


SUMMARY_COLUMNS = ["window", "start_relative", "end_relative", "kept_seconds", "beats", "trusted_intervals",
                   "untrusted_percent", "mean_hr_bpm", "mean_nn_ms", "sdnn_ms", "rmssd_ms", "pnn50_percent",
                   "sd1_ms", "sd2_ms", "lf_ms2", "hf_ms2", "lf_hf", "notes"]


def _number(v: float, digits: int = 3) -> str:
    """A value for a CSV cell: empty for NaN."""
    return "" if v is None or not math.isfinite(v) else f"{v:.{digits}f}"


def write_files(results: list[HrvResult], beats: Beats, folder: Path, stem: str, epoch_start: float,
                trim: Optional[Trim] = None, lo: float = -math.inf, hi: float = math.inf) -> list[Path]:
    """Write ``<stem>_hrv.csv`` (one row of measures per window) and ``<stem>_beats.csv`` (every beat kept by the trim,
    within [``lo``, ``hi``] on the relative clock: its Unix and relative time, the interval from the previous beat and
    whether it is trusted, the R amplitude) into ``folder``; returns the two paths."""
    folder = Path(folder)
    summary = folder / f"{stem}_hrv.csv"
    with open(summary, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_COLUMNS)
        for r in results:
            w.writerow([r.label, _number(r.start), _number(r.end), _number(r.seconds, 1), r.beats, r.intervals,
                        _number(100 * r.artefact_share, 1), _number(r.mean_hr, 2), _number(r.mean_nn, 1),
                        _number(r.sdnn, 2), _number(r.rmssd, 2), _number(r.pnn50, 1), _number(r.sd1, 2),
                        _number(r.sd2, 2), _number(r.lf, 1), _number(r.hf, 1), _number(r.lf_hf, 2),
                        " | ".join(r.notes)])
    listing = folder / f"{stem}_beats.csv"
    rel = beats.unix - epoch_start
    keep = (trim or Trim()).keep_mask(rel, lo, hi)
    with open(listing, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_unix", "timestamp_relative", "rr_ms", "rr_trusted", "r_amplitude_mv"])
        for i in np.flatnonzero(keep):
            w.writerow([f"{beats.unix[i]:.6f}", f"{rel[i]:.6f}", _number(beats.rr[i] * 1000.0, 1),
                        int(beats.ok[i]), _number(beats.amplitude[i], 3)])
    return [summary, listing]
