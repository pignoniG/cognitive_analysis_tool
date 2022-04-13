#!/usr/bin/env python3
# coding: utf-8

# ---------- #
# Data Tools #
# ---------- #

### Modules
# standard library
import os
from bisect import bisect_left
from os.path import join, normpath
import csv
import gzip
import json

# dependencies
import numpy as np
from scipy.signal import savgol_filter

# custom code
from pupil_code.pupil_tools.signal_tools import interpnan


### Functions & Procedures
def readInfoOld(data_source):
    # read the recording info.csv file
    info = {}
    with open(join(data_source, "info.csv")) as csvDataFile:
        for index, row in enumerate(csv.reader(csvDataFile)):
            if index > 0:
                info[row[0]] = row[1]
    return info

def readInfo(data_source):
    # read the recording info.player.json file
    info = {}
    with open(join(data_source, "info.player.json")) as jsonDataFile:
        info= json.load(jsonDataFile)
    
    return info

def readInfoTobiiG3(data_source):
    # read the recording info.player.json file
    info = {}
    with open(join(data_source, "recording.g3")) as jsonDataFile:
        info= json.load(jsonDataFile)
    
    return info

def readPupilTobiiG3(data_source):
    """read gazedata.gz"""
    pupil_positions = []
    with gzip.open(join(data_source, "gazedata.gz"), 'r') as jsonDataFile:
        for jsonObj in jsonDataFile:
            pupil_positions.append(json.loads(jsonObj))

    return pupil_positions

def readPupil(export_source):
    """read pupil_positions.csv"""
    pupil_positions = []
    with open(join(export_source, "pupil_positions.csv")) as csvDataFile:
        csvReader = csv.reader(csvDataFile)
        for index, row in enumerate(csvReader):
            if index > 0:
                pupil_positions.append(row)
    return pupil_positions

def readCamera(data_source):
    # read the camera data from the pupilCV.py script

    indexLum = []
    avgLum = []   # average "relative lumiance" of the sine
    timeStampsLum = []
    spotLum = []   # "relative lumiance" on the spot
    fieldDiameter = []   # "relative lumiance" on the spot
    frame = 0

    with open(join(data_source, 'outputFromVideo.csv')) as csvDataFile:
        for index, row in enumerate(csv.reader(csvDataFile)):
            if index > 0:
                # indexLum,timeStampsLum,avgLum,spotLum
                indexLum.append(float(row[0]))
                timeStampsLum.append(float(row[1]))
                avgLum.append(float(row[2]))
                spotLum.append(float(row[3]))
                fieldDiameter.append(float(row[4]))
                frame = frame+1
    return indexLum, timeStampsLum, avgLum, spotLum ,fieldDiameter

def readLux(lux_data_source, data_source, recStartTime, recEndTime):
    
    print("reading the pc saved lux")
    correction = 0
    coeff = 0.001

    ##### read lux values#####
    startMonth = recStartTime.month
    startDay = recStartTime.day
    startHour = recStartTime.hour
    endHour = recEndTime.hour

    luxValues = []
    luxTimeStamps = []

    for hour in range(startHour-1, endHour + 2):
        fileName = f'{startMonth}_{startDay}_{hour}.csv'

        if os.path.isfile(lux_data_source+"/"+fileName):

            with open(join(lux_data_source+"/", fileName)) as csvDataFile:
                for row in csv.reader(csvDataFile):
                    x = float(row[4])
                    x = 1.706061*x + 0.66935
                    y = x/2.2
                    luxValues.append(y)
                    luxTimeStamps.append((float(row[0]))*coeff-correction)
    return luxTimeStamps, luxValues

def graphPlot(plotElem, x, y, color, tckness, label):
    # plot, but more compact
    plotElem.plot(x, y,
                  marker='o',
                  markerfacecolor=color,
                  markersize=0,
                  color=color,
                  linewidth=tckness,
                  label=label)

def readGaze(export_source):
    gaze_pos = []
    gaze_pos_x = []
    gaze_pos_y = []

    with open(join(export_source, "gaze_positions.csv")) as csvGazeFile:
        for index, row in enumerate( csv.reader(csvGazeFile)):
            if index > 0:
                gaze_pos.append(row)
                gaze_pos_x.append(float(row[3]))
                gaze_pos_y.append(float(row[4]))

    # filtering the noisy gaze x and y
    #gaze_pos_x = savgol_filter(gaze_pos_x, 120*1+1, 2)
    #gaze_pos_y = savgol_filter(gaze_pos_y, 120*1+1, 2)

    return gaze_pos, gaze_pos_x, gaze_pos_y


