import cv2
import os
import csv
from os.path import join
import numpy as np
import time as t
from pupil_code.pupil_tools.magicwand import magicSelection

from pupil_code.pupil_tools.colour_tools import relativeLuminanceClac
from pupil_code.pupil_tools.data_tools import readInfo, readGaze

#####
# uses a "magic wand" approach to select th area of similar
# color/luminance around the user gaze and calculates the average
# relative luminance of that area.
#
# The "magic wand" code has been adapted from Alexander Reynolds work https://github.com/alkasm/magicwand
#
# A Python+OpenCV implementation similar to Adobe Photoshop's magic wand selection tool.
#
#####

def magicAnalysis(self):

    cv2.ocl.setUseOpenCL(True)
    self.w.analyzeVideoBar.set(0)
    self.w.analyzeVideoBar.show(True)

    data_source = self.settingsDict['recordingFolder']
    showVideo = self.settingsDict['showVideoAnalysis']

    export_source = join(data_source, "exports", "000")

    # The video resolution is automatically read from the info.csv file if available
    video_w = 1280
    video_h = 720

    # Start the video capture from file
    video_source = join(data_source, "world.mp4")

    if os.path.isfile(video_source) is False:
        print(f"Video not vound at {video_source}")
        return None

    cap = cv2.VideoCapture(video_source)
    length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    ##### read record info.csv #####
    info = readInfo(data_source)

    try:
        # this data is not always available
        video = info["World Camera Resolution"].split("x")
        video_w, video_h = int(video[0]), int(video[1])
        print("The video resolution is={video_w}x{video_h}")

    except Exception as ee:
        print("Unable to automatically read the video resolution.")
        print(ee)

    ##### read pupil_positions.csv #####
    # Unpacking the gaze data
    gaze_positions, gaze_positions_x, gaze_positions_y = readGaze(export_source)

    prev_frame_index = 0
    gaze_pix_positions = []
    gaze_frame_list_x = []
    gaze_frame_list_y = []
    gaze_frame_list_time = []

    prev_frame_x = 0
    prev_frame_y = 0

    # lets see how fast this thing can go
    start_time = t.time()
    index = -1

    # Reading all the gaze sample
    # going trough all the gaze samples

    for gaze_sample in gaze_positions:
        index = index+1

        frame_index = int(gaze_sample[1])
        frame_time = float(gaze_sample[0])

        if frame_index != prev_frame_index:

            # making sure the sample is within the frame
            gaze_frame_list_x = np.clip(gaze_frame_list_x, 0, video_w-1)
            gaze_frame_list_y = np.clip(gaze_frame_list_y, 0, video_h-1)

            gaze_pix_positions.append((frame_index, gaze_frame_list_x, gaze_frame_list_y, gaze_frame_list_time))
            gaze_frame_list_x = []
            gaze_frame_list_y = []
            gaze_frame_list_time = []

        if float(gaze_sample[2]) > 0.6:   # making sure the sample is good enough

            # scaling it to a pixel value from the normalized coordinates (0-1)
            gaze_frame_list_x.append(int(float(gaze_positions_x[index]) * video_w))
            gaze_frame_list_y.append(int((1-float(gaze_positions_y[index])) * video_h))

            # storing the previous frame to be used to replace low confidence values
            prev_frame_x = int(float(gaze_sample[3]) * video_w)
            prev_frame_i = int((1-float(gaze_sample[4])) * video_h)

        else:     # replace low confidence values
            gaze_frame_list_x.append(prev_frame_x)
            gaze_frame_list_y.append(prev_frame_y)

        gaze_frame_list_time.append(float(frame_time))
        prev_frame_index = frame_index

    ##### end read pupil_positions.csv #####

    frame_index = -1
    frame_index_alt = 0

    first_row = True

    gaze_positions_x = []
    gaze_positions_y = []

    row = ["frame_index", "time", "AVGlum", "SpotLum"]

    # Check if came=[]ra opened successfully
    if (cap.isOpened() is False):
        print("Error opening video stream or file")

    with open(join(data_source, 'outputFromVideo.csv'), 'w') as csvFile:
        writer = csv.writer(csvFile)
        if first_row:
            writer.writerow(row)
            first_row = False

        # Read until video is completed
        while(cap.isOpened()):

            # Capture frame-by-frame
            ret, frame = cap.read()
            frame_index += 1

            if ret is True:
                gaze_frame_n = gaze_pix_positions[frame_index_alt][0]

                if frame_index+1 > gaze_frame_n and frame_index_alt+2 < len(gaze_pix_positions):
                    frame_index_alt = frame_index_alt+1
                    gaze_frame_n = gaze_pix_positions[frame_index_alt][0]

                if gaze_frame_n == frame_index+1:
                    gaze_frame_n = gaze_pix_positions[frame_index_alt][0]

                    gaze_positions_x = gaze_pix_positions[frame_index_alt][1]
                    gaze_positions_y = gaze_pix_positions[frame_index_alt][2]
                    gaze_positions_time = gaze_pix_positions[frame_index_alt][3]

                    # mean and standard deviation of the rgb values
                    lumMean, lumStddev = cv2.meanStdDev(frame)

                    lum = relativeLuminanceClac(lumMean[0], lumMean[1], lumMean[2])            # mean relative luminance
                    avgStd = (float(lumStddev[0])+float(lumStddev[1])+float(lumStddev[2])) / 3  # mean sd across rgb

                    for i in range(0, len(gaze_positions_time)):
                        # for each gaze position relative to this frame
                        # frame=cv2.GaussianBlur(frame,(11,11),cv2.BORDER_DEFAULT)

                        # select the area with similar color and luminance around the gaze point within the specified tolerance

                        selection = magicSelection(frame,
                                                   gaze_positions_x[i],
                                                   gaze_positions_y[i],
                                                   avgStd*1.5,
                                                   connectivity=8)
                        stats = selection.return_stats()    # read the mean rgb of the selection

                        if showVideo:
                            selection.show()

                        R_pixval = float(stats[0])
                        G_pixval = float(stats[1])
                        B_pixval = float(stats[2])

                        pixval = relativeLuminanceClac(R_pixval, G_pixval, B_pixval)   # mean relative luminance of the selection
                        row = [frame_index, gaze_positions_time[i], float(lum), pixval]
                        writer.writerow(row)

                    # print the frame rate and persentage every 1000 frames
                    if frame_index % 100 == 0:
                        print ( round((frame_index/length)*100),"%" )
                        self.w.analyzeVideoBar.set(round((frame_index/length)*100))
 

                # Press Q on keyboard to    exit
                if showVideo:
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

            else:
                csvFile.close()
                break

    cap.release()

    # Closes all the frames
    cv2.destroyAllWindows()
