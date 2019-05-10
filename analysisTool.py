#!/usr/bin/env python3
# coding: utf-8

# ------------- #
# Analysis Tool #
# ------------- #

### Modules
from vanilla import Window
from defconAppKit.windows.baseWindow import BaseWindowController

### Constants

### Functions & Procedures

### Objects
class MyInterface(BaseWindowController):

    def __init__(self):
        super(BaseWindowController, self).__init__()

        self.w = Window()
        self.buildWindow()
        self.setUpBaseWindowBehavior()
        self.w.open()

    def buildWindow(self):
        pass

    def windowCloseCallback(self, sender):
        pass

    def startProgress(self, text, tickCount):
        pass


### Instructions
tool = MyInterface()
