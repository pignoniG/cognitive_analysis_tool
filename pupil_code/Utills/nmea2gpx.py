


#!/usr/bin/env python3
# coding: utf-8

# -------- #
# GPS Plot #
# -------- #

### Modules
# standard library
#import colorsys
import time as tm
import csv
import datetime
#import xml.dom.minidom as mnd

#import io
#from os.path import join
import gpxpy
import gpxpy.gpx
import pynmea2

# dependencies

import numpy as np


nemea_file = '/Users/giovanni/Desktop/sim_data/200225 - Run 01.txt'

gpx_file = nemea_file +'.gpx'



#nemea time = 2020-01-09T09:13:47 

nmea_time_epoch = 1578561227

recording_start_time = 1582615298.612032

delta_recording_time = 107

actual_recording_time = recording_start_time + delta_recording_time

gps_delta =  datetime.timedelta(seconds= actual_recording_time - nmea_time_epoch) 


# Creating a new file:
# --------------------

gpx = gpxpy.gpx.GPX()

# Create first track in our GPX:
gpx_track = gpxpy.gpx.GPXTrack()
gpx.tracks.append(gpx_track)

# Create first segment in our GPX track:
gpx_segment = gpxpy.gpx.GPXTrackSegment()
gpx_track.segments.append(gpx_segment)


#re Create points:



print("Nemea")
n_track = 0

lon_list = []
lat_list = []
h_list = []
time_list = []
#epoch_list = []

last_GPZDA = None 

row_list =[]

with open(nemea_file , newline='') as csvfile:
    reader = csv.reader(csvfile, delimiter=',', quotechar='|')
    for row in reader:
        row_list.append(row)

for i in range(len(row_list)):
    current_row =row_list[i] 

    if i+1 < len(row_list):
        if "$" in row_list[i+1][0] :
            pass
        else:
            current_row[-1] += row_list[i+1][0] 



    if current_row [0]=="$GPZDA":
        last_GPZDA = pynmea2.parse(','.join(current_row ))

    elif current_row [0]=="$GPGGA" and last_GPZDA :
        msg = pynmea2.parse(','.join(current_row ))
        lat_list.append(float(msg.latitude))
        lon_list.append(float(msg.longitude))

        #print(float(msg.latitude),float(msg.longitude))

        h_list.append(float(msg.altitude))
        
        #complete_date=[ last_GPZDA.year, last_GPZDA.month, last_GPZDA.day, msg.timestamp.hour, msg.timestamp.minute, msg.timestamp.second + msg.timestamp.microsecond]
        time_datetime = datetime.datetime(last_GPZDA.year,last_GPZDA.month, msg.timestamp.hour, msg.timestamp.hour, msg.timestamp.minute, msg.timestamp.second , msg.timestamp.microsecond)
        gps_delta

        #time_secondEph = calendar.timegm(complete_date)
        #total_second = msg.timestamp.hour * 3600 + msg.timestamp.minute * 60 + msg.timestamp.second + msg.timestamp.microsecond

        time_list.append(time_datetime+gps_delta)
        #epoch_list.append(int(time_secondEph))
        ++ n_track
    

for i in range(len(lon_list)):
    gpx_segment.points.append(gpxpy.gpx.GPXTrackPoint(lat_list[i],lon_list[i], elevation=h_list[i], time=time_list[i] ))





# You can add routes and waypoints, too...

print('Created GPX:', gpx.to_xml())

with open(gpx_file, "w") as f:
    f.write( gpx.to_xml())







