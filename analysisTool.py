#!/usr/bin/env python3
# coding: utf-8

# ------------- #
# Analysis Tool #
# ------------- #

### Modules
from vanilla import Window, PopUpButton, TextBox, Button, CheckBox
from defconAppKit.windows.baseWindow import BaseWindowController

### Constants
MARGIN = 10

CTRL_SIZES = {
    'HorizontalLineThickness': 1,
    'VerticalLineThickness': 1,

    'ButtonRegularHeight': 20,
    'ButtonSmallHeight': 17,
    'ButtonMiniHeight': 14,

    'TextBoxRegularHeight': 17,
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

### Objects
class MyInterface(BaseWindowController):

    def __init__(self):
        super(BaseWindowController, self).__init__()

        self.w = Window((300, 400), 'Driver')
        self.buildWindow()

        self.setUpBaseWindowBehavior()
        self.w.open()

    def buildWindow(self):
        jumpingY = MARGIN

        # recording folder
        self.w.recFolderButton = Button((MARGIN, jumpingY, 120, CTRL_SIZES['ButtonRegularHeight']),
                                        'Recording Folder',
                                        callback=self.recFolderButtonCallback)
        self.w.recordingFolderCaption = TextBox((120+MARGIN*2, jumpingY+1, 120, CTRL_SIZES['TextBoxRegularHeight']), 'some path!')

        # # subject age
        jumpingY += CTRL_SIZES['ButtonRegularHeight'] + MARGIN
        self.w.ageCaption = TextBox((MARGIN, jumpingY, 120, CTRL_SIZES['TextBoxRegularHeight']), 'Subject Age:')
        self.w.agePopUp = PopUpButton((120+MARGIN*2, jumpingY, 120, CTRL_SIZES['PopUpButtonRegularHeight']),
                                      [f'{ii}' for ii in range(99)],
                                      callback=self.agePopUpCallback)

        # options
        jumpingY += CTRL_SIZES['PopUpButtonRegularHeight'] + MARGIN
        ## use camera
        self.w.useCameraCheck = CheckBox((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                         'Use camera',
                                         callback=self.useCameraCheckCallback)
        ## plot output
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.plotOutputCheck = CheckBox((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                          'Plot Output',
                                          callback=self.plotOutputCheckCallback)
        # ## export pdf
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.exportPdfCheck = CheckBox((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                         'Export PDF',
                                         callback=self.exportPdfCheckCallback)
        # ## export csv
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.exportCsvCheck = CheckBox((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                         'Export CSV',
                                         callback=self.exportCsvCheckCallback)

        # # proceed button
        jumpingY += CTRL_SIZES['CheckBoxRegularHeight'] + MARGIN
        self.w.proceedButton = Button((MARGIN, jumpingY, 120, CTRL_SIZES['CheckBoxRegularHeight']),
                                      'Proceed!',
                                      callback=self.proceedButtonCallback)

    # Callbacks
    def recFolderButtonCallback(self, sender):
        print('recFolderButtonCallback')

    def agePopUpCallback(self, sender):
        print('agePopUpCallback')

    def useCameraCheckCallback(self, sender):
        print('useCameraCheckCallback')

    def plotOutputCheckCallback(self, sender):
        print('plotOutputCheckCallback')

    def exportPdfCheckCallback(self, sender):
        print('exportPdfCheckCallback')

    def exportCsvCheckCallback(self, sender):
        print('exportCsvCheckCallback')

    def proceedButtonCallback(self, sender):
        print('proceedButtonCallback')

    def windowCloseCallback(self, sender):
        print('windowCloseCallback')

    def startProgress(self, text, tickCount):
        print('startProgress')


### Instructions
tool = MyInterface()
