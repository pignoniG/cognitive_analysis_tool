#!/usr/bin/env python3
# coding: utf-8

# ------------ #
# Lum Analysis #
# ------------ #

### Modules
# std library
import os
from os.path import join
from collections import OrderedDict

# dependencies
import scipy.signal as signal
import numpy as np
import math

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
# custom
from pupil_code.pupil_tools.data_tools import readPupilVarjo, processPupilVarjo,readCdm2Varjo,readEvents,findIntervalAndAverage,appendRowCsv
from pupil_code.pupil_tools.data_tools import readLux, graphPlot, upsampleLux
from pupil_code.pupil_tools.data_tools import readCamera, drawDistance, saveCsv
from pupil_code.pupil_tools.signal_tools import interpnan, interpzero
from pupil_code.pupil_tools.colour_tools import calcPupil





### Functions & Procedures
def lumAnalysis(self):
    # self.plot.close()
    data_source = self.settingsDict['recordingFolder']

    recording_name = data_source.split("/")[-1]

    recording_source = os.path.dirname(data_source)
    export_source= recording_source


    # export all in a separate folder
    export_source_alt = self.settingsDict['exportFolder']

    # PlotSize
    fig, ax = self.plot.subplots(figsize=(10, 5))
    ax.set_ylim(-5, 10)

    ##### unified pupil size #####
    age = self.settingsDict['partAge']
    referenceAge = 28.58
    nOfEye = 2
    fieldAngle = 160

    eye ="both"#"right"#"both"





    ##### end cofig #####
    timelag = self.settingsDict['timelag']

    sampleFreq = 100
    distSampleLenght = sampleFreq/5    # eye_frames 120fps

    pupilFiltering = int(self.settingsDict['pupilFiltering'])*2

    sampleFreqCamera = 30

    export = self.settingsDict['exportData']
    showPlot = self.settingsDict['showPlot']

    cameraLum_min= self.settingsDict['cameraLum_min']

    cameraLum_max = self.settingsDict['cameraLum_max']

    pupilDynamics =  self.settingsDict['pupilDynamics']

    pupilCoeff =  self.settingsDict['pupilCoeff']

    


    exportWithEvents =  self.settingsDict['exportWithEvents']



    ##### read recond info #####
    pupil_offset = 0

    pupilData = readPupilVarjo(data_source)


    recEpochStartTime = float(pupilData[0][1])/ 10**9
    recEpochEndTime = float(pupilData[-1][1])/ 10**9

    print("Reconding started at :", recEpochStartTime)

    recStartTime =  datetime.fromtimestamp(recEpochStartTime)
    # get Time from the info file
    #recStartTime = datetime.fromisoformat(recordingInfo["created"][:-1])
    #recStartTime = recStartTime.replace(tzinfo=ZoneInfo('UTC'))
    #recStartTime = recStartTime.astimezone(ZoneInfo(recordingInfo["timezone"]))

    recDuration = float(recEpochEndTime-recEpochStartTime)
    recDurationSeconds = timedelta(seconds=float(recDuration))
    recEndTime = recStartTime + recDurationSeconds

    print("Reconding started at :", recStartTime)
    print("The recording lasted :", recDuration)

    pupilValues = processPupilVarjo(pupilData)

 
    recPupilValues_l, recPupilValues_r, recSimpleTimeStamps , recTimeStamps  = pupilValues

    recEpochStartTime = recStartTime.timestamp()
    recEpochTimeStamps = [x + recEpochStartTime for x in recSimpleTimeStamps]

     # remove nan form the pupil arrary
    recPupilValues_l = interpnan(recPupilValues_l)
    recPupilValues_r = interpnan(recPupilValues_r)

    recPupilValues_filter_r = signal.savgol_filter(recPupilValues_r, int(sampleFreq/2)+1, 2)
    recPupilValues_filter_l = signal.savgol_filter(recPupilValues_l, int(sampleFreq/2)+1, 2)

  
    recPupilValues_r = signal.savgol_filter(recPupilValues_r, int(sampleFreq/4)+1, 6)
    recPupilValues_l = signal.savgol_filter(recPupilValues_l, int(sampleFreq/4)+1, 6)

    luxTimeStamps, luxValues = readCdm2Varjo( data_source,cameraLum_min,cameraLum_max)




    luxTimeStamps = [x - timelag for x in luxTimeStamps]
    # filtered set of lux (10fps)
    #luxValues = signal.savgol_filter(interpnan(luxValues), 10+1, 6)

    luxValues = upsampleLux(luxTimeStamps,
                            luxValues,
                            recEpochTimeStamps)


    recPupilValues_filter_r = interpnan(recPupilValues_filter_r)
    recPupilValues_filter_l = interpnan(recPupilValues_filter_l)

    recPupilValues_r = interpnan(recPupilValues_r)
    recPupilValues_l = interpnan(recPupilValues_l)


    if eye =="right":
        recPupilValues_filter = recPupilValues_filter_r
        recPupilValues = recPupilValues_r

    elif eye =="both":
        recPupilValues_filter = []

        for i in range(len(recPupilValues_filter_r)):
            recPupilValues_filter.append((recPupilValues_filter_r[i]+recPupilValues_filter_l[i])/2)
        recPupilValues = []
        for i in range(len(recPupilValues_r)):
            recPupilValues.append((recPupilValues_r[i]+recPupilValues_l[i])/2)

    else:
        recPupilValues_filter = recPupilValues_filter_l
        recPupilValues = recPupilValues_l



    pupilValue = calcPupil(luxValues, age, referenceAge, nOfEye, fieldAngle)

   
    
    luxPupilValues = interpnan(pupilValue)
    luxPupilValues = [x for x in luxPupilValues]

    Lmin = np.min(luxPupilValues)
    Lmax = np.max(luxPupilValues)

    luxPupilValues = [(x- Lmin) /Lmax  for x in luxPupilValues]  



    fs = sampleFreq


    #Pupil ballistic correction parameters
    delay=0.5 #s
    
    first_item= luxPupilValues[0]
    for x in range(int(delay*sampleFreq)):
        luxPupilValues.insert(0, first_item)
        luxPupilValues.pop(-1)
    
    if pupilDynamics:

        
        # Attack (how fast it follows when increasing)
        attack_time = 6  # 2 ms – rise
        # Release (how fast it follows when decreasing)
        release_time = 0.5  # 200 ms –decay
    
        
        alpha_a = np.exp(-1/(fs*attack_time))
        alpha_r = np.exp(-1/(fs*release_time))
    
    
    
        y = np.zeros_like(luxPupilValues)
        
        for n in range(1, len(luxPupilValues)):
    
            if luxPupilValues[n] > y[n-1]:
           
                y[n] = alpha_a * y[n-1] + (1 - alpha_a) * luxPupilValues[n]
            else:
                y[n] = alpha_r * y[n-1] + (1 - alpha_r) * luxPupilValues[n]
    
        luxPupilValues  = y


    luxPupilValues = [x * Lmax + Lmin for x in luxPupilValues]  
 
    
    # scale pupil size 
    # Example

    #temporary fix as varjo is outputting radius instead of dyameter
    recPupilValues = [x * (1 + pupilCoeff)   for x in  recPupilValues]
    recPupilValues_filter = [x * (1 + pupilCoeff)  for x in recPupilValues_filter]



    meanRec = np.nanmean(recPupilValues, axis=0)
    meanLux = np.nanmean(luxPupilValues, axis=0)
    coeff= meanLux - meanRec
    

    recPupilValues_scaled = [x + (coeff)   for x in  recPupilValues]
    recPupilValues_filter_scaled = [x + (coeff)  for x in recPupilValues_filter]

   
    #luxPupilValues = [x - meanLux# for x in luxPupilValues]



  
    if exportWithEvents :
        eventData = readEvents(data_source,recEpochStartTime)
        #print (eventData)





    graphPlot(self.plot,
              recSimpleTimeStamps,
              luxPupilValues,
              "blue",
              0.8,
              "Sensor Calculated Pupil")

    graphPlot(self.plot,
                  recSimpleTimeStamps,
                  recPupilValues_scaled,
                  "gray",
                  0.5,
                  "Raw EyeTracker Pupil")
    graphPlot(self.plot,
                  recSimpleTimeStamps,
                  recPupilValues_filter_scaled,
                  "black",
                  0.8,
                  "Smoothed EyeTracker Pupil")


    distanceVal, distanceTime = drawDistance(self.plot,
                                                 recPupilValues_filter_scaled,
                                                 luxPupilValues,
                                                 recSimpleTimeStamps,
                                                 distSampleLenght,
                                                 pupilFiltering)
    meanDistance = np.nanmean(distanceVal, axis=0)
    ms = 0

    for i in distanceVal:
        ms = ms + (i-meanDistance)**2
    ms = ms / len(distanceVal)
    rms = math.sqrt(ms)

    print ("RMS Cognitive Workload is ",rms)


    handles, labels = self.plot.gca().get_legend_handles_labels()
    by_label = OrderedDict(zip(labels, handles))

    self.plot.legend(by_label.values(), by_label.keys())

    self.plot.xlabel('Time s')
    self.plot.ylabel('Pupil diameter mm')
    self.plot.title(f"CW{recording_name}")


    if exportWithEvents :

        eventAverageList=[]

        i=0
  
        for event in eventData:
            facecolor='white'
        
            preBuffer = 0 #dicard aprt of data toa cocunt for adaptation
            postBuffer = 0
            linewidth=0
            saveSection= False

            #if i==0 or i== len(eventData)-1:
            if event [0] in ("Riposo"):
                facecolor='teal'
                preBuffer = 10 #discard aprt of data toa cocunt for adaptation
                postBuffer = 10
                linewidth=1
                saveSection=True

            elif event [0] in ("CountB_7","Fibonacci","10_Nomi","CountB_13"):

                preBuffer = 1 #discard aprt of data toa cocunt for adaptation
                postBuffer = 1
                facecolor='darkorange'
                linewidth=1
                saveSection=True

            elif event [0] in ("Notte", "Alba", "Nuvolo"):
                facecolor='magenta'
                preBuffer = 40 #discard aprt of data toa cocunt for adaptation
                postBuffer = 0
                linewidth=1
                saveSection=True

                
            elif event [0] in ("Briefing"):
                facecolor='white'
                

            start= event [2]+preBuffer
            end = event [3]-postBuffer
    
            
            self.plot.axvspan(start, end,facecolor=facecolor, alpha=0.2)
            self.plot.axvspan(event [2], event [3],facecolor=facecolor, alpha=0.05)

            averageSection=findIntervalAndAverage(start,end, distanceTime,distanceVal)

            if saveSection:
                eventAverageList.append(averageSection)
            

            self.plot.plot([start,end], [averageSection,averageSection] ,
                marker='o',
                markerfacecolor="black",
                markersize=0,
                linestyle='-',
                color="black",
                linewidth=linewidth)


            i=i+1


   


    if showPlot:
        #self.plot.savefig(join(export_source, f'plot{recording_name}.pdf'), bbox_inches='tight')
        self.plot.savefig(join(export_source_alt, f'plot_{recording_name}.pdf'),
                          bbox_inches='tight')

    if export:
        csv_header = ["timestamp_unix",
                      "timestamp_relative",
                      "mm_pupil_diameter_scaled",
                      "mm_pupil_diameter_calc_lux",
                      "px_pupil_diameter_raw",
                      "recording_name",
                      "age"]

        csv_rows = [recEpochTimeStamps,
                    recSimpleTimeStamps,
                    recPupilValues_filter_scaled,
                    luxPupilValues,
                    recPupilValues,
                    recording_name,
                    age]


       # saveCsv(export_source, "pupilOutput.csv", csv_header, csv_rows)
        saveCsv(export_source_alt, f"{recording_name}_pupilOutput.csv", csv_header, csv_rows)

        csv_header = ["drelative_wl", "timestamp_relative", "recording_name", "age", "timestamp_unix"]
        distanceTimeEpoch = [x + float(recEpochStartTime) for x in distanceTime]
        csv_rows = [distanceVal, distanceTime, recording_name, age, distanceTimeEpoch]

        saveCsv(export_source_alt, f"{recording_name}_pupilOutputDistance.csv", csv_header, csv_rows)
       # saveCsv(export_source, "pupilOutputDistance.csv", csv_header, csv_rows)


    if exportWithEvents:
        csv_header = ["ID","R1","CountB_7","R2","Notte","Fibonacci","R3","Alba","10_Nomi","R4","Nuvolo","CountB_13","R5"]

        eventAverageList.insert(0, recording_name)

        appendRowCsv(export_source_alt, "eventsOutput.csv", csv_header, eventAverageList ,True)

    if showPlot:
        self.plot.show(block=False)