def readGazeTobiiG3(data_source,fps):

    gaze_positions = []
    gaze_pos = []
    gaze_pos_l_x = []
    gaze_pos_r_x = []
    gaze_pos_l_y = []
    gaze_pos_r_y = []
    frame_list = []


    """read gazedata.gz"""
   
    with gzip.open(join(data_source, "gazedata.gz"), 'r') as jsonDataFile:
        for jsonObj in jsonDataFile:
            gaze_positions.append(json.loads(jsonObj))




    for gaze_position in gaze_positions:
        if ( "eyeleft" in gaze_position["data"] and "eyeright" in gaze_position["data"]):
            if ( "pupildiameter" in gaze_position["data"]["eyeleft"] and "pupildiameter" in gaze_position["data"]["eyeright"]):
                gaze_pos.append(gaze_positions)
                gaze_pos_l_x.append(float(gaze_position["data"]["gaze2d"][0]))
                gaze_pos_r_x.append(float(gaze_position["data"]["gaze2d"][0]))
                gaze_pos_l_y.append(float(gaze_position["data"]["gaze2d"][1]))
                gaze_pos_r_y.append(float(gaze_position["data"]["gaze2d"][1]))
                frame_n= int( float(gaze_position["timestamp"])/(1/fps)) 
                frame_list.append((frame_n,float(gaze_position["timestamp"])))
                print(frame_n,float(gaze_position["timestamp"]))
    
    return gaze_pos, gaze_pos_l_x, gaze_pos_r_x, gaze_pos_l_y, gaze_pos_r_y, frame_list


def processPupilTobiiG3(pupil_positions):
    """extract the pupil data from the eye traker to get standar deviation,
    mean, and filter the dataset"""

    diameter_l = []
    diameter_r = []

    simpleTimeStamps = []


    for pupil_position in pupil_positions:
 

        if ( "eyeleft" in pupil_position["data"] and "eyeright" in pupil_position["data"]):
  
            if ( "pupildiameter" in pupil_position["data"]["eyeleft"] and "pupildiameter" in pupil_position["data"]["eyeright"]):
                simpleTimeStamps.append(float(pupil_position["timestamp"]))

                diameter_l.append(float(pupil_position["data"]["eyeleft"]["pupildiameter"]))
                diameter_r.append(float(pupil_position["data"]["eyeright"]["pupildiameter"]))
        

    return diameter_l,diameter_r, simpleTimeStamps



def processPupil(pupil_positions, pupil_coulmn,
                 recStartTimeAlt, filterForConf,
                 confidence_threshold):
    """extract the pupil data from the eye traker to get standar deviation,
    mean, and filter the dataset"""

    diameters = []
    frames = []
    timeStamps = []
    simpleTimeStamps = []
    confidence = []
    confidenceThreshold = 0.1

    if filterForConf:
        confidenceThreshold = confidence_threshold

    for row in pupil_positions:
        timeStamp = float(row[0])

        if (float(row[3]) > confidenceThreshold):

            timeStamps.append(timeStamp)
            simpleTimeStamps.append(timeStamp-recStartTimeAlt)
            frames.append(int(row[1]))
            confidence.append(float(row[3]))
            diameters.append(float(row[pupil_coulmn]))

    return diameters, timeStamps, frames, simpleTimeStamps, confidence


def findClosestLuxValIterpolate(currTimeStamp, luxTimeStamps, luxValues):
    # print("currTimeStamp",currTimeStamp)

    pos = bisect_left(luxTimeStamps, currTimeStamp)
    if pos == 0:
        return luxValues[0]

    if pos == len(luxTimeStamps):
        return luxValues[-1]

    beforeLux = luxValues[pos - 1]
    afterLux = luxValues[pos]
    beforeTime = luxTimeStamps[pos - 1]
    afterTime = luxTimeStamps[pos]
    timeSpan = afterTime - beforeTime
    interLux = ((currTimeStamp - beforeTime)/timeSpan) * afterLux + ((afterTime - currTimeStamp)/timeSpan) * beforeLux
    return interLux

def nested_sum(L):
    total = 0  # don't use `sum` as a variable name
    for i in L:
        if isinstance(i, list):  # checks if `i` is a list
            total += nested_sum(i)
        else:
            total += i
    return total

def saveCsv(where, file_name, header, rows):

    with open(join(where, file_name), 'w') as csvFile:
        writer = csv.writer(csvFile)
        writer.writerow(header)

        for i in range(0, len(rows[0])):
            row = []
            for a in range(0, len(rows)):
                if isinstance(rows[a], (int, str, float)):
                    row.append(rows[a])
                else:
                    row.append(rows[a][i])
            writer.writerow(row)

    print("saveCsv done", file_name)

