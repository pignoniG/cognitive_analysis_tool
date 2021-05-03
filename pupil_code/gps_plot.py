#!/usr/bin/env python3
# coding: utf-8

# -------- #
# GPS Plot #
# -------- #

### Modules
# standard library
import colorsys
import time as tm
import csv
import calendar
import xml.dom.minidom as mnd


import io
from os.path import join


# dependencies
import matplotlib.cm as cm
cmap = cm.jet

import numpy as np
from adjustText import adjust_text

# custom code
from pupil_code.pupil_tools.data_tools import *
from pupil_code.pupil_tools.colour_tools import *
from pupil_code.pupil_tools.signal_tools import *
from pupil_code.pupil_tools.geo_tools import *

### Constants

### Functions & Procedures

### Variables

### Instructions



def plotGpsCW(self):

    #self.plotGps.close()

    #SMALL_SIZE = 16
    #MEDIUM_SIZE = 20
    #BIGGER_SIZE = 24
    #self.plotGps.rc('font', size=SMALL_SIZE)          # controls default text sizes
    #self.plotGps.rc('axes', titlesize=SMALL_SIZE)     # fontsize of the axes title
    #self.plotGps.rc('axes', labelsize=MEDIUM_SIZE)    # fontsize of the x and y labels
    #self.plotGps.rc('xtick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
    #self.plotGps.rc('ytick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
    #self.plotGps.rc('legend', fontsize=SMALL_SIZE)    # legend fontsize
    #self.plotGps.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title

    data_source = self.settingsDict['recordingFolder']

    recording_name = data_source.split("/")[-1]

    # export inside the recording
    export_source = join(data_source, "exports", "000")

    # export all in a separate folder
    export_source_alt = self.settingsDict['exportFolder']
    data = open(join(data_source, 'gps_track.gpx'))

    exportfromgps = self.settingsDict['exportDataFromgps']
    timevsWl = self.settingsDict['timevsWl']
    distancevsWl = self.settingsDict['distancevsWl']

    # READ GPX FILE

    xmldoc = mnd.parse(data)
    track = xmldoc.getElementsByTagName('trkpt')
    elevation = xmldoc.getElementsByTagName('ele')
    datetime = xmldoc.getElementsByTagName('time')
    n_track = len(track)

    first_row = True
    # Read distance
    distanceVal = []
    rawDistanceVal = []

    # Read distance
    distanceTime = []
    rawDistanceTime = []

    with open(join(export_source, "pupilOutputDistance.csv")) as csvDataFile:
        csvReader = csv.reader(csvDataFile)
        for row in csvReader:
            if first_row:
                first_row = False
            else:
                rawDistanceVal.append(float(row[0]))
                rawDistanceTime.append(float(row[4]))
        csvDataFile.close()


    for i in range(int((rawDistanceTime[-1]-rawDistanceTime[0])/5)):
        time_r = rawDistanceTime[0]+i*5
        val = findClosestsAndIterpolate(time_r, rawDistanceTime, rawDistanceVal)

        distanceVal.append(val)
        distanceTime.append(time_r)

    # PARSING GPX ELEMENT
    lon_list = []
    lat_list = []
    h_list = []
    time_list = []
    epoch_list = []

    for s in range(n_track):
        lon, lat = track[s].attributes['lon'].value, track[s].attributes['lat'].value
        elev = elevation[s].firstChild.nodeValue
        lon_list.append(float(lon))
        lat_list.append(float(lat))
        h_list.append(float(elev))
        # PARSING TIME ELEMENT
        dt = datetime[s].firstChild.nodeValue
        print (dt)

        time_split = dt.split('T')
        hms_split = time_split[1].split(':')
        time_hour = int(hms_split[0])
        time_minute = int(hms_split[1])
        time_second = float(hms_split[2].split('Z')[0])
        # 'Jul 9, 2009 @ 20:02:58 UTC'
        time_secondEph = calendar.timegm(tm.strptime(dt, '%Y-%m-%dT%H:%M:%S.%fZ'))

        total_second = time_hour*3600+time_minute*60+time_second
        time_list.append(total_second)
        epoch_list.append(int(time_secondEph))

    
