# AS7341 spectral sensor

The AMS AS7341 (datasheet DS000504) measures the light in eight visible bands, a broadband *clear* channel and a near-infrared one. Where the
[TSL2591](lux-sensor.md) gives one number (lux), the AS7341 tells what the light is made of, which matters for the pupil:
the same lux of blue and of red light do not constrict it alike. It is read by an Arduino Nano over USB and recorded by
the [sensor logger](../usage/logger.md) next to the other sensors.

Without a TSL2591 log, a glasses recording takes its lux from the AS7341 ([below](#as-a-lux-sensor)). The app also
shows its file under ΔPD and exports it, like the Shimmer's.

## As a lux sensor

A glasses recording (Pupil Core, Neon, Tobii Pro Glasses 3) without the TSL2591's `lux.csv` takes its lux from the
AS7341's `as7341.csv`, found the same way (`cwtool/spectral.py`). The TSL2591 comes first when both are there. The lux
is a weighted sum of the eight bands in basic counts, with weights fitted to the datasheet's typical curves and the CIE
photopic curve V(λ):

- **Curves:** the datasheet's typical responsivity (DS000504 v3-00, Figure 19, relative to F8) and its test light
  (Figure 16), taken from the PDF's vector paths. They are in [`data/`](data/), with V(λ).
- **Scale:** each band is scaled so that the test light gives the datasheet's typical counts, so the estimate is in lux.
- **Fit:** `tools/as7341_weights.py` fits the weights over blackbodies, white LEDs, display mixes, coloured LEDs and
  fluorescents (4.8 % RMS on them). A test checks the weights in the code against it.
- **Channels:** clear and NIR are not used, so an eye tracker's infrared does not enter. Saturated spectra are left
  out.
- **Smoothing:** a running median of 3 spectra, not 5.
- **Labels:** the export names the column `lux (AS7341 estimate)`, and the app says where the lux came from.

**Accuracy.** For a unit that has not been measured the estimate is within about 10 % RMS over many kinds of light
(its bands sit up to 10 nm from the typical ones). The scale under the dome is not known, and the calibration's fitted
sensitivity absorbs a constant scale. See
[open issue 58](../OPEN_ISSUES.md#58-the-as7341-spectral-sensor-is-logged-but-not-calibrated-or-used-by-the-analysis).

On the 22 November screen runs, with both sensors under their domes, the estimate read 0.92× the TSL2591's lux.
Against the luminance-matched grays, it read red 1.21×, green 0.92× and blue 0.70×, where the TSL2591 read 1.48×,
0.74× and 1.43×.

## Hardware

- Arduino Nano (ATmega328P; the clones with a CH340 USB chip work)
- An AS7341 breakout with a regulator and I²C level shifters, so it runs from the Nano's 5 V: Adafruit 4698,
  DFRobot SEN0364 or similar
- A four-conductor cable

| AS7341 breakout | Arduino Nano |
|---|---|
| VIN | 5V |
| GND | GND |
| SDA | A4 |
| SCL | A5 |

## Firmware

`Lux Sensor/Arduino Nano/AS7341_spectral_nano/AS7341_spectral_nano.ino`. It talks to the sensor's registers directly and
needs no library beyond the Arduino core's `Wire`. Flash it with the Arduino IDE (board *Arduino Nano*; for many clones
the processor *ATmega328P (Old Bootloader)*) or from the command line:

```bash
arduino-cli compile --fqbn arduino:avr:nano "Lux Sensor/Arduino Nano/AS7341_spectral_nano"
arduino-cli upload -p /dev/cu.usbserial-XXXX --fqbn arduino:avr:nano:cpu=atmega328old "Lux Sensor/Arduino Nano/AS7341_spectral_nano"
```

The Arduino IDE 2 includes `arduino-cli` in `Arduino IDE.app/Contents/Resources/app/lib/backend/resources/`. The Nano's
LED blinks while spectra are sent.

**What it does.** The sensor has six ADCs for ten photodiodes, so a spectrum is two integrations, the multiplexer
switched between them: F1–F4 with clear and NIR, then F5–F8 with clear and NIR. At 50 ms each, one spectrum every
133 ms (7.5 per second): the two integrations, the switching and the sending.
The gain (0.5× to 512×) is chosen for the next spectrum from the brightest channel of this one: it is kept between 30 %
and 80 % of full scale (18 000 counts at 50 ms), and a saturated spectrum lowers it 8× at once, so a light switched on
is followed within a few spectra. A spectrum measured while saturated is kept and flagged.

**Dim light** (firmware 2, [open issue 65](../OPEN_ISSUES.md#65-as7341-50-ms-integrations-leave-dim-scenes-at-01-counts-in-the-spectral-bands)):
the integration stays as short as the light allows. Only when the gain is at 512× and the brightest channel is still
under 5400 counts (30 % of the 50 ms full scale) is the integration doubled, to 100 ms and then 200 ms (a spectrum every
233 or 433 ms; full scale 36 000 and 65 535 counts). It is halved again as soon as the shorter integration would still
give 10 800 counts, and goes back to 50 ms at once on saturation; the gain is lowered only at 50 ms. Firmware 1 kept
50 ms, which left the bands of a dim screen at 0–1 counts.

**Serial format** (250 000 baud). Lines starting with `#` are messages (`# AS7341 spectral logger 2` at start-up,
`# ERROR ...` if the sensor is not found, after which it retries every second). Each spectrum is one line:

```text
AS7341,<sent ms>,<mid ms>,<gain code>,<ATIME>,<ASTEP>,<saturated>,F1,F2,F3,F4,CLEAR,NIR,F5,F6,F7,F8,CLEAR,NIR
```

with the board's `millis()` when the line was sent and at the middle of the measurement, the gain code (gain =
2^(code − 1)), the integration settings (time = (ATIME + 1)(ASTEP + 1) × 2.78 µs) and the raw counts.

## What the logger saves

*+ Spectral* in the [sensor logger](../usage/logger.md) finds the board by asking each USB serial port for the firmware
(or choose the port). The file, `as7341.csv`, has

| Column | |
|---|---|
| `unix time (s)` | the middle of the measurement, on the computer's clock |
| `device time (s)` | the same on the board's clock (seconds since the board started) |
| `F1 415 nm` … `F8 680 nm` | the eight bands (peak wavelength from the datasheet), in basic counts |
| `clear`, `nir` | broadband and near infrared, the mean of the two integrations, in basic counts |
| `gain`, `integration (ms)` | the settings of that spectrum (the raw counts are basic counts × gain × integration) |
| `saturated` | 1 if a channel was clipped: its values are too low |

**Basic counts** are AMS's normalisation, raw counts / (gain × integration time in ms), so spectra taken at different
gains compare directly. They are not radiometric units: the bands differ in sensitivity, and the gain steps are not
exactly 2× (the datasheet allows a few percent).

**Clock.** The board's clock is mapped onto the computer's like the Shimmer's: from the time each line left the board
and the time it arrived, along the lower envelope of their differences over the last minute (a line, since the board's
clock drifts: the Nano clone's runs 0.32 % slow), so the USB delay's jitter does not enter and the stamp is that of the
measurement, not of the arrival. A constant USB delay (a few ms) is not removed. Loggers before 22 November 2026 took
the smallest difference over the last minute, which put this board's stamps about 0.19 s early; cwtool repairs those
files when it reads them ([open issue 62](../OPEN_ISSUES.md#62-the-as7341s-timestamps-lag-its-boards-clock-drift-about-019-s-early)).
`python -m cwtool.logger.clockcheck` reports the board's clock drift and the regularity.
