#!/usr/bin/env python3
# coding: utf-8

# -------- #
# GPS Plot #
# -------- #

### Modules
# standard library
import colorsys
import time as tm
import csv
import calendar
import xml.dom.minidom as mnd
import urllib
import io
from os.path import join
from math import radians, log, tan, cos, pi, atan, sinh, degrees, sqrt, sin

# dependencies
import matplotlib.cm as cm
cmap = cm.jet
from PIL import Image
import numpy as np
from adjustText import adjust_text

# custom code
from pupil_code.pupil_tools.data_tools import *
from pupil_code.pupil_tools.colour_tools import *
from pupil_code.pupil_tools.signal_tools import *

### Constants

### Functions & Procedures

### Variables

### Instructions

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = radians(lat_deg)
    n = 2 ** zoom
    xtile = int((lon_deg + 180.0) / 360 * n)
    ytile = int((1 - log(tan(lat_rad) + (1 / cos(lat_rad))) / pi) / 2 * n)
    return (xtile, ytile)

def num2deg(xtile, ytile, zoom):
    n = 2 ** zoom
    lon_deg = xtile / n * 360 - 180
    lat_rad = atan(sinh(pi * (1 - 2 * ytile / n)))
    lat_deg = degrees(lat_rad)
    return (lat_deg, lon_deg)

def getImageCluster(lat_deg, lon_deg, delta_lat, delta_long):
    zoom = int(0.2/(delta_lat*delta_long))

    print("zoom", zoom)

    smurl = r"http://a.tile.openstreetmap.org/{0}/{1}/{2}.png"
    xmin, ymax = deg2num(lat_deg, lon_deg, zoom)
    xmax, ymin = deg2num(lat_deg + delta_lat, lon_deg + delta_long, zoom)

    lat_max, lon_max = num2deg(xmin, ymax+1, zoom)
    lat_min, lon_min = num2deg(xmax+1, ymin, zoom)

    Cluster = Image.new('RGB', ((xmax-xmin+1)*256-1, (ymax-ymin+1)*256-1))

    for xtile in range(xmin, xmax+1):
        for ytile in range(ymin, ymax+1):
            try:
                imgurl = smurl.format(zoom, xtile, ytile)
                print(f"Opening: {imgurl}")
                imgstr = urllib.request.urlopen(imgurl).read()
                tile = Image.open(io.BytesIO(imgstr))
                Cluster.paste(tile, box=((xtile-xmin)*256, (ytile-ymin)*255))
            except Exception as error:
                print(error)
                print("Couldn't download image")
                tile = None

    print(lat_max, lon_min, lat_min, lon_max)
    print("lat_max", "lon_min", "lat_min", "lon_max")

    return Cluster, lat_max, lon_min, lat_min, lon_max


