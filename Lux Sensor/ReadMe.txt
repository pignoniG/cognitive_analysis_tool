This folder contains the Arduino code for the sensor logger modules:
It has been tested in two configurations: 

Adalogger FeatherWing + Adafruit Feather M4 Express + Adafruit TSL2591 High Dynamic Range Digital Light Sensor

https://www.adafruit.com/product/3857


https://www.adafruit.com/product/1980

Or

Arduino Nano + Nano Data Logging Shield Deek-Robot ID 8105 + Adafruit TSL2591 High Dynamic Range Digital Light Sensor

https://forum.arduino.cc/index.php?topic=528237.0
https://www.adafruit.com/product/1980

They are equivalent in functionality but since the modules have different RTC the code is different.


AS7341 spectral sensor (Arduino Nano/AS7341_spectral_nano)

Arduino Nano + an AS7341 breakout (Adafruit 4698, DFRobot SEN0364 or similar), connected to a computer over USB and
recorded by the sensor logger (cwtool-logger, "+ Spectral"). Nothing is stored on the board. Wiring: VIN to 5V, GND to
GND, SDA to A4, SCL to A5. No library beyond the Arduino core's Wire. See docs/hardware/spectral-sensor.md.
