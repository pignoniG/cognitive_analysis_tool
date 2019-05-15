#!/usr/bin/env python3
# coding: utf-8

# ---------- #
# Magic Wand #
# ---------- #

### Modules
# standard library
from collections import namedtuple

# dependecies
import cv2
import numpy as np

### Constants
Point = namedtuple('Point', 'x, y')

### Functions & Procedures
class magicSelection:
    """adapted from Alexander Reynolds work https://github.com/alkasm/magicwand
       A Python+OpenCV implementation similar to Adobe Photoshop's magic wand selection tool."""

    def __init__(self, image, xI, yI, tolerance, connectivity=4):
        # general params
        self.name = "window"
        self._seed_point = Point(xI, yI)
        self._image = image
        self._h, self._w = image.shape[:2]
        if len(image.shape) == 3:
            self._channels = 3
        else:
            self._channels = 1
        self._selection = image.copy()
        self._mask = 255*np.ones((self._h, self._w), dtype=np.uint8)

        # parameters for floodfill
        self.connectivity = connectivity
        self._tolerance = (tolerance,)*3

        self._flood_mask = np.zeros((self._h+2, self._w+2), dtype=np.uint8)
        self._magicwand()

    def _magicwand(self):
        self._flood_mask[:] = 0
        flags = self.connectivity | 255 << 8   # bit shift
        flags |= cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY
        flood_image = self._image.copy()
        cv2.floodFill(flood_image, self._flood_mask, self._seed_point, 0,
                      self._tolerance, self._tolerance, flags)
        self._mask = self._flood_mask[1:-1, 1:-1].copy()
        # self._mask=cv2.GaussianBlur( self._mask,(11,11),cv2.BORDER_DEFAULT)

    def show(self):
        self._applied_mask = cv2.bitwise_and(
            self._image, self._image, mask=self._mask)

        cv2.circle(self._applied_mask,
                   (self._seed_point[0], self._seed_point[1]),
                   10, (127, 127, 127), -1)
        cv2.imshow(self.name, self._applied_mask)

    def return_stats(self):
        # return(self.mean,self.stddev,self.min,self.max)
        return(self.mean)

    @property
    def mask(self):
        return self._mask

    @property
    def applied_mask(self):
        self._applied_mask = cv2.bitwise_and(
            self._image, self._image, mask=self._mask)
        return self._applied_mask

    @property
    def selection(self):
        self._drawselection()
        return self._selection

    @property
    def contours(self):
        self._drawselection()
        return self._contours

    @property
    def seedpt(self):
        return self._seed_point

    @property
    def mean(self):
        stddev, mean = 0, 0
        mean = cv2.meanStdDev(self._image, mean, stddev, self._mask)[0]
        if self._channels == 1:
            return mean[0, 0]
        return mean[:, 0]

    @property
    def stddev(self):
        stddev, mean = 0, 0

        stddev = cv2.meanStdDev(self._image, mean, stddev, self._mask)[1]
        if self._channels == 1:
            return stddev[0, 0]
        return stddev[:, 0]

    @property
    def min(self):
        if self._channels == 1:
            return cv2.minMaxLoc(self._image, self._mask)[0]
        min_val = [cv2.minMaxLoc(self._image[:, :, i], self._mask)[0]
                   for i in range(3)]
        return np.array(min_val, dtype=np.uint8)

    @property
    def max(self):
        if self._channels == 1:
            return cv2.minMaxLoc(self._image, self._mask)[1]
        max_val = [cv2.minMaxLoc(self._image[:, :, i], self._mask)[1]
                   for i in range(3)]
        return np.array(max_val, dtype=np.uint8)
