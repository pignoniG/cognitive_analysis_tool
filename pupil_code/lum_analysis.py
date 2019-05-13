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
from datetime import datetime, timedelta

# custom
from pupil_code.pupil_tools.data_tools import readInfo, readPupil, processPupil
from pupil_code.pupil_tools.data_tools import readLux, graphPlot, upsampleLux
from pupil_code.pupil_tools.data_tools import readCamera, drawDistance, saveCsv
from pupil_code.pupil_tools.signal_tools import interpnan, interpzero
from pupil_code.pupil_tools.colour_tools import calcPupil


### Functions & Procedures
def lumAnalysis(self):
    self.plot.close()
    data_source = self.settingsDict['recordingFolder']
    lux_data_source = self.settingsDict['luxFolder']
    recording_name = data_source.split("/")[-1]

    recording_source = os.path.dirname(data_source)

    # export inside the recording
    export_source = join(data_source, "exports", "000")
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

    ##### unified pupil size #####
    useCamera = self.settingsDict['useCamera']

    confidence_treshold = 0.6
    filterForConf = True

    ##### end cofig #####
    timelag = self.settingsDict['timelag']

    sampleFreq = 120
    distSampleLenght = 1*sampleFreq    # eye_frames 120fps

    pupilFiltering = int(self.settingsDict['pupilFiltering'])*2

    sampleFreqCamera = 30

    export = self.settingsDict['exportData']
    showPlot = self.settingsDict['showPlot']

    ##### read recond info #####
    pupil_coulmn = 6      # 13 in mm 6 in px
    pupil_offset = 0

    pupilData = readPupil(export_source)
    recordingInfo = readInfo(data_source)

    # get Time from the info file
    recStartTime = datetime.fromtimestamp(float(recordingInfo["Start Time (System)"]))
    recStartTimeAlt = float(recordingInfo["Start Time (Synced)"])
    bootTime = datetime.fromtimestamp(float(recordingInfo["Start Time (System)"])-recStartTimeAlt)
    timeFromBoot = recStartTime-bootTime
    recDuration = recordingInfo["Duration Time"].split(":")
    recDurationSeconds = timedelta(seconds=(int(recDuration[0])*60 + int(recDuration[1])) * 60 + int(recDuration[2]))
    recEndTime = recStartTime + recDurationSeconds

    print("Reconding started at :", recStartTime)
    print("Computer booted  at :", bootTime)
    print("It was on for :", timeFromBoot)
    print("The recording lasted :", recDuration)

    pupilValues = processPupil(pupilData,
                               pupil_coulmn,
                               recStartTimeAlt,
                               filterForConf,
                               confidence_treshold)
    recPupilValues, recTimeStamps, recFrames, recSimpleTimeStamps, recConfidence = pupilValues

    # remove nan form the pupil arrary
    recPupilValues = interpnan(recPupilValues)

    recPupilValues_filter = signal.savgol_filter(recPupilValues, 1*sampleFreq+1, 2)

    recPupilValues = signal.savgol_filter(recPupilValues, int(sampleFreq/10)+1, 6)
    recConfidence = signal.savgol_filter(recConfidence, int(sampleFreq/10)+1, 6)

    luxTimeStamps, luxValues = readLux(lux_data_source,
                                       data_source,
                                       recStartTime,
                                       recEndTime)
    luxTimeStamps = [x - timelag for x in luxTimeStamps]
    # filtered set of lux (10fps)
    luxValues = signal.savgol_filter(interpnan(luxValues), 10+1, 6)

    luxValues = upsampleLux(luxTimeStamps,
                            luxValues,
                            recTimeStamps,
                            recordingInfo,
                            True)

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
        indexLum, timeStampsLum, avgLum, spotLum = readCamera(data_source)

        avgLum = upsampleLux(timeStampsLum, avgLum, recTimeStamps, recordingInfo, False)
        spotLum = upsampleLux(timeStampsLum, spotLum, recTimeStamps, recordingInfo, False)

        scaledSpotLum = []
        for i in range(0, len(recTimeStamps)):

            sensorLux = luxValues[i]
            cameraALum = avgLum[i]
            cameraSLum = spotLum[i]

            cameraLum_min = sensorLux / (cameraALum * 10+1)
            cameraLum_max = cameraLum_min * 11

            # linear interpolation method
            scaledSpot = ((cameraLum_max * cameraSLum)+ (cameraLum_min * (1-cameraSLum)) )/2
            scaledSpotLum.append(scaledSpot)

        scaledSpotLum = signal.savgol_filter(interpnan(interpzero(scaledSpotLum)), sampleFreq*3+1, 1)

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
                      "frame_n",
                      "confidence",
                      "mm_pupil_diameter_scaled",
                      "mm_pupil_diameter_calc_lux",
                      "px_pupil_diameter_raw",
                      "recording_name",
                      "age"]

        csv_rows = [recTimeStamps,
                    recSimpleTimeStamps,
                    recFrames,
                    recConfidence,
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

        csv_header = ["distanceVal", "distanceTime", "recording_name", "age", "distanceTimeEpoch"]
        distanceTimeEpoch = [x + float(recordingInfo["Start Time (System)"]) for x in distanceTime]
        csv_rows = [distanceVal, distanceTime, recording_name, age, distanceTimeEpoch]

        saveCsv(export_source_alt, f"{recording_name}_pupilOutputDistance.csv", csv_header, csv_rows)
        saveCsv(export_source, "pupilOutputDistance.csv", csv_header, csv_rows)

    if showPlot:
        self.plot.show(block=False)
