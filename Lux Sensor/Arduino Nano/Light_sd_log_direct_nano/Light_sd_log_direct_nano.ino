// Lux sensor logger: an Arduino Nano with a Deek-Robot data logging shield reads an Adafruit TSL2591 light sensor,
// prints each reading on the serial port for the sensor logger (cwtool-logger, "+ Lux") and appends it to an
// hourly CSV file on the SD card. See ../../ReadMe.txt and docs/hardware/lux-sensor.md.
//
// Serial: 250000 baud. Lines starting with '#' are messages; each reading is one line
//
//   TSL2591,<sent ms>,<mid ms>,<clock ms>,<gain>,<integration ms>,<full>,<ir>,<saturated>,<lux>
//
//   sent ms         the board's millis() just before the line is sent (the logger maps the board's clock onto the
//                   computer's with it)
//   mid ms          the board's millis() at the middle of the integration
//   clock ms        the SD file's clock at millis() = 0: Unix time in ms from the real-time clock, read once at
//                   start-up (0 if the real-time clock was not found); the SD file's time is clock ms + millis()
//   gain            1, 25, 428 or 9876
//   full, ir        the raw counts of the two photodiodes (visible + infrared, infrared)
//   saturated       1 if a channel reached the full scale (37888 counts at 100 ms): the counts are clipped
//   lux             Adafruit's formula, (full - ir) * (1 - ir / full) / (100 ms * gain / 408)
//
// SD card: <month>_<day>_<hour>.csv, rows
//
//   <Unix ms at mid-integration>,<hour>,<minute>,<second>,<lux>,<full>,<ir>,<gain>,<saturated>
//
// (readers of the earlier files, which ended at the lux, read these: the lux is still the fifth column).
//
// The gain is chosen for the next reading from the full channel of this one: lower above 80 % of full scale, higher
// while the next gain would leave it under 50 % (open issue 64). Earlier versions stayed at 25x in dim light.
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_TSL2591.h"
#include <TimeLib.h>
#include <SPI.h>
#include <SD.h>
#include <DS1307RTC.h>
Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591);

const char VERSION[] = "# TSL2591 lux logger 2";
const uint16_t INTEGRATION_MS = 100;
const uint32_t FULL_SCALE = 37888;          // counts at 100 ms (datasheet)
const tsl2591Gain_t GAINS[4] = {TSL2591_GAIN_LOW, TSL2591_GAIN_MED, TSL2591_GAIN_HIGH, TSL2591_GAIN_MAX};
const uint16_t GAIN_VALUES[4] = {1, 25, 428, 9876};
const int chipSelect = 10;

uint8_t gainIndex = 1;                      // 25x to start with
uint64_t clockAtZero = 0;                   // Unix ms of millis() = 0, from the real-time clock
bool sdReady = false;
bool led = false;
unsigned long lastLed = 0;

// A 64-bit number in decimal (Print has no 64-bit overload on every core).
void print64(Print &out, uint64_t v) {
  char buffer[21];
  uint8_t i = sizeof(buffer) - 1;
  buffer[i] = 0;
  do {
    buffer[--i] = '0' + (v % 10);
    v /= 10;
  } while (v > 0);
  out.print(&buffer[i]);
}

// Unix ms of millis() = 0: wait for the real-time clock's second to change, then take millis() at that moment.
// The Nano's clock (a ceramic resonator) can run 0.3 % off, so the SD file's times drift from the real-time clock's
// by seconds an hour; the sensor logger measures the drift (open issue 64).
void syncClock() {
  tmElements_t tm;
  if (!RTC.read(tm)) {
    Serial.println(F("# ERROR real-time clock not found or not set: the SD file's times start at 1970"));
    return;
  }
  uint8_t previous = tm.Second;
  unsigned long start = millis();
  while (millis() - start < 1500) {
    if (RTC.read(tm) && tm.Second != previous) {
      unsigned long at = millis();
      setTime(tm.Hour, tm.Minute, tm.Second, tm.Day, tm.Month, tmYearToCalendar(tm.Year));
      clockAtZero = (uint64_t)now() * 1000ULL - at;
      Serial.print(F("# real-time clock "));
      Serial.print(tmYearToCalendar(tm.Year));
      Serial.print('-');
      Serial.print(tm.Month);
      Serial.print('-');
      Serial.print(tm.Day);
      Serial.print(' ');
      Serial.print(tm.Hour);
      Serial.print(':');
      Serial.print(tm.Minute);
      Serial.print(':');
      Serial.print(tm.Second);
      Serial.println(F(" (no time zone; set by hand)"));
      return;
    }
  }
  Serial.println(F("# ERROR real-time clock not running: the SD file's times start at 1970"));
}

