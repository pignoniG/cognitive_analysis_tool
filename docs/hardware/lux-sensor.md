# Lux sensor hardware

Glasses-type trackers (Pupil Core, Pupil Neon) see the world through a scene camera with automatic exposure, so
their video cannot tell how bright the scene is. An [Adafruit TSL2591](https://www.adafruit.com/product/1980) light
sensor mounted on the tracker, facing forward, measures the illuminance at the eye; the analysis turns it into the
average luminance of the view (see [Luminance](../processing/luminance.md#lux-sensor-devices)).

The firmware and 3D-printable mount are in the repository's `Lux Sensor/` folder.

## Two ways to log

| | Logged to a computer | Logged to the SD card |
|---|---|---|
| Hardware | microcontroller + sensor | microcontroller + data logging shield (RTC, SD card) + battery + sensor |
| Recording | `tools/lux_logger.py` over USB | power the board on |
| Clock | the computer's, the same as the eye tracker's | the board's real-time clock: drifts seconds per day, no time zones |
| Cable | 3–4 m ribbon cable to the computer | 1.5 m, logger carried by the participant |

Either way the readings (about 10 per second) are written to one CSV per hour, `<month>_<day>_<hour>.csv`, with the
Unix time in milliseconds in the first column and lux in the fifth.

With the SD card logger, set the real-time clock to local time and correct the remaining offset with the
**time lag** parameter (for example, 3600 s for a clock one hour off).

## Bill of materials

Tested configurations (the two differ only in their real-time clock, so each has its own firmware):

**Adafruit Feather** (`Lux Sensor/Adalogger FeatherWing/Light_sd_log_direct`)

- [Adafruit Feather M4 Express](https://www.adafruit.com/product/3857), with a built-in battery charger
- [Adalogger FeatherWing](https://www.adafruit.com/product/2922): real-time clock (PCF8523) and SD card
- [3.7 V lithium battery](https://www.adafruit.com/product/1578), [CR1220](https://www.adafruit.com/product/380)
  backup battery for the clock, a 4–8 GB micro SD card
- Adafruit TSL2591 sensor and a four-conductor ribbon cable

**Arduino Nano** (`Lux Sensor/Arduino Nano/Light_sd_log_direct_nano`)

- Arduino Nano and the Deek-Robot 8105 Nano data logging shield (DS1307 real-time clock)
- Adafruit TSL2591 sensor and a four-conductor ribbon cable

Only the microcontroller and sensor are needed when always logging to a computer.

## Wiring

| TSL2591 | Microcontroller |
|---|---|
| Vin (3–5 V) | 3V |
| GND | GND |
| SCL | SCL (I²C clock) |
| SDA | SDA (I²C data) |

## Firmware

Flash the board with the Arduino IDE. The sketches need the `Adafruit_Sensor` and `Adafruit_TSL2591` libraries, and
the RTC library for the board's clock (`RTC_PCF8523` from RTClib for the FeatherWing, `DS1307RTC` for the Nano
shield). Set the clock once with the RTC library's example sketch.

Adafruit's guides: [Feather M4 setup](https://learn.adafruit.com/adafruit-feather-m4-express-atsamd51/setup),
[Adalogger RTC](https://learn.adafruit.com/adafruit-adalogger-featherwing/adafruit2-rtc-with-arduino),
[TSL2591 wiring and test](https://learn.adafruit.com/adafruit-tsl2591/wiring-and-test).

## Mount

`Lux Sensor/Mount Hardware/Adafruit Pupil lumiance sensor kit.stl` holds the sensor on the Pupil Core's world
camera and includes cable clips. It prints on a generic filament printer.

## Calibration

The analysis converts lux to average luminance with

\[
\bar L = \frac{g \cdot E + o}{\Omega}
\]

where \(E\) is the reading in lux, \(g\) = 1.706061 and \(o\) = 0.66935 are the sensor's linear calibration, and
\(\Omega\) = 2.2 sr is the solid angle of its field of view (the 1.x values; parameters `lux_gain`, `lux_offset`,
`lux_solid_angle`). Where these constants come from is not documented in 1.x
([open issue 23](../OPEN_ISSUES.md)).
