import cv2
import os
import csv
from os.path import join
import numpy as np
import multitasking
import time as t
import math

from pupil_code.pupil_tools.magicwand import magicSelection
from pupil_code.pupil_tools.colour_tools import relativeLuminanceClac
from pupil_code.pupil_tools.data_tools import readInfo, readGaze

multitasking.set_max_threads(multitasking.config["CPU_CORES"] * 20)
    
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

@multitasking.task
def frameGrabber(g_id,src,frame_str,frame_n,gaze_pos,output_list,last_sel,showVideo):

    start = t.time()
    i=0
    #Opening a local video stream
    vid = cv2.VideoCapture(src)
    #settign the start frame
    vid.set(cv2.CAP_PROP_POS_FRAMES,frame_str)
    #wile readign frames

    while(vid.isOpened()):

        #the vid is closed when all the farem group is analised
        if i >= frame_n:
            break

        grabbed,frame = vid.read()

        #if a frame is correctly read
        if grabbed:
            #frame=cv2.GaussianBlur(frame,(11,11),cv2.BORDER_DEFAULT)
            absolute_frame_n = frame_str + i
            frameAsinc(absolute_frame_n,
                       frame,
                       gaze_pos,
                       output_list,last_sel,showVideo,g_id)
            i += 1
        else:
            break

    vid.release()

    print("Final analisis time of the frame grabber id=",g_id," is ",t.time() - start, "s")


#@multitasking.task
def subFrameAsinc(frame_n,frame,x,y,t,lum,avgStd,output_list,last_sel,showVideo,g_id):

    sel = magicSelection(frame,x,y, avgStd*1.5,connectivity=8)
    
    if showVideo:
        #save the selection output for visualisation
        last_sel [g_id]= sel.export();

    R_pixval , G_pixval , B_pixval = sel.return_stats()    # read the mean rgb of the selection
    
    pixval = relativeLuminanceClac(R_pixval, G_pixval, B_pixval)   # mean relative luminance of the selection
 
    if output_list[frame_n] is None :
        output_list[frame_n]=[]

    output_list[frame_n].append([frame_n, t, lum, pixval])


#@multitasking.task
def frameAsinc(frame_n,frame, gaze_pos, output_list,last_sel,showVideo,g_id):

    lumMean, lumStddev = cv2.meanStdDev(frame)
    lum = float(relativeLuminanceClac(lumMean[0], lumMean[1], lumMean[2]))           # mean relative luminance
    avgStd = (float(lumStddev[0])+float(lumStddev[1])+float(lumStddev[2])) / 3  # mean sd across rgb           


    if gaze_pos[frame_n]:

        for i in range(len(gaze_pos[frame_n][1])):

            x = gaze_pos[frame_n][1][i]
            y = gaze_pos[frame_n][2][i]
            t = gaze_pos[frame_n][3][i]

            subFrameAsinc(frame_n,frame,x,y,t,lum,avgStd,output_list,last_sel,showVideo,g_id)