def upsampleLux(luxTimeStamps, luxValues, recTimeStamps, recordingInfo, shift):

    upLuxValues = []
    for sample in range(0, len(recTimeStamps)):
        timeStamp = float(recTimeStamps[sample])
        if shift:
            unixTimeStamp = float(recordingInfo["start_time_system_s"]) + (timeStamp - float(recordingInfo["start_time_synced_s"]))
        else:
            unixTimeStamp = timeStamp

        luxVal = findClosestLuxValIterpolate(unixTimeStamp, luxTimeStamps, luxValues)
        upLuxValues.append(luxVal)
    return upLuxValues

def drawDistance(plotElem, pupilValuesA, pupilValuesB, recTimeStamps, sampleLenght, pupilFiltering):
    dtw_dist = []
    dtw_time = []
    lenPupilArray = len(pupilValuesA)

    sampleNumber = int(lenPupilArray/sampleLenght)

    for sample in range(0, sampleNumber):
        sStart = int(sample * sampleLenght - 1 * sampleLenght)
        if sStart < 0:
            sStart = 0

        sEnd = int(sStart + 1 * sampleLenght)
        if sEnd >= lenPupilArray:
            sEnd = lenPupilArray - 1

        # print(sample, "of", sampleNumber)
        # print(sStart, "to", sEnd)
        # print(sStartII, "to", sEndII)

        currPupilSample = pupilValuesA[sStart: sEnd]
        currCalcSample = pupilValuesB[sStart: sEnd]

        currTime = (recTimeStamps[sStart]+recTimeStamps[sEnd])/2
        computeDtw = np.nanmean(currPupilSample, axis=0) - np.nanmean(currCalcSample)

        dtw_dist.append(computeDtw)
        dtw_time.append(currTime)

    dtw_dist = interpnan(dtw_dist)

    if pupilFiltering % 2 == 0:
        pupilFiltering = pupilFiltering+1

    # filtered set of diff diameters
    dtw_dist_smoothed = savgol_filter(np.array(dtw_dist), pupilFiltering, 1)

    dtw_WLstd = np.nanstd(dtw_dist_smoothed)
    dtw_WLvar = np.nanvar(dtw_dist_smoothed)
    dtw_WLmean = np.nanmean(dtw_dist_smoothed)

    print("Standard deviation", dtw_WLstd)
    print("Variance", dtw_WLvar)
    print("Mean", dtw_WLmean)

    plotElem.plot(dtw_time,
                  dtw_dist_smoothed,
                  marker='o',
                  markerfacecolor='blue',
                  markersize=0,
                  color='red',
                  linewidth=1,
                  label="Cognitive wl")

    plotElem.axhline(y=dtw_WLmean-dtw_WLstd,
                     color='black',
                     linestyle='-',
                     linewidth=0.3)

    plotElem.axhline(y=dtw_WLmean,
                     color='black',
                     linestyle='-',
                     linewidth=0.3)

    plotElem.axhline(y=dtw_WLmean+dtw_WLstd,
                     color='black',
                     linestyle='-',
                     linewidth=0.3)

    return dtw_dist_smoothed, dtw_time


def findClosestVal(currVal, valList):
    # find the two closest lux values (closest in the time domain) in the list

    pos = bisect_left(valList, currVal)
    if pos == 0:
        return valList[0], pos
    if pos == len(valList):
        return valList[-1], pos

    before = valList[pos - 1]
    after = valList[pos]

    if after - currVal < currVal - before:
        return after, pos
    else:
        return before, pos - 1

def findClosestsAndIterpolate(currVal, valList, toInterpList):

    pos = bisect_left(valList, currVal)
    if pos == 0:
        return toInterpList[0]

    if pos == len(valList):
        return toInterpList[-1]

    beforeInterp = toInterpList[pos - 1]
    afterInterp = toInterpList[pos]

    beforeTime = valList[pos - 1]
    afterTime = valList[pos]
    timeSpan = afterTime - beforeTime
    interp = ((currVal - beforeTime)/timeSpan) * afterInterp + ((afterTime - currVal)/timeSpan) * beforeInterp

    return interp


def findIntervalAndAverage(minVal,maxVal, valList, toInterpList):

    pos_a = bisect_left(valList, minVal)
    if pos_a == 0:
        return toInterpList[0]

    if pos_a == len(valList):
        return toInterpList[-1]

    pos_b = bisect_left(valList, maxVal)
    if pos_b == 0:
        return toInterpList[0]

    if pos_b == len(valList):
        return toInterpList[-1]

    total = 0
    n = 0

    for eachAdress in range(pos_a , pos_b+1,1):
        n = n+1
        total = total + toInterpList[eachAdress]


    average = total/n


    return average
