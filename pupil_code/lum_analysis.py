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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
# custom
from pupil_code.pupil_tools.data_tools import readInfoTobiiG3, readPupilTobiiG3, processPupilTobiiG3
from pupil_code.pupil_tools.data_tools import readLux, graphPlot, upsampleLux
from pupil_code.pupil_tools.data_tools import readCamera, drawDistance, saveCsv
from pupil_code.pupil_tools.signal_tools import interpnan, interpzero
from pupil_code.pupil_tools.colour_tools import calcPupil



### Functions & Procedures
def lumAnalysis(self):
    # self.plot.close()
    data_source = self.settingsDict['recordingFolder']
    lux_data_source = self.settingsDict['luxFolder']
    print(lux_data_source)

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
    fieldAngle = 167

    eye ="right"

    ##### unified pupil size #####
    useCamera = self.settingsDict['useCamera']

    ##### end cofig #####
    timelag = self.settingsDict['timelag']

    sampleFreq = 60
    distSampleLenght = sampleFreq/5    # eye_frames 120fps

    pupilFiltering = int(self.settingsDict['pupilFiltering'])*2

    sampleFreqCamera = 30

    export = self.settingsDict['exportData']
    showPlot = self.settingsDict['showPlot']

    ##### read recond info #####
    pupil_offset = 0

    pupilData = readPupilTobiiG3(data_source)
    recordingInfo = readInfoTobiiG3(data_source)

    
    # get Time from the info file
    recStartTime = datetime.fromisoformat(recordingInfo["created"][:-1])
    recStartTime = recStartTime.replace(tzinfo=ZoneInfo('UTC'))
    recStartTime = recStartTime.astimezone(ZoneInfo(recordingInfo["timezone"]))

    recDuration = float(recordingInfo["duration"])
    recDurationSeconds = timedelta(seconds=float(recDuration))
    recEndTime = recStartTime + recDurationSeconds

    print("Reconding started at :", recStartTime)

    print("The recording lasted :", recDuration)

    pupilValues = processPupilTobiiG3(pupilData)
 
    recPupilValues_l, recPupilValues_r, recSimpleTimeStamps = pupilValues

    recEpochStartTime = recStartTime.timestamp()
    recEpochTimeStamps = [x + recEpochStartTime for x in recSimpleTimeStamps]

     # remove nan form the pupil arrary
    recPupilValues_l = interpnan(recPupilValues_l)
    recPupilValues_r = interpnan(recPupilValues_r)

    recPupilValues_filter_r = signal.savgol_filter(recPupilValues_r, int(sampleFreq/5)+1, 2)
    recPupilValues_filter_l = signal.savgol_filter(recPupilValues_l, int(sampleFreq/5)+1, 2)

    recPupilValues_r = signal.savgol_filter(recPupilValues_r, int(sampleFreq/10)+1, 6)
    recPupilValues_l = signal.savgol_filter(recPupilValues_l, int(sampleFreq/10)+1, 6)

    luxTimeStamps, luxValues = readLux(lux_data_source,
                                       data_source,
                                       recStartTime,
                                       recEndTime)

    luxTimeStamps = [x - timelag for x in luxTimeStamps]
    # filtered set of lux (10fps)
    luxValues = signal.savgol_filter(interpnan(luxValues), 10+1, 6)

    luxValues = upsampleLux(luxTimeStamps,
                            luxValues,
                            recEpochTimeStamps,
                            recordingInfo,
                            False)


    if eye =="right":
        recPupilValues_filter = recPupilValues_filter_r
        recPupilValues = recPupilValues_r
    else:
        recPupilValues_filter = recPupilValues_filter_l
        recPupilValues = recPupilValues_l

    pupilValue = calcPupil(luxValues, age, referenceAge, nOfEye, fieldAngle)
    luxPupilValues = interpnan(pupilValue)

    meanLux = np.nanmean(luxPupilValues, axis=0)
    meanRec = np.nanmean(recPupilValues_filter, axis=0)

    stdLux = np.nanstd(luxPupilValues)
    stdRec = np.nanstd(recPupilValues_filter)

    pupil_coeff = meanLux / meanRec

    # pupil_coeff = ( meanLux-stdLux )/ (meanRec - stdRec )
    print(f"calculated pupil_coeff={pupil_coeff}")

    recPupilValues_scaled = [x * pupil_coeff for x in recPupilValues]
    recPupilValues_filter_scaled = [x * pupil_coeff for x in recPupilValues_filter]

    graphPlot(self.plot,
              recSimpleTimeStamps,
              luxPupilValues,
              "blue",
              0.8,
              "Sensor Calculated Pupil")

    if not useCamera:
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

    if useCamera:
        indexLum, timeStampsLum, avgLum, spotLum, fieldDiameters = readCamera(data_source)
        
        fieldDiameters = upsampleLux(timeStampsLum, fieldDiameters, recTimeStamps, recordingInfo, False)

        avgLum = upsampleLux(timeStampsLum, avgLum, recEpochTimeStamps, recordingInfo, False)
        spotLum = upsampleLux(timeStampsLum, spotLum, recEpochTimeStamps, recordingInfo, False)

        scaledSpotLum = []
        for i in range(0, len(recEpochTimeStamps)):

            sensorLux = luxValues[i]
            cameraALum = avgLum[i]
            cameraSLum = spotLum[i]

            #fieldDiameter = fieldDiameters[i] #unused
            #fieldAngle = 2*math.atan(fieldDiameter/2*180) #unused
            fieldAngle = 160
            

            cameraLum_min = 0
            cameraLum_max = sensorLux/cameraALum

            # linear interpolation method
            scaledSpot = (cameraLum_max * cameraSLum) + (cameraLum_min * (1 - cameraSLum))
            scaledSpotLum.append(scaledSpot)

        scaledSpotLum = signal.savgol_filter(interpnan(interpzero(scaledSpotLum)), int(sampleFreq/5)+1, 1)

        spotPupilValues = calcPupil(scaledSpotLum, age, referenceAge, nOfEye, fieldAngle)

        meanLum = np.nanmean(spotPupilValues, axis=0)
        meanRec = np.nanmean(recPupilValues_filter, axis=0)

        stdLum = np.nanstd(spotPupilValues)
        stdRec = np.nanstd(recPupilValues_filter)

        pupilLum_coeff = meanLum/meanRec

        print(f"pupilLum_coeff={pupilLum_coeff}")

        recPupilValues_filter_scaled_Lum = [x * pupilLum_coeff for x in recPupilValues_filter]

        graphPlot(self.plot,
                  recSimpleTimeStamps,
                  spotPupilValues,
                  "orange",
                  1,
                  "Camera Calculated Pupil")

        graphPlot(self.plot,
                  recSimpleTimeStamps,
                  recPupilValues_filter_scaled_Lum,
                  "black",
                  0.8,
                  "Smoothed EyeTracker Pupil")

    if useCamera:
        distanceVal, distanceTime = drawDistance(self.plot,
                                                 recPupilValues_filter_scaled_Lum,
                                                 spotPupilValues,
                                                 recSimpleTimeStamps,
                                                 distSampleLenght,
                                                 pupilFiltering)
    else:
        distanceVal, distanceTime = drawDistance(self.plot,
                                                 recPupilValues_filter_scaled,
                                                 luxPupilValues,
                                                 recSimpleTimeStamps,
                                                 distSampleLenght,
                                                 pupilFiltering)

    handles, labels = self.plot.gca().get_legend_handles_labels()
    by_label = OrderedDict(zip(labels, handles))

    self.plot.legend(by_label.values(), by_label.keys())

    self.plot.xlabel('Time s')
    self.plot.ylabel('Pupil diameter mm')
    self.plot.title(f"CW{recording_name}")
    if showPlot:
        self.plot.savefig(join(export_source, f'plot{recording_name}.pdf'),
                          bbox_inches='tight')
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

        if useCamera:
            csv_header.append("mm_pupil_diameter_calc_camera")
            csv_rows.append(spotPupilValues)

        saveCsv(export_source, "pupilOutput.csv", csv_header, csv_rows)
        saveCsv(export_source_alt, f"{recording_name}_pupilOutput.csv", csv_header, csv_rows)

        csv_header = ["drelative_wl", "timestamp_relative", "recording_name", "age", "timestamp_unix"]
        distanceTimeEpoch = [x + float(recEpochStartTime) for x in distanceTime]
        csv_rows = [distanceVal, distanceTime, recording_name, age, distanceTimeEpoch]

        saveCsv(export_source_alt, f"{recording_name}_pupilOutputDistance.csv", csv_header, csv_rows)
        saveCsv(export_source, "pupilOutputDistance.csv", csv_header, csv_rows)

    if showPlot:
        self.plot.show(block=False)
