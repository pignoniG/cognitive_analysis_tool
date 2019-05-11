
#import csv

import scipy.signal as signal
import numpy as np
from datetime import *
from pupil_code.pupil_tools.data_tools import *
from pupil_code.pupil_tools.colour_tools import *
from pupil_code.pupil_tools.signal_tools import *
#import scipy.fftpack
from collections import OrderedDict
#from scipy.signal import freqz

import os

##### cofig #####

##### define the recordings folder

def lumAnalysis(self):
    self.plotDist.close()
    data_source=self.settingsDict['recordingFolder'] 
    recording_name=data_source.split("/")[-1]

    recording_source=os.path.dirname(data_source)

    #export inside the recording
    export_source=data_source+"/exports/000"
    #export all in a separate folder
    export_source_alt=self.settingsDict['exportFolder'] 

    #PlotSize
    fig, ax = self.plotDist.subplots(figsize=(10,5))
    ax.set_ylim(-5, 10)
    
    
    ##### unified pupil size #####
    
    age = self.settingsDict['partAge'] 
    referenceAge = 28.58 
    nOfEye = 2
    fieldAngle = 167
    
    ##### unified pupil size #####

    useCamera = self.settingsDict['useCamera'] 

    confidence_treshold = 0.6
    filterForConf = True
    
    ##### end cofig #####
    
    timelag = self.settingsDict['timelag'] 

    sampleFreq = 120
    distSampleLenght = 1*sampleFreq#(eye_frames 120fps)

    pupilFiltering = int( self.settingsDict['pupilFiltering'])*2


    
    sampleFreqCamera = 30
 
    export = self.settingsDict['exportData'] 
    showPlot= self.settingsDict['showPlot'] 
    

    ##### read recond info #####

    pupil_coulmn = 6 # 13 in mm 6 in px
    pupil_offset = 0
    
    
    pupilData = readPupil(export_source)
    recordingInfo = readInfo(data_source)
    
    #get Time from the info file
    
    recStartTime = datetime.fromtimestamp(float(recordingInfo["Start Time (System)"]))
    recStartTimeAlt = float(recordingInfo["Start Time (Synced)"])
    bootTime = datetime.fromtimestamp(float(recordingInfo["Start Time (System)"])-recStartTimeAlt)
    timeFromBoot= recStartTime-bootTime
    recDuration = recordingInfo["Duration Time"].split(":")
    recDurationSeconds = timedelta( seconds= ( int(recDuration[0])* 60 + int(recDuration[1])) * 60 + int(recDuration[2]))
    recEndTime = recStartTime + recDurationSeconds

    print ("Reconding started at :", recStartTime )
    print ("Computer booted  at :", bootTime )
    print ("It was on for :" , timeFromBoot )
    print ("The recording lasted :" , recDuration )
    
    
    
    recPupilValues,recTimeStamps,recFrames,recSimpleTimeStamps,recConfidence = processPupil(pupilData,pupil_coulmn,recStartTimeAlt,filterForConf,confidence_treshold)
    
    recPupilValues = interpnan(recPupilValues)#remove nan form the pupil arrary
    
    recPupilValues_filter = signal.savgol_filter(recPupilValues, 1*sampleFreq+1, 2)
    
    recPupilValues = signal.savgol_filter(recPupilValues, int(sampleFreq/10)+1, 6)
    recConfidence = signal.savgol_filter(recConfidence, int(sampleFreq/10)+1, 6)

    
    luxTimeStamps,luxValues = readLux(recording_source,data_source,recStartTime,recEndTime)
    luxTimeStamps=[x - timelag for x in luxTimeStamps]
    luxValues = signal.savgol_filter(interpnan(luxValues), 10+1, 6) # filtered set of lux (10fps)
    
    luxValues = upsampleLux(luxTimeStamps,luxValues,recTimeStamps,recordingInfo,True)
        
    luxPupilValues = interpnan(calcPupil(luxValues,age,referenceAge,nOfEye,fieldAngle))
    
    meanLux = np.nanmean(luxPupilValues, axis=0)
    meanRec = np.nanmean(recPupilValues_filter, axis=0)
    
    stdLux = np.nanstd(luxPupilValues)
    stdRec = np.nanstd(recPupilValues_filter)
        
    pupil_coeff = meanLux / meanRec
    
    #pupil_coeff = ( meanLux-stdLux )/ (meanRec - stdRec ) 
    print("calculated pupil_coeff=",pupil_coeff )
    
        
    
    recPupilValues_scaled = [x * pupil_coeff  for x in recPupilValues]

    
    recPupilValues_filter_scaled = [x * pupil_coeff  for x in recPupilValues_filter]

    graphPlot(self.plotDist , recSimpleTimeStamps,luxPupilValues ,"blue",0.8,"Sensor Calculated Pupil")
    
    if not useCamera:
        
        graphPlot(self.plotDist , recSimpleTimeStamps,recPupilValues_scaled,"gray",0.5,"Raw EyeTracker Pupil")
        graphPlot(self.plotDist , recSimpleTimeStamps,recPupilValues_filter_scaled,"black",0.8,"Smoothed EyeTracker Pupil")
    
    
    if useCamera:
        indexLum , timeStampsLum , avgLum , spotLum  = readCamera(data_source)
        
        avgLum = upsampleLux(timeStampsLum , avgLum , recTimeStamps , recordingInfo , False)
        spotLum = upsampleLux(timeStampsLum , spotLum , recTimeStamps , recordingInfo , False)
    
        scaledSpotLum=[]
        for i in range(0,len(recTimeStamps)):
    
            sensorLux = luxValues[i]
            cameraALum= avgLum[i] 
            cameraSLum= spotLum[i]
    
            cameraLum_min= sensorLux / (cameraALum *10+1)
            cameraLum_max= cameraLum_min * 11 

            scaledSpot = ((cameraLum_max * cameraSLum)+ (cameraLum_min * (1-cameraSLum)) )/2 # linear interpolation method
            scaledSpotLum.append(scaledSpot)
    
        scaledSpotLum = signal.savgol_filter(interpnan(interpzero(scaledSpotLum )), sampleFreq*3+1  , 1)
    
        spotPupilValues = calcPupil(scaledSpotLum,age,referenceAge,nOfEye,fieldAngle )
    
        meanLum = np.nanmean(spotPupilValues, axis=0)
        meanRec = np.nanmean(recPupilValues_filter, axis=0)
    
        stdLum = np.nanstd(spotPupilValues)
        stdRec = np.nanstd(recPupilValues_filter)

        pupilLum_coeff = meanLum/meanRec

        print("pupilLum_coeff=",pupilLum_coeff )


        recPupilValues_filter_scaled_Lum = [x * pupilLum_coeff for x in recPupilValues_filter]
    
        graphPlot(self.plotDist , recSimpleTimeStamps,spotPupilValues,"orange",1,"Camera Calculated Pupil")
    
        graphPlot(self.plotDist , recSimpleTimeStamps,recPupilValues_filter_scaled_Lum,"black",0.8,"Smoothed EyeTracker Pupil")
    
    
    if useCamera:
        distanceVal , distanceTime = drawDistance(self.plotDist, recPupilValues_filter_scaled_Lum, spotPupilValues, recSimpleTimeStamps, distSampleLenght, pupilFiltering)
    else:
        distanceVal , distanceTime = drawDistance(self.plotDist, recPupilValues_filter_scaled, luxPupilValues, recSimpleTimeStamps, distSampleLenght, pupilFiltering)
    


    handles, labels = self.plotDist.gca().get_legend_handles_labels()
    by_label = OrderedDict(zip(labels, handles))
    self.plotDist.legend(by_label.values(), by_label.keys())
    
    self.plotDist.xlabel('Time s')
    self.plotDist.ylabel('Pupil diameter mm')
    self.plotDist.title("CW"+ recording_name)
    if showPlot:
        self.plotDist.savefig(export_source+'/plot'+recording_name+'.pdf', bbox_inches='tight')
        self.plotDist.savefig(export_source_alt+'/plot_'+recording_name+'.pdf', bbox_inches='tight')
    
    if export:
        csv_header = ["timestamp_unix","timestamp_relative","frame_n","confidence","mm_pupil_diameter_scaled","mm_pupil_diameter_calc_lux","px_pupil_diameter_raw","recording_name","age"]
        csv_rows   = [recTimeStamps,recSimpleTimeStamps,recFrames,recConfidence,recPupilValues_filter_scaled,luxPupilValues,recPupilValues,recording_name,age]
    
        if useCamera:
            csv_header.append("mm_pupil_diameter_calc_camera")
            csv_rows.append(spotPupilValues)

        saveCsv(export_source,"pupilOutput.csv",csv_header,csv_rows)
        saveCsv(export_source_alt,recording_name+"_pupilOutput.csv",csv_header,csv_rows)
    
        csv_header = ["distanceVal","distanceTime","recording_name","age","distanceTimeEpoch"]
        distanceTimeEpoch= [x +float(recordingInfo["Start Time (System)"]) for x in distanceTime ]
        csv_rows   = [distanceVal,distanceTime,recording_name,age,distanceTimeEpoch]
    
        saveCsv(export_source_alt,recording_name+"_pupilOutputDistance.csv",csv_header,csv_rows)
        saveCsv(export_source,"pupilOutputDistance.csv",csv_header,csv_rows)
        
    if showPlot:
            self.plotDist.show()
    
    
    
    
    
    
    