# POPULATE DISTANCE AND SPEED LIST
    d_list = [0.0]
    speed_list = [0.0]
    l = 0
    for k in range(n_track-1):
        if k < (n_track-1):
            l = k+1
        else:
            l = k
        XY0 = geo2cart(lon_list[k], lat_list[k], h_list[k])
        XY1 = geo2cart(lon_list[l], lat_list[l], h_list[l])

        # DISTANCE
        d = distance(XY0[0], XY0[1], XY1[0], XY1[1])
        sum_d = d+d_list[-1]
        d_list.append(sum_d)

        # SPEED
        s = speed(XY0[0], XY0[1], XY1[0], XY1[1], time_list[k], time_list[l])
        speed_list.append(s)

    # PLOT TRACK
    # f,(track,speed,elevation)=self.plotGps.subplots(3,1)
    f, (track) = self.plot.subplots(1, 1, figsize=(6, 11))
    # f.set_figheight(8)
    # f.set_figwidth(2)

    lonMax = max(lon_list)
    lonMin = min(lon_list)
    lonDelta = lonMax-lonMin
    latMax = max(lat_list)
    latMin = min(lat_list)
    latDelta = latMax-latMin

    a, lat_max, lon_min, lat_min, lon_max = getImageCluster(latMin, lonMin, latDelta, lonDelta)
    # fig = track.figure()
    # fig.patch.set_facecolor('white')
    track.imshow(np.asarray(a), zorder=0, extent=[lon_max, lon_min, lat_max, lat_min])
    track.set_xlim((lon_max, lon_min))
    track.set_ylim((lat_max, lat_min))

    # self.plotGps.subplots_adjust(hspace=0.5)
    track.set_aspect(2)
    # img = self.plotGps.imread("/Users/giovanni/Desktop/AAA_filed_test/map_n.jpg")
    # track.imshow(img, zorder=0, extent=[5.1272, 5.2515, 60.2750, 60.4057])
    track.plot(lon_list, lat_list, 'k')

    track.set_ylabel("Latitude")
    track.set_xlabel("Longitude")
    track.set_title(f"{recording_name} Track Plot")

    # track.set_aspect(2.1663)
    # PLOT SPEED
    # speed.bar(d_list,speed_list,30,color='w',edgecolor='w')
    # speed.set_title("Speed")
    # speed.set_xlabel("Distance(m)")
    # speed.set_ylabel("Speed(m/s)")

    # PLOT ELEVATION PROFILE
    # elevation.fill_between(d_list,h_list,base_reg,alpha=0.1)
    # elevation.set_title("Elevation Profile")
    # elevation.set_xlabel("Distance(m)")
    # elevation.set_ylabel("GPS Elevation(m)")
    # elevation.grid()
    # ANIMATION/DYNAMIC PLOT
    distanceVal_std = np.nanstd(distanceVal)
    
    #distanceVal_mean = np.nanmean(distanceVal)
    #distanceVal_min = min(distanceVal)
    #distanceVal_max = max(distanceVal)
    #distanceVal_var = distanceVal_max-distanceVal_min
    
    for i in range(len(distanceTime)-1):
        lon_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lat_list)

        track.plot(lon_closestValue, lat_closestValue, marker='o',
                   markersize=8, mfc=(1, 1, 1, 1), mec=(1, 1, 1, 0.0))
    
   
    for i in range(len(distanceTime)-1):
        lon_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lat_list)
        
        curr_distanceVal = distanceVal[i]
      

        c = (curr_distanceVal + distanceVal_std*1.5) / ((distanceVal_std*1.5)*2)
        # c = (distanceVal[i] - distanceVal_min) /(distanceVal_var)

        if c < 0:
            c = 0
        if c > 1:
            c = 1

        c = 0.4-c*0.4
        c = colorsys.hsv_to_rgb(c, 1, 1)
        r = c[0]
        g = c[1]
        b = c[2]

        track.plot(lon_closestValue, lat_closestValue, marker='o',
                   markersize=8.1, mfc=(r, g, b, 0.6), mec=(0, 0, 0, 0.0))
        
    texts = []

