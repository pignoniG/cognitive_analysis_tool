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

from dateutil.parser import parse

# dependencies
import numpy as np
from scipy.signal import savgol_filter

# custom code
from pupil_code.pupil_tools.signal_tools import interpnan
from pupil_code.pupil_tools.colour_tools import linearLuminanceClac,relativeLuminanceClac ,manualRGBtoLuminanceClac

def find(name, path):
    for root, dirs, files in os.walk(path):

        for file in files:
            if name in file:
                return os.path.join(root, file)
        return False

def appendRowCsv(folder, file_name, header,rowToAdd, reorder):
    file = find( file_name,folder)

    if not file:
        print(file_name,"is missing, will be created now")
        with open(join(folder, file_name), 'w') as csvFile:
            writer = csv.writer(csvFile)
            writer.writerow(header)
            writer.writerow(rowToAdd)

    else:

        with open(file, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader)  # Remove this line if your CSV has no header
            
            unsorted_rows = []
            for row in reader:
                unsorted_rows.append(row)


            i=0
            rowWasThere=False
    
            for onerow in unsorted_rows:
                if onerow[0]==rowToAdd[0]:
                    unsorted_rows[i]=rowToAdd
                    rowWasThere=True
    
                i=i+1
    
            if not rowWasThere:
                unsorted_rows.append(rowToAdd)
    
            if reorder:
                sorted_rows = sorted(unsorted_rows, key=lambda row: row[0])
            else:
                sorted_rows = unsorted_rows



        
        with open(file, "w", newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header) # Remove this line if no header
            writer.writerows(sorted_rows)
        
        
            

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

def readEvents(data_source,recording_start):

    eventfile=find("event_log", data_source)
    info =[]
    tStamp=0
    with open(eventfile) as csvDataFile:
        for index, row in enumerate(csv.reader(csvDataFile)):


            if index > 0:
                #find offset from recording start
                if index == 1:
                    startTime = row[1] 
                    epochStartTime =  parse(startTime).timestamp()
                    tStamp= epochStartTime-recording_start
                    print(epochStartTime,recording_start,tStamp)


                start = tStamp
                end = tStamp = tStamp+float(row[3])

                # id , duration , start, end, 
                info.append((row[0],float(row[3]),start,end))
            


    return info

def readPupilVarjo(export_source):
    """read pupil_positions.csv"""
    pupil_positions = []
    with open(find("varjo_gaze_output_", export_source)) as csvDataFile:
        csvReader = csv.reader(csvDataFile)
        for index, row in enumerate(csvReader):
            if index > 0:
                pupil_positions.append(row)
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
    Epoch= []
    EstimLux= []

    with open(join(data_source, 'outputFromVideo.csv')) as csvDataFile:
        for index, row in enumerate(csv.reader(csvDataFile)):
            if index > 0:
                # indexLum,timeStampsLum,avgLum,spotLum
                indexLum.append(float(row[0]))
                timeStampsLum.append(float(row[1]))
                avgLum.append(float(row[2]))
                spotLum.append(float(row[3]))
                fieldDiameter.append(float(row[4]))
                Epoch.append(float(row[5]))
                EstimLux.append(float(row[6]))
                frame = frame+1

    return indexLum, timeStampsLum, avgLum, spotLum ,fieldDiameter,Epoch,EstimLux





def readCdm2Varjo( data_source,cameraLum_min,cameraLum_max):
       # read the camera data from the pupilCV.py script

    indexLum = []
    avgLum = []   # average "relative lumiance" of the sine
    timeStampsLum = []
    spotLum = []   # "relative lumiance" on the spot
    fieldDiameter = []   # "relative lumiance" on the spot
    frame = 0
    Epoch= []
    EstimLux= []
    R= []
    G= []
    B= []

    with open(join(data_source, 'outputFromVideo.csv')) as csvDataFile:
        for index, row in enumerate(csv.reader(csvDataFile)):
            if index > 0:
                # indexLum,timeStampsLum,avgLum,spotLum
                indexLum.append(float(row[0]))
                timeStampsLum.append(float(row[1]))
                R.append(float(row[3]))
                G.append(float(row[2]))
                B.append(float(row[4]))
                rCoeff=0.4
                gCoeff=0
                bCoeff=0.2


                pixval= manualRGBtoLuminanceClac(R[-1],G[-1], B[-1],2.2,rCoeff,gCoeff,bCoeff)
                

                avgLum.append(float(row[5]))
                #pixval= float(row[6])
                spotLum.append(pixval)
                fieldDiameter.append(float(row[7]))
                Epoch.append(float(row[8]))

                


                EstimLux.append((cameraLum_max * pixval) + (cameraLum_min * (1 - pixval)))
                frame = frame+1



    return Epoch,EstimLux



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
                  linewidth=0.1,
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

def readGazeVarjo(data_source,fps):
    """read varjo_gaze_output_"""
    gaze_positions = []
    gaze_pos = []
    gaze_pos_l_x = []
    gaze_pos_r_x = []
    gaze_pos_l_y = []
    gaze_pos_r_y = []
    frame_list = []

    with open( find("varjo_gaze_output_", data_source)) as csvDataFile:
        csvReader = csv.reader(csvDataFile)
        for index, gaze_positions in enumerate(csvReader):
            if index > 0 and int(gaze_positions[6]) > 1 and int(gaze_positions[24]) > 1 and int(gaze_positions[34]) > 1:

                gaze_pos.append(gaze_positions)
                gaze_pos_l_x.append((float(gaze_positions[25])+1)/2) 
                gaze_pos_r_x.append((float(gaze_positions[35])+1)/2) #right_projected_x
                gaze_pos_l_y.append((float(gaze_positions[26])+1)/2) 
                gaze_pos_r_y.append((float(gaze_positions[36])+1)/2) #right_projected_y
                timeStamp= float(gaze_positions[2])/10**9
                epochTimeStamp= float(gaze_positions[1])/10**9
                frame_n= int(timeStamp/(1/fps)) 
                frame_list.append((frame_n,timeStamp,epochTimeStamp))
    
    return gaze_pos, gaze_pos_l_x, gaze_pos_r_x, gaze_pos_l_y, gaze_pos_r_y, frame_list

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

def processPupilVarjo(pupil_positions):
    """extract the pupil data from the eye traker to get standar deviation,
    mean, and filter the dataset"""

    diameter_l = []
    diameter_r = []
    simpleTimeStamps = []
    timeStamps = []


    for pupil_position in pupil_positions:

          if int(pupil_position[6]) > 1 and int(pupil_position[24]) > 1 and int(pupil_position[34]) > 1 and float(pupil_position[39])>1 and float(pupil_position[39])<9:

                diameter_l.append(float(pupil_position[39])) #left_pupil_diameter_in_mm
                diameter_r.append(float(pupil_position[43])) #right_pupil_diameter_in_mm

                simpleTimeStamps.append(float(pupil_position[2])/10**9) #videotimestamp
        
                timeStamps.append(float(pupil_position[1])/10**9) #ephoctime stamp
        

    return diameter_l,diameter_r, simpleTimeStamps,timeStamps



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

def upsampleLux(luxTimeStamps, luxValues, recTimeStamps):

    upLuxValues = []
    for sample in range(0, len(recTimeStamps)):
        unixTimeStamp = float(recTimeStamps[sample])
    

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