def magicAnalysis(self):

    print("Your cpu has ",multitasking.config["CPU_CORES"]," cores" )

    cv2.ocl.setUseOpenCL(True)

    # start with an empty progress bar
    self.w.analyzeVideoBar.set(0)
    self.w.analyzeVideoBar.show(True)

    # read initial parameters from the interface

    data_source = self.settingsDict['recordingFolder']
    showVideo = self.settingsDict['showVideoAnalysis']
    export_source = join(data_source, "exports", "000")

    cv_threads = int(multitasking.config["CPU_CORES"]) * 2;
    

    #if showVideo:
        #cv_threads = int(multitasking.config["CPU_CORES"]);

    # The video resolution is automatically read from the info.csv file if available
    video_w = 1280
    video_h = 720

    # Start the video capture from file
    video_source = join(data_source, "world.mp4")
    #video_source = "/Users/giovannipignoni/Downloads/file_example_MP4_1920_18MG.mp4"

    if os.path.isfile(video_source) is False:
        print(f"Video not found at {video_source}")
        return None

    #count the frames in the video
    cap = cv2.VideoCapture(video_source)
    frames_n= int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print("frames_n=",frames_n)
    cap.release()

    ##### read record info.csv #####
    info = readInfo(data_source)

    try:
        # this data is not always available
        video = info["World Camera Resolution"].split("x")
        video_w, video_h = int(video[0]), int(video[1])
        print("The video resolution is={}x{}".format(video_w,video_h))

    except Exception as ee:
        print("Unable to automatically read the video resolution.")
        print(ee)

   ##### read pupil_positions.csv #####
    # Unpacking the gaze data
    gaze_positions, gaze_positions_x, gaze_positions_y = readGaze(export_source)

    prev_frame_index = 0

    gaze_list_max_frame= int(gaze_positions[-1][1])
    gaze_list_min_frame= int(gaze_positions[0][1])

    gaze_pix_size = frames_n

    if gaze_list_max_frame > gaze_pix_size :
        gaze_pix_size = gaze_list_max_frame

   
    gaze_pix_positions = [None]*int(gaze_pix_size+1)

    gaze_frame_list_x = []
    gaze_frame_list_y = []
    gaze_frame_list_time = []

    prev_frame_x = 0
    prev_frame_y = 0
    
    index = 0

    # Reading all the gaze sample

    for gaze_sample in gaze_positions:

        frame_index = int(gaze_sample[1])
        frame_time = float(gaze_sample[0])

        if frame_index != prev_frame_index:

            # making sure the sample is within the frame
            gaze_frame_list_x = np.clip(gaze_frame_list_x, 0, video_w-1)
            gaze_frame_list_y = np.clip(gaze_frame_list_y, 0, video_h-1)

            gaze_pix_positions[frame_index]=frame_index, gaze_frame_list_x, gaze_frame_list_y, gaze_frame_list_time

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

        index += 1

    ##### end read pupil_positions.csv #####

    #create  a list long as the video file to store the resoult of the analisis
    analised_list=[None]*int(gaze_pix_size)

    #List of the main open CV threads 
    frame_grabbers = [] 

    #Number of frames to analise
    print ("We will analise from",gaze_list_min_frame,"to", gaze_list_max_frame )

    frames_to_analise_n = gaze_list_max_frame - gaze_list_min_frame

    #Number of frames for each Open CV thread
    frame_range = int(frames_to_analise_n / cv_threads)

    #Time counter to calcualte fps
    start = t.time()

    #List to store the last frames analised (used only for visalisation)
    last_selection = [None]*int(cv_threads)

    for cv_thread in range(cv_threads):

        grabber_id = cv_thread

        first_frame = gaze_list_min_frame + (frame_range * cv_thread)




        frame_grabbers.append(frameGrabber(grabber_id,
                                           video_source,
                                           first_frame,
                                           frame_range,
                                           gaze_pix_positions,
                                           analised_list,
                                           last_selection,
                                           showVideo )) 

    #The main tread will ceck regularly if all the Open CV threads are finished
    grabbing = True
    if showVideo:
        mosaic_col_n = int(math.sqrt(cv_threads))
        mosaic_row_n = int(cv_threads/mosaic_col_n)

        scale = 1/mosaic_col_n
    
        mosaic_empty = np.zeros((video_h,video_w, 3), dtype = "uint8")
        mosaic_empty = cv2.resize( mosaic_empty,None,fx=scale,fy=scale)


    while grabbing:
        tempGrabbing=False

        for grabber in frame_grabbers:
            if (grabber.is_alive()):
                tempGrabbing=True
        grabbing=tempGrabbing


        #Count how many frames have been analised by cekking how many elements in the list have been populated
        anzl_frames = 0
        for row in analised_list:
            if row:
                anzl_frames +=1 

        fps  = int(anzl_frames /(t.time() - start));

        print("The analisis is at",round((anzl_frames/frames_to_analise_n)*100),"%","@",fps,"fps" )

        self.w.analyzeVideoBar.set(round((anzl_frames/frames_to_analise_n)*100))

        #The process can be visualised as a mosaic
        if showVideo:  
            mosaic_list = []
            mosaic_row = []  
            try:
                i=0
                for selection in last_selection:
                    selection = cv2.resize(selection,None,fx=scale,fy=scale)

                    if i < mosaic_row_n: 
                        mosaic_row.append(selection)
                        i +=1

                    else:
                        im_h = cv2.hconcat(mosaic_row)
                        mosaic_list.append(im_h)
                        mosaic_row = []
                        mosaic_row.append(selection)
                        i = 1

                if len(mosaic_row) < mosaic_row_n:
                    diff = mosaic_row_n - len(mosaic_row)
                    for a in range(diff):
                        mosaic_row.append(mosaic_empty)
        
                im_h = cv2.hconcat(mosaic_row)
                mosaic_list.append(im_h)


                cv2.imshow("Mosaic",cv2.vconcat(mosaic_list))

            except Exception as ee:
                print("No frames to show so far")
                   
            
           
        t.sleep(1)

    t.sleep(2)
    print("Final analisis time is",int(t.time() - start), "s")
    print("saving to CSV...")
    
    first_row = True
    row = ["frame_index", "time", "AVGlum", "SpotLum"]

    with open(join(data_source, 'outputFromVideo.csv'), 'w') as csvFile:
        writer = csv.writer(csvFile)
        if first_row:
            writer.writerow(row)
            first_row = False

        for frame_rows in analised_list:

            if frame_rows:
                for gaze_row in frame_rows:
                    writer.writerow(gaze_row) 

    print("saved to CSV!")


    self.w.analyzeVideoBar.set(100)

    # Closes all the frames
    cv2.destroyAllWindows()
