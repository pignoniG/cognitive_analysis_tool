#include <Wire.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_TSL2591.h"
#include <math.h>   
#include <TimeLib.h>
#include "RTClib.h"
#include <SPI.h>
#include <SD.h>

#include <DS1307RTC.h>

Adafruit_TSL2591 tsl = Adafruit_TSL2591(2591); 

bool timeSync = false;
int  syncSecond= 61;
int  syncSecondPrev= 61;
uint64_t syncMillis = 0ULL;
long syncMillisStamp = 0;  
int frequency= 35;
const int ledPin =  LED_BUILTIN;// the number of the LED pin
int ledState = LOW;             // ledState used to set the LED
const long ledInterval = 1000;           // interval at which to blink (milliseconds)
long previousLedMillis = 0;
float frameIntervalMillis = 1.0/frequency;  
long prevFrameMillis = 0;  
long frameCount = 1;

File myFile;
const int chipSelect = 10;



float advancedRead(void)
{
  // More advanced data read example. Read 32 bits with top 16 bits IR, bottom 16 bits full spectrum
  // That way you can do whatever math and comparisons you want!
  uint32_t lum = tsl.getFullLuminosity();
  uint16_t ir, full;
  ir = lum >> 16;
  full = lum & 0xFFFF;
  return(tsl.calculateLux(full, ir));
}





void configureSensor(void){
  tsl.setGain(TSL2591_GAIN_LOW);    // 1x gain (bright light)
  //tsl.setGain(TSL2591_GAIN_MED);      // 25x gain
  //tsl.setGain(TSL2591_GAIN_HIGH);   // 428x gain
  //tsl.setGain(TSL2591_GAIN_MAX);   // 9876x gain
  
  // Changing the integration time gives you a longer time over which to sense light
  // longer timelines are slower, but are good in very low light situtations!
  tsl.setTiming(TSL2591_INTEGRATIONTIME_100MS);  // shortest integration time (bright light)
  // tsl.setTiming(TSL2591_INTEGRATIONTIME_200MS);
  //tsl.setTiming(TSL2591_INTEGRATIONTIME_300MS);
  // tsl.setTiming(TSL2591_INTEGRATIONTIME_400MS);
  // tsl.setTiming(TSL2591_INTEGRATIONTIME_500MS);
  // tsl.setTiming(TSL2591_INTEGRATIONTIME_600MS);  // longest integration time (dim light)

  /* Display the gain and integration time for reference sake */  
  Serial.println(F("------------------------------------"));
  Serial.print  (F("Gain:         "));
  
  tsl2591Gain_t gain = tsl.getGain();
  switch(gain){
  case TSL2591_GAIN_LOW:
    Serial.println(F("1x (Low)"));
    break;
  case TSL2591_GAIN_MED:
    Serial.println(F("25x (Medium)"));
    break;
  case TSL2591_GAIN_HIGH:
    Serial.println(F("428x (High)"));
    break;
  case TSL2591_GAIN_MAX:
    Serial.println(F("9876x (Max)"));
    break;
  }
  Serial.print  (F("Timing:       "));
  Serial.print((tsl.getTiming() + 1) * 100, DEC); 
  Serial.println(F(" ms"));
  Serial.println(F("------------------------------------"));
  Serial.println(F(""));
}

void setup(void){
  Serial.begin(250000);
  //while (!Serial) { delay(1);}
  pinMode(ledPin, OUTPUT);

  if (tsl.begin()) { Serial.println(F("Found a TSL2591 sensor"));}
  else { Serial.println(F("No sensor found ... check your wiring?"));}



  Serial.print("Initializing SD card...");
  // On the Ethernet Shield, CS is pin 4. It's set as an output by default.
  // Note that even if it's not used as the CS pin, the hardware SS pin 
  // (10 on most Arduino boards, 53 on the Mega) must be left as an output 
  // or the SD library functions will not work. 
  pinMode(SS, OUTPUT);
   
  if (!SD.begin(chipSelect)) {
    Serial.println("initialization failed!");
    return;
  }
  Serial.println("initialization done.");

  configureSensor();
  syncTime();
}

