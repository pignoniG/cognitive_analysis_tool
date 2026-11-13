// AS7341 spectral logger: an Arduino Nano reads an AMS AS7341 11-channel spectral sensor (Adafruit 4698, DFRobot
// SEN0364 or similar breakout) and prints one spectrum per line on the serial port, for the sensor logger
// (cwtool-logger, "+ Spectral"). Nothing is stored on the board.
//
// Wiring: sensor VIN to 5V (the breakouts above have a regulator and level shifters), GND to GND, SDA to A4,
// SCL to A5. Only the Wire library is needed (it comes with the Arduino AVR core).
//
// Serial: 250000 baud. Lines starting with '#' are messages; each spectrum is one line
//
//   AS7341,<sent ms>,<mid ms>,<gain code>,<ATIME>,<ASTEP>,<saturated>,F1,F2,F3,F4,CLEAR,NIR,F5,F6,F7,F8,CLEAR,NIR
//
//   sent ms     the board's millis() just before the line is sent (the logger maps the board's clock onto the
//               computer's with it)
//   mid ms      the board's millis() at the middle of the measurement
//   gain code   AGAIN: 0 = 0.5x, 1 = 1x, 2 = 2x, ... 10 = 512x (gain = 2^(code - 1))
//   ATIME/ASTEP integration time = (ATIME + 1) * (ASTEP + 1) * 2.78 us; full scale = (ATIME + 1) * (ASTEP + 1)
//   saturated   1 if a channel reached full scale (digital) or the analog front end saturated: the counts are clipped
//   then the raw ADC counts of the two measurements: F1-F4 with CLEAR and NIR, then F5-F8 with CLEAR and NIR
//
// The six ADCs cannot see all ten photodiodes at once, so a spectrum is two integrations of 50 ms, switched by the
// sensor's multiplexer (SMUX): one spectrum every 133 ms. The gain is chosen automatically for the next spectrum
// (the brightest channel between 30 % and 80 % of full scale; a saturated spectrum drops it by 8x at once).
//
// See docs/hardware/spectral-sensor.md. Register map: AMS AS7341 datasheet (DS000504); the SMUX tables are those of
// AMS's application note and Adafruit's AS7341 library (BSD licence).

#include <Wire.h>

const uint8_t ADDRESS = 0x39;

// registers
const uint8_t REG_ENABLE = 0x80;   // bit 0 PON, bit 1 SP_EN (spectral measurement), bit 4 SMUXEN
const uint8_t REG_ATIME = 0x81;
const uint8_t REG_ID = 0x92;       // bits 7:2 = 0x09
const uint8_t REG_ASTATUS = 0x94;  // bit 7 saturation, bits 3:0 gain; reading it latches the six ADC values after it
const uint8_t REG_STATUS2 = 0xA3;  // bit 6 AVALID: a measurement is ready
const uint8_t REG_CFG0 = 0xA9;
const uint8_t REG_CFG1 = 0xAA;     // AGAIN
const uint8_t REG_CFG6 = 0xAF;     // SMUX_CMD in bits 4:3
const uint8_t REG_ASTEP_L = 0xCA;

const uint8_t PON = 0x01, SP_EN = 0x02, SMUXEN = 0x10;
const uint8_t SMUX_WRITE = 0x10;   // SMUX_CMD = 2: write the configuration in RAM 0x00-0x13 to the multiplexer

// Integration: (ATIME + 1) * (ASTEP + 1) * 2.78 us = 30 * 600 * 2.78 us = 50.0 ms; full scale 18000 counts.
const uint8_t ATIME = 29;
const uint16_t ASTEP = 599;
const uint32_t FULL_SCALE = (uint32_t)(ATIME + 1) * (ASTEP + 1);
const uint16_t INTEGRATION_MS = 51;
const uint8_t GAIN_MAX = 10;       // 512x

// SMUX: which photodiode goes to which ADC (nibble value = ADC index + 1, 0 = not connected).
const uint8_t SMUX_F1_F4[20] = {0x30, 0x01, 0x00, 0x00, 0x00, 0x42, 0x00, 0x00, 0x50, 0x00,
                                0x00, 0x00, 0x20, 0x04, 0x00, 0x30, 0x01, 0x50, 0x00, 0x06};
const uint8_t SMUX_F5_F8[20] = {0x00, 0x00, 0x00, 0x40, 0x02, 0x00, 0x10, 0x03, 0x50, 0x10,
                                0x03, 0x00, 0x00, 0x00, 0x24, 0x00, 0x00, 0x50, 0x00, 0x06};