def plotGpsCW(self):

    self.plotGps.close()

    SMALL_SIZE = 16
    MEDIUM_SIZE = 20
    BIGGER_SIZE = 24

    self.plotGps.rc('font', size=SMALL_SIZE)          # controls default text sizes
    self.plotGps.rc('axes', titlesize=SMALL_SIZE)     # fontsize of the axes title
    self.plotGps.rc('axes', labelsize=MEDIUM_SIZE)    # fontsize of the x and y labels
    self.plotGps.rc('xtick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
    self.plotGps.rc('ytick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
    self.plotGps.rc('legend', fontsize=SMALL_SIZE)    # legend fontsize
    self.plotGps.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title

    data_source = self.settingsDict['recordingFolder']
    recording_name = data_source.split("/")[-1]

    # export inside the recording
    export_source = join(data_source, "exports", "000")

    # export all in a separate folder
    export_source_alt = self.settingsDict['exportFolder']
    data = open(join(data_source, 'gps_track.gpx'))

    # READ GPX FILE

    xmldoc = mnd.parse(data)
    track = xmldoc.getElementsByTagName('trkpt')
    elevation = xmldoc.getElementsByTagName('ele')
    datetime = xmldoc.getElementsByTagName('time')
    n_track = len(track)

    first_row = True
    # Read distance
    distanceVal = []
    rawDistanceVal = []

    # Read distance
    distanceTime = []
    rawDistanceTime = []

    with open(join(export_source, "pupilOutputDistance.csv")) as csvDataFile:
        csvReader = csv.reader(csvDataFile)
        for row in csvReader:
            if first_row:
                first_row = False
            else:
                rawDistanceVal.append(float(row[0]))
                rawDistanceTime.append(float(row[4]))
        csvDataFile.close()

    for i in range(int((rawDistanceTime[-1]-rawDistanceTime[0])/5)):
        time_r = rawDistanceTime[0]+i*5
        val = findClosestsAndIterpolate(time_r, rawDistanceTime, rawDistanceVal)
        distanceVal.append(val)
        distanceTime.append(time_r)

    # PARSING GPX ELEMENT
    lon_list = []
    lat_list = []
    h_list = []
    time_list = []
    epoch_list = []

    for s in range(n_track):
        lon, lat = track[s].attributes['lon'].value, track[s].attributes['lat'].value
        elev = elevation[s].firstChild.nodeValue
        lon_list.append(float(lon))
        lat_list.append(float(lat))
        h_list.append(float(elev))
        # PARSING TIME ELEMENT
        dt = datetime[s].firstChild.nodeValue

        time_split = dt.split('T')
        hms_split = time_split[1].split(':')
        time_hour = int(hms_split[0])
        time_minute = int(hms_split[1])
        time_second = int(hms_split[2].split('Z')[0])
        # 'Jul 9, 2009 @ 20:02:58 UTC'
        time_secondEph = calendar.timegm(tm.strptime(dt, '%Y-%m-%dT%H:%M:%SZ'))

        total_second = time_hour*3600+time_minute*60+time_second
        time_list.append(total_second)
        epoch_list.append(int(time_secondEph))

    # GEODETIC TO CARTERSIAN FUNCTION
    def geo2cart(lon, lat, h):
        a = 6378137        # WGS84 Major axis
        b = 6356752.3142   # WGS84 Minor axis
        e2 = 1-(b**2/a**2)
        N = float(a/sqrt(1-e2*(sin(radians(abs(lat)))**2)))
        X = (N+h)*cos(radians(lat))*cos(radians(lon))
        Y = (N+h)*cos(radians(lat))*sin(radians(lon))
        return X, Y

    # DISTANCE FUNCTION
    def distance(x1, y1, x2, y2):
        d = sqrt((x1-x2)**2+(y1-y2)**2)
        return d

    # SPEED FUNCTION
    def speed(x0, y0, x1, y1, t0, t1):
        d = sqrt((x0-x1)**2+(y0-y1)**2)
        delta_t = t1-t0
        if delta_t == 0:
            delta_t = 0.001
        s = float(d/delta_t)
        return s

    # POPULATE DISTANCE AND SPEED LIST
    d_list = [0.0]
    speed_list = [0.0]
    l = 0
    for k in range(n_track-1):
        if k < (n_track-1):
            l = k+1
        else:
            l = k
        XY0 = geo2cart(lon_list[k], lat_list[k], h_list[k])
        XY1 = geo2cart(lon_list[l], lat_list[l], h_list[l])

        # DISTANCE
        d = distance(XY0[0], XY0[1], XY1[0], XY1[1])
        sum_d = d+d_list[-1]
        d_list.append(sum_d)

        # SPEED
        s = speed(XY0[0], XY0[1], XY1[0], XY1[1], time_list[k], time_list[l])
        speed_list.append(s)

    # PLOT TRACK
    # f,(track,speed,elevation)=self.plotGps.subplots(3,1)
    f, (track) = self.plotGps.subplots(1, 1, figsize=(6, 11))
    # f.set_figheight(8)
    # f.set_figwidth(2)

    lonMax = max(lon_list)
    lonMin = min(lon_list)
    lonDelta = lonMax-lonMin
    latMax = max(lat_list)
    latMin = min(lat_list)
    latDelta = latMax-latMin

    a, lat_max, lon_min, lat_min, lon_max = getImageCluster(latMin, lonMin, latDelta, lonDelta)
    # fig = track.figure()
    # fig.patch.set_facecolor('white')
    track.imshow(np.asarray(a), zorder=0, extent=[lon_max, lon_min, lat_max, lat_min])
    track.set_xlim((lon_max, lon_min))
    track.set_ylim((lat_max, lat_min))

    # self.plotGps.subplots_adjust(hspace=0.5)
    track.set_aspect(2)
    # img = self.plotGps.imread("/Users/giovanni/Desktop/AAA_filed_test/map_n.jpg")
    # track.imshow(img, zorder=0, extent=[5.1272, 5.2515, 60.2750, 60.4057])
    track.plot(lon_list, lat_list, 'k')
    track.set_ylabel("Latitude")
    track.set_xlabel("Longitude")
    track.set_title(f"{recording_name} Track Plot")

    # track.set_aspect(2.1663)
    # PLOT SPEED
    # speed.bar(d_list,speed_list,30,color='w',edgecolor='w')
    # speed.set_title("Speed")
    # speed.set_xlabel("Distance(m)")
    # speed.set_ylabel("Speed(m/s)")

    # PLOT ELEVATION PROFILE
    # elevation.fill_between(d_list,h_list,base_reg,alpha=0.1)
    # elevation.set_title("Elevation Profile")
    # elevation.set_xlabel("Distance(m)")
    # elevation.set_ylabel("GPS Elevation(m)")
    # elevation.grid()
    # ANIMATION/DYNAMIC PLOT

    distanceVal_std = np.nanstd(distanceVal)
    for i in range(len(distanceTime)-1):
        lon_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lat_list)

        track.plot(lon_closestValue, lat_closestValue, marker='o',
                   markersize=8, mfc=(1, 1, 1, 1), mec=(1, 1, 1, 0.0))

    for i in range(len(distanceTime)-1):
        lon_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(distanceTime[i], epoch_list, lat_list)
        curr_distanceVal = distanceVal[i]
        c = (curr_distanceVal + distanceVal_std*1.5) / (distanceVal_std*1.5)*2
        # c = (distanceVal[i] - distanceVal_min) /(distanceVal_var)

        if c < 0:
            c = 0
        if c > 1:
            c = 1

        c = 0.4-c*0.4
        c = colorsys.hsv_to_rgb(c, 1, 1)
        r = c[0]
        g = c[1]
        b = c[2]

        track.plot(lon_closestValue, lat_closestValue, marker='o',
                   markersize=8.1, mfc=(r, g, b, 0.6), mec=(0, 0, 0, 0.0))

    texts = []
    prevDist = 0
    for i in range(int((distanceTime[-1]-distanceTime[0])/60)):
        time = int(distanceTime[0])+i*60
        time_s = i

        lon_closestValue = findClosestsAndIterpolate(time, epoch_list, lon_list)
        lat_closestValue = findClosestsAndIterpolate(time, epoch_list, lat_list)
        distance_closestValue = findClosestsAndIterpolate(time, epoch_list, d_list)

        if distance_closestValue - prevDist > 200:
            prevDist = distance_closestValue
            track.plot(lon_closestValue,
                       lat_closestValue,
                       marker='.',
                       markersize=3,
                       mfc=(0, 0, 0, 0),
                       mec=(0, 0, 0, 0.5))
            texts.append(track.text(lon_closestValue+0.001, lat_closestValue+0.001, f"{time_s} min", fontsize=8))

    adjust_text(texts, only_move={'texts': 'x'})
    self.plotGps.savefig(f'{export_source_alt}/plot{recording_name}.pdf',
                         bbox_inches='tight')
    self.plotGps.show()
