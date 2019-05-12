This folder contains the Arduino code for the sensor logger modules:
It has been tested in two configurations: 

Adalogger FeatherWing + Adafruit Feather M4 Express + Adafruit TSL2591 High Dynamic Range Digital Light Sensor

https://www.adafruit.com/product/3857
https://www.adafruit.com/product/2922
https://www.adafruit.com/product/1980

Or

Arduino Nano + Nano Data Logging Shield Deek-Robot ID 8105 + Adafruit TSL2591 High Dynamic Range Digital Light Sensor

https://forum.arduino.cc/index.php?topic=528237.0
https://www.adafruit.com/product/1980

They are equivalent in functionality but since the modules have different RTC the code is different.


The Adalogger FeatherWing code requires the Adafruit_Sensor and Adafruit_TSL2591 libraries for the sensor and uses the RTC_PCF8523 RTC.

The Nano Data Logging Shield code requires the Adafruit_Sensor and Adafruit_TSL2591 libraries for the sensor and uses the DS1307RTC RTC.

Use the example code in the respective libraries to initialise the RTC