float unifiedSensorAPIRead(void){
  /* Get a new sensor event */ 
  float mLux=advancedRead();

  
  /* Display the results (light is measured in lux) */
  //Serial.print(F("[ ")); Serial.print(event.timestamp); Serial.print(F(" ms ] "));

  if (isnan(mLux)){
    /* Light is too low for the current gain */
  
    tsl2591Gain_t gain = tsl.getGain();
    switch(gain){
      case TSL2591_GAIN_LOW:
        tsl.setGain(TSL2591_GAIN_MED);
        mLux=advancedRead();
        break;
      case TSL2591_GAIN_MED:
        tsl.setGain(TSL2591_GAIN_HIGH);
        mLux=advancedRead();
        break;
      case TSL2591_GAIN_HIGH:
        tsl.setGain(TSL2591_GAIN_MAX);
        mLux=advancedRead();
        break;
      case TSL2591_GAIN_MAX:
        mLux=0;
        break;
      }
  }

  if (mLux <= 0) {
    /* Light is too hight for the current gain */
    tsl2591Gain_t gain = tsl.getGain();
    switch(gain){
      case TSL2591_GAIN_LOW:
        mLux=100000;
        break;
      case TSL2591_GAIN_MED:
        tsl.setGain(TSL2591_GAIN_LOW);
        mLux=advancedRead();
        break;
      case TSL2591_GAIN_HIGH:
        tsl.setGain(TSL2591_GAIN_MED);
        mLux=advancedRead();
        break;
      case TSL2591_GAIN_MAX:
        tsl.setGain(TSL2591_GAIN_HIGH);
        mLux=advancedRead();
        break;
    }
  }


  Serial.println(mLux);
    tsl2591Gain_t gain = tsl.getGain();
    switch(gain){
      
    case TSL2591_GAIN_LOW:
      if(mLux<6000){
        tsl.setGain(TSL2591_GAIN_MED);}
      break;

    case TSL2591_GAIN_MED:
      break;

    case TSL2591_GAIN_HIGH:
      break;

    case TSL2591_GAIN_MAX:
      break;
    }


  return (mLux);

}

void syncTime() {
  tmElements_t tm;
  if (RTC.read(tm)) {
    syncSecond=int(tm.Second);
    syncSecondPrev = syncSecond;
 

  Serial.println("syncTime()");
  
   
  
  
  while(!timeSync){ 
    tmElements_t tm;
    RTC.read(tm);
    syncSecond= int(tm.Second); 
    if(syncSecondPrev!=syncSecond){

      setTime(tm.Hour,tm.Minute,tm.Second,tm.Day,tm.Month,tmYearToCalendar(tm.Year));
      syncMillis =now()*1000ULL;
      syncMillisStamp =  millis();
      prevFrameMillis = syncMillisStamp;
    
      timeSync=true;
        Serial.println("Time synced!");
     print2digits(tm.Hour);
    Serial.write(':');
    print2digits(tm.Minute);
    Serial.write(':');
    print2digits(tm.Second);
    Serial.print(", Date (D/M/Y) = ");
    Serial.print(tm.Day);
    Serial.write('/');
    Serial.print(tm.Month);
    Serial.write('/');
    Serial.print(tmYearToCalendar(tm.Year));
    Serial.println();
      }
    syncSecondPrev = syncSecond; 
  }}
}


void loop(void){ 
unsigned long currentMillis = millis();
  
    if (currentMillis - previousLedMillis >= ledInterval) {
    // save the last time you blinked the LED
    previousLedMillis = currentMillis;

    // if the LED is off turn it on and vice-versa:
    if (ledState == LOW) {
      ledState = HIGH;
    } else {
      ledState = LOW;
    }

    // set the LED with the ledState of the variable:
    digitalWrite(ledPin, ledState);
  }

  
  float luxValue = unifiedSensorAPIRead();





    if((currentMillis - prevFrameMillis)/1000.00 >= frameIntervalMillis) {

      //Serial.print("sUtime = ");
      //Serial.println (now());
      //Serial.print("mUtime = ");
      uint64_t millsUtime= currentMillis - syncMillisStamp + syncMillis;   
      uint64_t xx = millsUtime/1000000000ULL;
       //if (xx >0) Serial.print((long)xx);
       //Serial.print((long)(millsUtime - xx*1000000000));
       //Serial.println ();
      
      //Serial.print("Frame = ");
      //Serial.print(frameCount);
      //Serial.write('-');
      //Serial.println(frameCount/((currentMillis - syncMillisStamp)/1000));
      //DateTime rtcTime = rtc.now();
       //Serial.print("Time = ");
       //Serial.print(hour());
       //Serial.write(':');
       //Serial.print(minute());
      //Serial.print(rtcTime.minute());
            
       //Serial.write(':');
       //Serial.println(second());
      //Serial.print(rtcTime.second());
      //Serial.println();



      prevFrameMillis=currentMillis;


      String fileName = String(month()) +"_"+ String(day()) +"_"+ String(hour()) + ".csv";
      //Serial.println(fileName);
      myFile = SD.open(fileName , FILE_WRITE);
        
        
      if (myFile) {

        if (xx >0) myFile.print((long)xx);
        myFile.print((long)(millsUtime - xx*1000000000));
        myFile.write(',');
        myFile.print(hour());
        myFile.write(',');
        myFile.print(minute());
        myFile.write(',');
        myFile.print(second());
        myFile.write(',');
        myFile.println(luxValue);
        

        myFile.close();

         

         
        }  else {
        // if the file didn't open, print an error:
        //Serial.println("error opening test.csv");
        }
        
        frameCount = frameCount+1;
      
     }



  

}

void print2digits(int number) {
  if (number >= 0 && number < 10) {
    Serial.write('0');
  }
  Serial.print(number);
}
