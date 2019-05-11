from bisect import bisect_left
import os
import csv
import numpy as np
from scipy.signal import butter, lfilter, freqz,savgol_filter
#from scipy.spatial import distance
#from datetime import *
#from tslearn.metrics import *
from pupil_code.pupil_tools.signal_tools import *

def readInfo(data_source):
	# read the recording info.csv file
	info = {}
	with open(data_source+"/info.csv") as csvDataFile:
		csvReader = csv.reader(csvDataFile)
		firstLine = True
		
		for row in csvReader:
			if firstLine:
				firstLine = False
			else:
				info[row[0]] = row[1]
	return ( info )


def readPupil(export_source):
	# read pupil_positions.csv
	pupil_positions = []

	with open(export_source+"/pupil_positions.csv") as csvDataFile:
		csvReader = csv.reader(csvDataFile)
		firstLine = True
		for row in csvReader:
			if firstLine: #skip fisrstline (column declaration)
				firstLine = False
			else:
				pupil_positions.append(row)

	csvDataFile.close()	
	return(pupil_positions)

def readCamera(data_source):
	# read the camera data from the pupilCV.py script

	indexLum = []
	avgLum = [] #average "relative lumiance" of the sine 
	timeStampsLum = [] 
	spotLum = [] #"relative lumiance" on the spot
	frame = 0 

	with open(data_source+'/outputFromVideo.csv') as csvDataFile:
		csvReader = csv.reader(csvDataFile)
		firstLine = True
	
		for row in csvReader:
			if firstLine:
				firstLine = False
			else:

				#indexLum,timeStampsLum,avgLum,spotLum
				indexLum.append(float(row[0]))
				timeStampsLum.append(float(row[1]))
				avgLum.append(float(row[2]))
				spotLum.append(float(row[3]))

				frame = frame+1
	
	csvDataFile.close()	

	return(indexLum,timeStampsLum,avgLum,spotLum)

def readLux(recording_source,data_source,recStartTime,recEndTime):

	lux_data_source = data_source+"/SD_dump"
	os.path.normpath(lux_data_source)
	
	correction = 3600*2
	coeff = 0.001

	if not(os.path.isdir(lux_data_source) ):
		print("reading the pc saved lux")
		lux_data_source = recording_source+"/SD_dump"
		correction = 0
		coeff = 0.001

	##### read lux values#####
	startMonth = recStartTime.month
	startDay = recStartTime.day
	startHour = recStartTime.hour
	endHour = recEndTime.hour

	luxValues = []
	luxTimeStamps = []

	for hour in range(startHour-1 , endHour + 2):
		fileName = "/"+str(startMonth)+"_"+str(startDay)+"_"+str(hour)+".csv"

		if os.path.isfile(lux_data_source+fileName):

			with open(lux_data_source+fileName) as csvDataFile:
				csvReader = csv.reader(csvDataFile)
				#print(fileName)
		
				for row in csvReader:
					x = float(row[4])
					x = 1.706061*x + 0.66935
					y = x/2.2
					
					luxValues.append(y)
					luxTimeStamps.append((float(row[0]))*coeff-correction)
					
			csvDataFile.close()	
	return(luxTimeStamps,luxValues)
	

def graphPlot(plotElem,x , y, color, tckness,label):
	#plot, but more compact
	plotElem.plot( x, y ,marker='o', markerfacecolor=color, markersize=0, color=color, linewidth=tckness,label=label)


def readGaze(export_source):
		gaze_pos = []
		gaze_pos_x = []
		gaze_pos_y = []

		with open(export_source+"/gaze_positions.csv") as csvGazeFile:
			csvReader = csv.reader(csvGazeFile)
			firstLine = True
			
			for row in csvReader:
				if firstLine: #skip first line (column declaration)
					firstLine = False
				else:
					gaze_pos.append(row)
					gaze_pos_x.append(float(row[3]))
					gaze_pos_y.append(float(row[4]))

		csvGazeFile.close() 

		#filtering the noisy gaze x and y 
		gaze_pos_x = savgol_filter(gaze_pos_x, 120*1+1, 2)
		gaze_pos_y = savgol_filter(gaze_pos_y, 120*1+1, 2)

		return (gaze_pos, gaze_pos_x,gaze_pos_y)

def processPupil(pupil_positions,pupil_coulmn,recStartTimeAlt,filterForConf,confidence_treshold):
	# extract the pupil data from the eye traker to get standar deviation, mean, and filter the dataset
	
	diameters = []
	frames = []
	timeStamps = []
	simpleTimeStamps = []
	confidence = []
	confidenceTreshold = 0.1

	if filterForConf:
		confidenceTreshold=confidence_treshold
	
	for row in pupil_positions:

		timeStamp=float(row[0])

		
		if (float(row[3]) > confidenceTreshold):

			timeStamps.append(timeStamp)
			simpleTimeStamps.append(timeStamp-recStartTimeAlt)
			frames.append(int(row[1]))
			confidence.append(float(row[3]))
			diameters.append(float(row[pupil_coulmn]))

	return(diameters,timeStamps,frames,simpleTimeStamps,confidence)


