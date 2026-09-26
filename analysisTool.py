#!/usr/bin/env python3
# coding: utf-8

# ------------- #
# Analysis Tool #
# ------------- #

### Modules
# standard library
import sys
import os
from os.path import join
import pickle
import traceback

# dependencies

from PyObjCTools import AppHelper
from vanilla.dialogs import getFolder
from vanilla.test.testTools import executeVanillaTest
from vanilla import Window, PopUpButton, TextBox, Button, CheckBox,ProgressBar, EditText,ProgressSpinner
from defconAppKit.windows.baseWindow import BaseWindowController
import matplotlib.pyplot as plt

# custom code
from pupil_code.openCV_magic import magicAnalysis
from pupil_code.lum_analysis import lumAnalysis
from pupil_code.gps_plot import plotGpsCW
from pupil_code.lux_log import logLux

### Constants
MARGIN = 10

CTRL_SIZES = {
    'HorizontalLineThickness': 1,
    'VerticalLineThickness': 1,

    'ButtonRegularHeight': 20,
    'ButtonSmallHeight': 17,
    'ButtonMiniHeight': 14,

    'TextBoxRegularHeight': 25,
    'TextBoxSmallHeight': 14,
    'TextBoxMiniHeight': 12,

    'EditTextRegularHeight': 22,
    'EditTextSmallHeight': 19,
    'EditTextMiniHeight': 16,

    'CheckBoxRegularHeight': 22,
    'CheckBoxSmallHeight': 18,
    'CheckBoxMiniHeight': 10,

    'ComboBoxRegularHeight': 21,
    'ComboBoxSmallHeight': 17,
    'ComboBoxMiniHeight': 14,

    'PopUpButtonRegularHeight': 20,
    'PopUpButtonSmallHeight': 17,
    'PopUpButtonMiniHeight': 15,

    'SliderWithoutTicksRegularHeight': 15,
    'SliderWithoutTicksSmallHeight': 11,
    'SliderWithoutTicksMiniHeight': 10,

    'SliderWithTicksRegularHeight': 23,
    'SliderWithTicksSmallHeight': 17,
    'SliderWithTicksMiniHeight': 16
}

### Functions & Procedures
def saveSettings(settings):
    with open('settings.pkl', 'wb') as f:
        pickle.dump(settings, f, pickle.HIGHEST_PROTOCOL)