uint8_t gain = 6;                  // 32x to start with
bool sensorReady = false;
bool led = false;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADDRESS);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegisters(uint8_t reg, uint8_t *buffer, uint8_t n) {
  Wire.beginTransmission(ADDRESS);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(ADDRESS, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buffer[i] = Wire.read();
  return true;
}

bool readRegister(uint8_t reg, uint8_t &value) {
  return readRegisters(reg, &value, 1);
}

// Wait until (register & mask) == want, at most timeoutMs.
bool waitFor(uint8_t reg, uint8_t mask, uint8_t want, uint16_t timeoutMs) {
  unsigned long start = millis();
  uint8_t value;
  do {
    if (!readRegister(reg, value)) return false;
    if ((value & mask) == want) return true;
  } while (millis() - start < timeoutMs);
  return false;
}

bool setupSensor() {
  uint8_t id;
  if (!readRegister(REG_ID, id) || (id & 0xFC) != (0x09 << 2)) return false;
  return writeRegister(REG_ENABLE, PON)
         && writeRegister(REG_CFG0, 0x00)            // register bank 0x80+, normal power
         && writeRegister(REG_ATIME, ATIME)
         && writeRegister(REG_ASTEP_L, ASTEP & 0xFF)
         && writeRegister(REG_ASTEP_L + 1, ASTEP >> 8)
         && writeRegister(REG_CFG1, gain);
}

// One integration with the given SMUX configuration: the ASTATUS byte and six ADC values in counts.
// startMs/endMs: when the integration was started and found complete.
bool measure(const uint8_t *smux, uint8_t &astatus, uint16_t counts[6], unsigned long &startMs, unsigned long &endMs) {
  if (!writeRegister(REG_ENABLE, PON)) return false;              // stop measuring while the SMUX is switched
  Wire.beginTransmission(ADDRESS);                                // RAM 0x00-0x13 in one write (auto-increment)
  Wire.write((uint8_t)0x00);
  Wire.write(smux, 20);
  if (Wire.endTransmission() != 0) return false;
  if (!writeRegister(REG_CFG6, SMUX_WRITE)) return false;
  if (!writeRegister(REG_ENABLE, PON | SMUXEN)) return false;
  if (!waitFor(REG_ENABLE, SMUXEN, 0, 50)) return false;          // SMUXEN clears when the switch is done
  if (!writeRegister(REG_ENABLE, PON | SP_EN)) return false;
  startMs = millis();
  delay(INTEGRATION_MS - 3);                                      // no need to poll before the integration can end
  if (!waitFor(REG_STATUS2, 0x40, 0x40, 4 * INTEGRATION_MS)) return false;
  endMs = millis();
  uint8_t data[13];
  if (!readRegisters(REG_ASTATUS, data, 13)) return false;
  astatus = data[0];
  for (uint8_t i = 0; i < 6; i++) counts[i] = data[1 + 2 * i] | (uint16_t(data[2 + 2 * i]) << 8);
  return true;
}

// Gain for the next spectrum from the brightest channel of this one.
void adjustGain(uint16_t peak, bool saturated) {
  uint8_t next = gain;
  if (saturated) {
    next = gain >= 3 ? gain - 3 : 0;
  } else if (peak > FULL_SCALE * 8 / 10) {
    if (gain > 0) next = gain - 1;
  } else if (peak < FULL_SCALE * 3 / 10) {
    uint32_t level = peak > 0 ? peak : 1;                         // double while it stays at most 60 % of full scale
    while (next < GAIN_MAX && level * 2 <= FULL_SCALE * 6 / 10) {
      level *= 2;
      next++;
    }
  }
  if (next != gain && writeRegister(REG_CFG1, next)) gain = next;
}

void connectSensor() {
  sensorReady = setupSensor();
  if (sensorReady) {
    Serial.println(F("# AS7341 found"));
  } else {
    Serial.println(F("# ERROR AS7341 not found: check VIN, GND, SDA = A4, SCL = A5"));
  }
}

void setup() {
  Serial.begin(250000);
  pinMode(LED_BUILTIN, OUTPUT);
  Wire.begin();
  Wire.setClock(400000);
  Wire.setWireTimeout(25000, true);                               // a stuck bus resets the I2C module, no hang
  Serial.println(F("# AS7341 spectral logger 1"));
  Serial.print(F("# integration ms "));
  Serial.print(FULL_SCALE * 2.78 / 1000.0, 2);
  Serial.print(F(", full scale "));
  Serial.println(FULL_SCALE);
  connectSensor();
}

void loop() {
  if (!sensorReady) {
    delay(1000);
    connectSensor();
    return;
  }
  uint8_t statusA, statusB, usedGain = gain;
  uint16_t a[6], b[6];
  unsigned long startA, endA, startB, endB;
  if (!measure(SMUX_F1_F4, statusA, a, startA, endA) || !measure(SMUX_F5_F8, statusB, b, startB, endB)) {
    Serial.println(F("# ERROR lost the AS7341, reconnecting"));
    sensorReady = false;
    return;
  }
  uint16_t peak = 0;
  for (uint8_t i = 0; i < 6; i++) {
    if (a[i] > peak) peak = a[i];
    if (b[i] > peak) peak = b[i];
  }
  bool saturated = ((statusA | statusB) & 0x80) || peak >= FULL_SCALE;
  adjustGain(peak, saturated);

  unsigned long mid = startA + (endB - startA) / 2;
  Serial.print(F("AS7341,"));
  Serial.print(millis());
  Serial.print(',');
  Serial.print(mid);
  Serial.print(',');
  Serial.print(usedGain);
  Serial.print(',');
  Serial.print(ATIME);
  Serial.print(',');
  Serial.print(ASTEP);
  Serial.print(',');
  Serial.print(saturated ? 1 : 0);
  for (uint8_t i = 0; i < 6; i++) {
    Serial.print(',');
    Serial.print(a[i]);
  }
  for (uint8_t i = 0; i < 6; i++) {
    Serial.print(',');
    Serial.print(b[i]);
  }
  Serial.println();
  led = !led;
  digitalWrite(LED_BUILTIN, led);                                 // blinks while spectra are sent
}