def findClosestLuxValIterpolate(currTimeStamp , luxTimeStamps , luxValues ):
	#print("currTimeStamp",currTimeStamp)

	pos = bisect_left(luxTimeStamps, currTimeStamp)
	if pos == 0:
		return luxValues[0]

	if pos == len(luxTimeStamps):
		return luxValues[-1]
	
	beforeLux =  luxValues[pos - 1]
	afterLux =  luxValues[pos]

	beforeTime =  luxTimeStamps[pos - 1]
	afterTime =  luxTimeStamps[pos]

	timeSpan = afterTime - beforeTime

	interLux = ((currTimeStamp - beforeTime)/timeSpan) *  afterLux+ ((afterTime - currTimeStamp)/timeSpan) *beforeLux 
	
	return interLux

def nested_sum(L):
	total = 0  # don't use `sum` as a variable name
	for i in L:
		if isinstance(i, list):  # checks if `i` is a list
			total += nested_sum(i)
		else:
			total += i
	return total

def saveCsv(where,file_name,header,rows):
	first_row = True
	row = header

	with open(where+'/'+file_name, 'w') as csvFile:
		writer = csv.writer(csvFile)
		if first_row:
			writer.writerow(row)
			first_row = False
		
		for i in range(0,len(rows[0])):
	
			row = []

			for a in range(0,len(rows)):

				if isinstance(rows[a], (int , str , float )):
					row.append(rows[a])
				else:
					row.append(rows[a][i])
					
			writer.writerow(row)

	print("saveCsv done",file_name)

def upsampleLux(luxTimeStamps,luxValues,recTimeStamps,recordingInfo,shift):

	upLuxValues=[]

	for sample in range (0,len(recTimeStamps)):
		
		timeStamp = float(recTimeStamps[sample])
		if shift:
			unixTimeStamp = float(recordingInfo["Start Time (System)"]) + ( timeStamp - float(recordingInfo["Start Time (Synced)"]))
		else:
			unixTimeStamp = timeStamp 

		luxVal = findClosestLuxValIterpolate( unixTimeStamp , luxTimeStamps , luxValues )
		upLuxValues.append(luxVal)

	return(upLuxValues)
	
def drawDistance( plotElem, pupilValuesA,pupilValuesB,recTimeStamps,sampleLenght,pupilFiltering):
	dtw_dist = []
	dtw_time = []
	lenPupilArray = len(pupilValuesA)

	sampleNumber =int(lenPupilArray / sampleLenght)

	for sample in range( 0, sampleNumber ):
		sStart = int(sample * sampleLenght - 1 * sampleLenght )
		if sStart < 0 :
			sStart = 0	
		
		sEnd = int(sStart + 1 * sampleLenght )
		if sEnd >= lenPupilArray :
			sEnd = lenPupilArray -1

		#print(sample, "of", sampleNumber)
		#print(sStart, "to", sEnd)
		#print(sStartII, "to", sEndII)
		
		currPupilSample = pupilValuesA[sStart: sEnd]
		currCalcSample = pupilValuesB[sStart: sEnd]
			
		currTime = (recTimeStamps[sStart]+recTimeStamps[sEnd] )/2
		computeDtw = np.nanmean( currPupilSample, axis=0) - np.nanmean( currCalcSample)

		dtw_dist.append(computeDtw)
		dtw_time.append(currTime)		
	
	dtw_dist=interpnan (dtw_dist)

	if pupilFiltering % 2 == 0:
		pupilFiltering=pupilFiltering+1

	dtw_dist_smoothed = savgol_filter(np.array(dtw_dist), pupilFiltering, 1) # filtered set of diff dyameters
	
	dtw_WLstd = np.nanstd(dtw_dist_smoothed)
	dtw_WLvar = np.nanvar(dtw_dist_smoothed)
	dtw_WLmean = np.nanmean(dtw_dist_smoothed)
	
	print ("Standard deviation" , dtw_WLstd )
	print ("Variance" , dtw_WLvar )
	print ("Mean" , dtw_WLmean )

	plotElem.plot( dtw_time,dtw_dist_smoothed,marker='o', markerfacecolor='blue', markersize=0, color='red', linewidth=1,label="cognitive wl")
	plotElem.axhline(y=dtw_WLmean- dtw_WLstd , color='black', linestyle='-',linewidth=0.3)
	plotElem.axhline(y=dtw_WLmean  , color='black', linestyle='-',linewidth=0.3)
	plotElem.axhline(y=dtw_WLmean+ dtw_WLstd  , color='black', linestyle='-',linewidth=0.3)
	
	return dtw_dist_smoothed ,dtw_time


def findClosestVal( currVal, valList ):

	#find the two closest lux values (closest in the time domain) in the list

	pos = bisect_left(valList, currVal)
	if pos == 0:
		return valList[0],pos
	if pos == len(valList):
		return valList[-1],pos

	before = valList[pos - 1]
	after = valList[pos]

	if after - currVal < currVal - before:
	   return after,pos
	else:
	   return before,pos - 1

def findClosestsAndIterpolate( currVal , valList , toInterpList ):
	
	pos = bisect_left(valList, currVal)
	if pos == 0:
		return toInterpList[0]

	if pos == len(valList):
		return toInterpList[-1]
	
	beforeInterp =  toInterpList[pos - 1]
	afterInterp =  toInterpList[pos]

	beforeTime =  valList[pos - 1]
	afterTime =  valList[pos]
	timeSpan = afterTime - beforeTime
	interp = ((currVal - beforeTime)/timeSpan) *  afterInterp+ ((afterTime - currVal)/timeSpan) *beforeInterp 
	
	return interp