// Gain for the next reading from the full channel of this one.
void adjustGain(uint16_t full, bool saturated) {
  uint8_t next = gainIndex;
  if (saturated || full > FULL_SCALE * 8 / 10) {
    if (next > 0) next--;
  } else {
    uint32_t level = full;
    while (next < 3 && level * GAIN_VALUES[next + 1] / GAIN_VALUES[next] <= FULL_SCALE / 2) {
      level = level * GAIN_VALUES[next + 1] / GAIN_VALUES[next];
      next++;
    }
  }
  if (next != gainIndex) {
    gainIndex = next;
    tsl.setGain(GAINS[gainIndex]);
  }
}

void writeSd(uint64_t unixMs, float lux, uint16_t full, uint16_t ir, uint16_t gain, bool saturated) {
  if (!sdReady) return;
  String fileName = String(month()) + "_" + String(day()) + "_" + String(hour()) + ".csv";
  File f = SD.open(fileName, FILE_WRITE);
  if (!f) return;
  print64(f, unixMs);
  f.write(',');
  f.print(hour());
  f.write(',');
  f.print(minute());
  f.write(',');
  f.print(second());
  f.write(',');
  f.print(lux, 5);
  f.write(',');
  f.print(full);
  f.write(',');
  f.print(ir);
  f.write(',');
  f.print(gain);
  f.write(',');
  f.println(saturated ? 1 : 0);
  f.close();
}

void setup(void) {
  Serial.begin(250000);
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.println(VERSION);
  if (!tsl.begin()) {
    Serial.println(F("# ERROR TSL2591 not found: check the wiring"));
  }
  tsl.setTiming(TSL2591_INTEGRATIONTIME_100MS);
  tsl.setGain(GAINS[gainIndex]);
  syncClock();
  pinMode(SS, OUTPUT);
  sdReady = SD.begin(chipSelect);
  if (!sdReady) Serial.println(F("# ERROR SD card not found: readings go to the serial port only"));
}

void loop(void) {
  unsigned long now = millis();
  if (now - lastLed >= 1000) {                // blinks once a second while it runs
    lastLed = now;
    led = !led;
    digitalWrite(LED_BUILTIN, led);
  }

  uint16_t gain = GAIN_VALUES[gainIndex];
  unsigned long start = millis();             // getFullLuminosity starts the integration, waits 120 ms, reads
  uint32_t both = tsl.getFullLuminosity();
  unsigned long mid = start + INTEGRATION_MS / 2;
  uint16_t ir = both >> 16, full = both & 0xFFFF;
  bool saturated = full >= FULL_SCALE || ir >= FULL_SCALE;
  float lux = full > 0 ? tsl.calculateLux(full, ir) : 0.0;   // at the gain of this reading
  adjustGain(full, saturated);

  Serial.print(F("TSL2591,"));
  Serial.print(millis());
  Serial.print(',');
  Serial.print(mid);
  Serial.print(',');
  print64(Serial, clockAtZero);
  Serial.print(',');
  Serial.print(gain);
  Serial.print(',');
  Serial.print(INTEGRATION_MS);
  Serial.print(',');
  Serial.print(full);
  Serial.print(',');
  Serial.print(ir);
  Serial.print(',');
  Serial.print(saturated ? 1 : 0);
  Serial.print(',');
  Serial.println(lux, 5);

  writeSd(clockAtZero + mid, lux, full, ir, gain, saturated);  // after the line, so it does not delay it
}
