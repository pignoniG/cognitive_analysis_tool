# AS7341 spectral sensor

The AMS AS7341 (datasheet DS000504) measures the light in eight visible bands, a broadband *clear* channel and a near-infrared one. Where the
[TSL2591](lux-sensor.md) gives one number (lux), the AS7341 tells what the light is made of, which matters for the pupil:
the same lux of blue and of red light do not constrict it alike. It is read by an Arduino Nano over USB and recorded by
the [sensor logger](../usage/logger.md) next to the other sensors.

The analysis does not use it yet: its counts are not lux or luminance until the sensor is calibrated
([open issue 58](../OPEN_ISSUES.md)). The app shows its file under ΔPD and exports it, like the Shimmer's.

The datasheet's typical responsivity curves (DS000504 v3-00, Figure 19, relative to F8, 1 nm steps) are in
[`data/as7341_responsivity.csv`](data/as7341_responsivity.csv), taken from the PDF's vector paths. They give the
photopic light within about 10 % and the melanopic within about 25 % on a unit that has not been measured; see
[open issue 58](../OPEN_ISSUES.md#58-the-as7341-spectral-sensor-is-logged-but-not-calibrated-or-used-by-the-analysis).

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