#export wl vs time start
    if exportfromgps:
 
        prevDist = 0
        prevTime = 0

        time_s_list=[]
        time_m_list=[]
        recording_names=[]
        lon_closestValue_list=[]
        lat_closestValue_list=[]
        distance_closestValue_list=[]
        speed_closestValue_list=[]
        wl_closestValue_list=[]

    
        for i in range(int((distanceTime[-1]-distanceTime[0]))):
            time = int(distanceTime[0])+i
            time_s = i
            time_m = time_s /60

            if time_s - prevTime >= timevsWl:

                lon_closestValue = findIntervalAndAverage(time - timevsWl, time, epoch_list, lon_list)
                lat_closestValue = findIntervalAndAverage(time - timevsWl, time, epoch_list, lat_list)
                distance_closestValue = findIntervalAndAverage(time - timevsWl, time, epoch_list, d_list)
                speed_closestValue = findIntervalAndAverage(time - timevsWl, time, epoch_list, speed_list)
                wl_closestValue = findIntervalAndAverage(time - timevsWl, time, distanceTime, distanceVal)

                time_s_list.append(time_s)
                recording_names.append(recording_name)
                time_m_list.append(round(time_m, 2))
                lon_closestValue_list.append(lon_closestValue)
                lat_closestValue_list.append(lat_closestValue)
                distance_closestValue_list.append(round(distance_closestValue, 2))
                speed_closestValue_list.append(round(speed_closestValue, 2))
                wl_closestValue_list.append(round( wl_closestValue, 5))
        
                prevTime = time_s


    
        csv_header = ["recording_name","time_s","time_m","lon","lat","distance","speed","Wl"]

        csv_rows = [recording_names,
                    time_s_list,
                    time_m_list,
                    lon_closestValue_list,
                    lat_closestValue_list,
                    distance_closestValue_list,
                    speed_closestValue_list,
                    wl_closestValue_list]

        saveCsv(export_source_alt, recording_name+"_pupilOutputVsTime.csv", csv_header, csv_rows)
    

#export wl vs time end


#export wl vs distance start
    if exportfromgps:
 
        prevDist = 0
        prevTime = 0

        time_s_list=[]
        time_m_list=[]
        recording_names=[]
        lon_closestValue_list=[]
        lat_closestValue_list=[]
        distance_closestValue_list=[]
        speed_closestValue_list=[]
        wl_closestValue_list=[]

    
        for i in range(int((distanceTime[-1]-distanceTime[0])*100)):
            time = int(distanceTime[0])+i/100
            time_s = i/100
            time_m = time_s /60
    

            distance_closestValue = findClosestsAndIterpolate(time, epoch_list, d_list)
            
           

          
    
    
            if distance_closestValue - prevDist >= distancevsWl:
                prevDist = distance_closestValue
                prevTime = time

                lon_closestValue = findIntervalAndAverage(prevTime , time, epoch_list, lon_list)
                lat_closestValue = findIntervalAndAverage(prevTime , time, epoch_list, lat_list)
                speed_closestValue = findIntervalAndAverage(prevTime , time, epoch_list, speed_list)
                wl_closestValue = findIntervalAndAverage(prevTime , time, distanceTime, distanceVal)

                recording_names.append(recording_name)

                time_s_list.append(time_s)
                time_m_list.append(round(time_m, 2))
                lon_closestValue_list.append(lon_closestValue)
                lat_closestValue_list.append(lat_closestValue)
                distance_closestValue_list.append(round(distance_closestValue, 2))
                speed_closestValue_list.append(round(speed_closestValue, 2))
                wl_closestValue_list.append(round( wl_closestValue, 5))
        
                


    
        csv_header = ["recording_name","time_s","time_m","lon","lat","distance","speed","Wl"]

        csv_rows = [recording_names,
                    time_s_list,
                    time_m_list,
                    lon_closestValue_list,
                    lat_closestValue_list,
                    distance_closestValue_list,
                    speed_closestValue_list,
                    wl_closestValue_list]

        saveCsv(export_source_alt, recording_name+"_pupilOutputVsDistance.csv", csv_header, csv_rows)
    

#export wl vs distance end


    texts = []
    prevDist = 0

    for i in range(int((distanceTime[-1]-distanceTime[0])/60)):
        time = int(distanceTime[0])+i*60
        time_s = i

        lon_closestValue = findClosestsAndIterpolate(time, epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(time, epoch_list, lat_list)
        distance_closestValue = findClosestsAndIterpolate(time, epoch_list, d_list)


        if distance_closestValue - prevDist >= 200:
            prevDist = distance_closestValue
            track.plot(lon_closestValue,
                       lat_closestValue,
                       marker='.',
                       markersize=3,
                       mfc=(0, 0, 0, 0),
                       mec=(0, 0, 0, 0.5))
            texts.append(track.text(lon_closestValue+0.001, lat_closestValue+0.001, f"{time_s} min", fontsize=8))

    adjust_text(texts, only_move={'texts': 'x'})
    self.plot.savefig(f'{export_source_alt}/plot{recording_name}.pdf',
                         bbox_inches='tight')
    self.plot.show(block=False) 