### Objects
class MyInterface(BaseWindowController):

    def __init__(self):
        super(BaseWindowController, self).__init__()

        # standard settings
        self.settingsDict = {'recordingFolder': False,
                             'showVideoAnalysis': False,
                             'partAge': 25,
                             'useCamera': False,
                             'timelag': 0,
                             'showPlot': True,
                             'exportData': True,
                             'pupilFiltering': 1,
                             'exportFolder': False,
                             'luxFolder': False}

        # load settings
        if os.path.isfile("settings.pkl"):
            with open('settings.pkl', 'rb') as s:
                self.settingsDict = pickle.load(s)

        self.plot = plt
        self.w = Window((600, 850), 'Cognitive Worklaod Pupil Analisis')
        self.buildWindow()
        self.updateInterface()

        self.setUpBaseWindowBehavior()
        self.w.open()

    def buildWindow(self):
        jumpingY = MARGIN

        # lux button
        self.w.aCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(a) Log the luminace data or open saved luminace data.')

        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN
        
        self.w.luxButton = Button((MARGIN, jumpingY, 160, CTRL_SIZES['CheckBoxRegularHeight']),
                                      'log the luminance',
                                      callback=self.luxButtonCallback)

        

        self.w.luxButtonCaption = TextBox((176+MARGIN*3, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']), 'Connect the external sensor first!')




        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN

        # sensor data folder
        self.w.luxFolderButton = Button((MARGIN, jumpingY, 160, CTRL_SIZES['ButtonRegularHeight']),
                                        'Luminance Folder',
                                        callback=self.luxFolderButtonCallback)

        self.w.luxFolderCaption = TextBox((160+MARGIN*2, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']), 'Select where to save/read the lumiance sensor data')
       
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight']*2 + MARGIN

        
        self.w.bCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(b) Select a recording.')
        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN

        # recording folder
        self.w.recFolderButton = Button((MARGIN, jumpingY, 120, CTRL_SIZES['ButtonRegularHeight']),
                                        'Recording Folder',
                                        callback=self.recFolderButtonCallback)

        self.w.recordingFolderCaption = TextBox((120+MARGIN*2, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                'Select a recording')

        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN

        self.w.recordingFoundCaption = TextBox((120+MARGIN*2, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']), '')

        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN

        self.w.analyzedVideoCaption = TextBox((120+MARGIN*2, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']), '')

        # export folder
        jumpingY += CTRL_SIZES['ButtonRegularHeight']*2 + MARGIN

        self.w.cCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(c) Select were to save the output (csv and pdf).')

        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN
        self.w.exportFolderButton = Button((MARGIN, jumpingY, 120, CTRL_SIZES['ButtonRegularHeight']),
                                           'Export Folder',
                                           callback=self.expFolderButtonCallback)
        self.w.exportFolderCaption = TextBox((120+MARGIN*2, jumpingY+1, 600, CTRL_SIZES['TextBoxRegularHeight']),
                                             'Select an export folder')

        jumpingY += CTRL_SIZES['ButtonRegularHeight']*2 + MARGIN

        self.w.dCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(d) Analyze the video data to compute the lumince on the gaze area (optional).')

        # analyze video
        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN

        self.w.analyzeVideoButton = Button((MARGIN, jumpingY, 140, CTRL_SIZES['ButtonRegularHeight']),
                                           'Analyze World Video',
                                           callback=self.analyzeVideoButtonCallback)
        self.w.analyzeVideoCaption = TextBox((140+MARGIN*2, jumpingY+1, 600, CTRL_SIZES['TextBoxRegularHeight']),
                                             'Process the world camera video.')

        ## show analyze video
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.showAnalizeCheck = CheckBox((MARGIN, jumpingY, 600, CTRL_SIZES['CheckBoxRegularHeight']),
                                           'Show video analysis (slow)',
                                           callback=self.showAnalizeCallback)

        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.analyzeVideoBar = ProgressBar((MARGIN, jumpingY, -10, 16), minValue=0, maxValue=100)
        self.w.analyzeVideoBar.show(False)


        jumpingY += CTRL_SIZES['ButtonRegularHeight']*1 + MARGIN

        self.w.eCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(e) Calculate the expected pupil size and workload.')
        
        # # proceed button
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.pupilSizeButton = Button((MARGIN, jumpingY, 220, CTRL_SIZES['CheckBoxRegularHeight']),
                                        'Calculate Workload',
                                        callback=self.pupilSizeButtonCallback)
        # # subject age
        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN
        self.w.ageCaption = TextBox((MARGIN, jumpingY, 120, CTRL_SIZES['TextBoxRegularHeight']), 'Subject Age:')
        self.w.agePopUp = PopUpButton((120+MARGIN*2, jumpingY, 120, CTRL_SIZES['PopUpButtonRegularHeight']),
                                      [f'{ii}' for ii in range(99)],
                                      callback=self.agePopUpCallback)

        # options
        jumpingY += CTRL_SIZES['PopUpButtonRegularHeight'] + MARGIN
        ## use camera
        self.w.useCameraCheck = CheckBox((MARGIN, jumpingY, 320, CTRL_SIZES['CheckBoxRegularHeight']),
                                         'Use world video camera data',
                                         callback=self.useCameraCheckCallback)

        ## timelag
        jumpingY += CTRL_SIZES['EditTextRegularHeight'] + MARGIN
        self.w.timeLagEditText = EditText((MARGIN, jumpingY, 100, 22), "0",
                                          callback=self.timeLagEditTextCallback)

        self.w.timeLagTextBox = TextBox((100+MARGIN*2, jumpingY, -10, 17),
                                        "Time delta (s) to sicronize sensor data with eye data")

        ## pupilFiltering
        jumpingY += CTRL_SIZES['EditTextRegularHeight'] + MARGIN
        self.w.pupilFilteringEditText = EditText((MARGIN, jumpingY, 100, 22), "0",
                                                 callback=self.pupilFilteringEditTextCallback)

        self.w.pupilFilteringTextBox = TextBox((100+MARGIN*2, jumpingY, -10, 17),
                                               "Temporal resolution of the CW data (smoothing, min 1s )")

        ## plot output
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.showPlotCheck = CheckBox((MARGIN, jumpingY, 180, CTRL_SIZES['CheckBoxRegularHeight']),
                                        'Generate/save plot',
                                        callback=self.showPlotCheckCallback)

        # ## export csv
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.exportDatasheet = CheckBox((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                          'Export to CSV',
                                          callback=self.exportDatasheetCallback)

        jumpingY += CTRL_SIZES['ButtonRegularHeight']*2 + MARGIN

        self.w.fCaption = TextBox((MARGIN, jumpingY+1, 1200, CTRL_SIZES['TextBoxRegularHeight']),
                                                '(f) Plot Workload over GPS data.')
        
        # # gps button
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.gpsButton = Button((MARGIN, jumpingY, 220, CTRL_SIZES['CheckBoxRegularHeight']),
                                  'Plot CW with GPS',
                                  callback=self.gpsButtonCallback)
        self.w.gpsCaption = TextBox((220+MARGIN*2, jumpingY+1, 600, CTRL_SIZES['TextBoxRegularHeight']),
                                  'Place "gps_track.gpx" inside the recording folder')


    def updateInterface(self):
        if self.settingsDict['recordingFolder']:

            csvPath = join(self.settingsDict['recordingFolder'], 'outputFromVideo.csv')
            if os.path.isfile(csvPath):
                self.w.analyzedVideoCaption.set("OK - World video already analyzed.")
            else:
                self.w.analyzedVideoCaption.set('! - World video data not found, analyze the video!')
                self.settingsDict['useCamera']=False

            self.w.recordingFolderCaption.set(self.settingsDict['recordingFolder'])

            pupilCsvPath = join(self.settingsDict['recordingFolder'], 'exports', '000', 'pupil_positions.csv')
            gazeCsvPath = join(self.settingsDict['recordingFolder'], 'exports', '000', 'gaze_positions.csv')
            if os.path.isfile(pupilCsvPath) and os.path.isfile(gazeCsvPath):
                self.w.recordingFoundCaption .set("OK - Valid recording found.")
            else:
                self.w.recordingFoundCaption .set('! - Not a valid recording, remember to export form PupilPlayer!')

        if self.settingsDict['exportFolder']:
            self.w.exportFolderCaption.set(self.settingsDict['exportFolder'])

        if self.settingsDict['luxFolder']:
            self.w.luxFolderCaption.set(self.settingsDict['luxFolder'])

        self.w.showAnalizeCheck.set(self.settingsDict['showVideoAnalysis'])

        self.w.showPlotCheck.set(self.settingsDict['showPlot'])

        self.w.useCameraCheck.set(self.settingsDict['useCamera'])

        self.w.exportDatasheet.set(self.settingsDict['exportData'])

        self.w.agePopUp.set(self.settingsDict['partAge'])

        self.w.timeLagEditText.set(self.settingsDict['timelag'])

        self.w.pupilFilteringEditText.set(self.settingsDict['pupilFiltering'])

    # Callbacks
    def recFolderButtonCallback(self, sender):

        self.settingsDict['recordingFolder'] = f'{getFolder()[0]}'

        self.w.recordingFolderCaption.set(self.settingsDict['recordingFolder'])
        self.updateInterface()

        sys.stdout.flush()

        # Callbacks
    def luxFolderButtonCallback(self, sender):
        
        self.settingsDict['luxFolder'] = f'{getFolder()[0]}'

        self.w.luxFolderCaption.set(self.settingsDict['luxFolder'])
        self.updateInterface()

        sys.stdout.flush()
        

    def expFolderButtonCallback(self, sender):

        self.settingsDict['exportFolder'] = f'{getFolder()[0]}'
        self.w.exportFolderCaption.set(self.settingsDict['exportFolder'])
        self.updateInterface()

        sys.stdout.flush()

    def analyzeVideoButtonCallback(self, sender):

        self.w.analyzeVideoBar.show(True)
        try:
            magicAnalysis(self)
        except Exception as e:
            print(e)
            print ("Exception in user code:")
            print ('-'*60)
            traceback.print_exc(file = sys.stdout)
            print ('-'*60)
        
        self.updateInterface() 
        sys.stdout.flush()

    def showAnalizeCallback(self, sender):
        self.settingsDict['showVideoAnalysis'] = sender.get()
        self.updateInterface()
        sys.stdout.flush()

    def timeLagEditTextCallback(self, sender):
        self.settingsDict['timelag'] = float(sender.get())
        sys.stdout.flush()

    def pupilFilteringEditTextCallback(self, sender):
        self.settingsDict['pupilFiltering'] = float(sender.get())
        sys.stdout.flush()

    def agePopUpCallback(self, sender):
        self.settingsDict['partAge'] = sender.get()
        print('agePopUpCallback')
        sys.stdout.flush()

    def useCameraCheckCallback(self, sender):
        self.settingsDict['useCamera'] = sender.get()
        sys.stdout.flush()

    def showPlotCheckCallback(self, sender):
        self.settingsDict['showPlot'] = sender.get()
        sys.stdout.flush()


    def exportDatasheetCallback(self, sender):
        self.settingsDict['exportData'] = sender.get()
        sys.stdout.flush()

    def pupilSizeButtonCallback(self, sender):
        try:
            lumAnalysis(self)
        except Exception as e:
            print(e)

            print("Exception in user code:")
            print('-'*60)
            traceback.print_exc(file=sys.stdout)
            print('-'*60)
        sys.stdout.flush()

    def gpsButtonCallback(self, sender):
        try:
            plotGpsCW(self)
        except Exception as e:
            print(e)

            print("Exception in user code:")
            print('-'*60)
            traceback.print_exc(file=sys.stdout)
            print('-'*60)
        sys.stdout.flush()

    def windowCloseCallback(self, sender):
        print('windowCloseCallback')
        print(self.settingsDict)
        saveSettings(self.settingsDict)
        sys.stdout.flush()

        

    def luxButtonCallback(self, sender):
        try:

            logLux(self)
        except Exception as e: 
            print(e)

            print ("Exception in user code:")
            print ('-'*60)
            traceback.print_exc(file = sys.stdout)
            print ('-'*60)
        sys.stdout.flush()


if __name__ == "__main__":
    executeVanillaTest(MyInterface)
