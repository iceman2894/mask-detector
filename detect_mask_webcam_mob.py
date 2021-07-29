from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing.image import img_to_array
from tensorflow.keras.models import load_model
from imutils.video import VideoStream
import numpy as np
import argparse
import imutils
import time
import cv2
import os
import RPi.GPIO as GPIO
from time import sleep
from threading import Thread

# Pins in GPIO.BOARD
# ready = 8
# faceRead = 5    # yellow
# maskOn = 7      # green
# maskOff = 3     # red

# Pins in GPIO.BCM
ready = 14
faceRead = 3    # yellow
maskOn = 4      # green
maskOff = 2     # red

# Pins for Motor Driver Inputs in GPIO.BCM
Motor1A = 24
Motor1B = 23
Motor1E = 25

# GPIO Setup
GPIO.setmode(GPIO.BCM)

#setup
GPIO.setup(ready, GPIO.OUT)
GPIO.setup(faceRead, GPIO.OUT)
GPIO.setup(maskOn, GPIO.OUT)
GPIO.setup(maskOff, GPIO.OUT)
# ------------------------------
GPIO.setup(Motor1A, GPIO.OUT)   # All pins as Outputs
GPIO.setup(Motor1B, GPIO.OUT)
GPIO.setup(Motor1E, GPIO.OUT)

# startup output
GPIO.output(faceRead, GPIO.LOW)
GPIO.output(maskOn, GPIO.LOW)
GPIO.output(maskOff, GPIO.LOW)
# ------------------------------
GPIO.output(Motor1A, GPIO.LOW)
GPIO.output(Motor1B, GPIO.LOW)
GPIO.output(Motor1E, GPIO.LOW)

#readyLEDStatus = 0
doorIsOpen = 0          # 0: Closed, 1: Open

def doorControl(open, faceDetected):
    global doorIsOpen
    if open and not doorIsOpen:

        print('Door opening\n')
        # Going forwards
        GPIO.output(Motor1A, GPIO.HIGH)
        GPIO.output(Motor1B, GPIO.LOW)
        GPIO.output(Motor1E, GPIO.HIGH)
        sleep(3)
        print('Opened\n')
        GPIO.output(Motor1E, GPIO.LOW)
        doorIsOpen = 1

    elif not open and doorIsOpen:
        if(not faceDetected):
            sleep(4)  # delay in closing until person passes inside
        print('Door closing\n')
        GPIO.output(Motor1A, GPIO.LOW)
        GPIO.output(Motor1B, GPIO.HIGH)
        GPIO.output(Motor1E, GPIO.HIGH)
        sleep(3)
        print('Closed\n')
        GPIO.output(Motor1E, GPIO.LOW)
        doorIsOpen = 0
    return
    
    
# toggle function for read LED
def toggleReadLed():
    while True:
        GPIO.output(ready, GPIO.HIGH)
        sleep(1)
        GPIO.output(ready, GPIO.LOW)
        sleep(1)
    # blink led
        
def detect_and_predict_mask(frame, faceNet, maskNet):
    # grab the dimensions of the frame and then construct a blob
    # from it
    (h, w) = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300),
                                 (104.0, 177.0, 123.0))

    # pass the blob through the network and obtain the face detections
    faceNet.setInput(blob)
    detections = faceNet.forward()

    # initialize our list of faces, their corresponding locations,
    # and the list of predictions from our face mask network
    faces = []
    locs = []
    preds = []

    # loop over the detections
    for i in range(0, detections.shape[2]):
        # extract the confidence (i.e., probability) associated with
        # the detection
        confidence = detections[0, 0, i, 2]

        # filter out weak detections by ensuring the confidence is
        # greater than the minimum confidence
        if confidence > args["confidence"]:
            # compute the (x, y)-coordinates of the bounding box for
            # the object
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            (startX, startY, endX, endY) = box.astype("int")

            # ensure the bounding boxes fall within the dimensions of
            # the frame
            #(startX, startY) = (max(0, startX), max(0, startY))
            #(endX, endY) = (min(w - 1, endX), min(h - 1, endY))

            # extract the face ROI, convert it from BGR to RGB channel
            # ordering, resize it to 224x224, and preprocess it
            face = frame[startY:endY, startX:endX]
            try:
                face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
            except:
                continue
                pass
            face = cv2.resize(face, (224, 224))
            face = img_to_array(face)
            face = preprocess_input(face)

            # add the face and bounding boxes to their respective
            # lists
            faces.append(face)
            locs.append((startX, startY, endX, endY))

    # only make a predictions if at least one face was detected
    if len(faces) > 0:
        # for faster inference we'll make batch predictions on *all*
        # faces at the same time rather than one-by-one predictions
        # in the above `for` loop
        GPIO.output(faceRead, GPIO.HIGH)
        # GPIO.output(maskOn, GPIO.LOW)
        # GPIO.output(maskOff, GPIO.LOW)

        faces = np.array(faces, dtype="float32")
        preds = maskNet.predict(faces, batch_size=32)
    else:
        GPIO.output(faceRead, GPIO.LOW)
        GPIO.output(maskOn, GPIO.LOW)
        GPIO.output(maskOff, GPIO.LOW)

        # check if door is open
        if doorIsOpen:
            doorControl(0, 0)  # close the door
            
    # return a 2-tuple of the face locations and their corresponding
    # locations
    return (locs, preds)



# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-f", "--face", type=str,
                default="face_detector",
                help="path to face detector model directory")
ap.add_argument("-m", "--model", type=str,
                default="mask_detector.model",
                help="path to trained face mask detector model")
ap.add_argument("-c", "--confidence", type=float, default=0.5,
                help="minimum probability to filter weak detections")
args = vars(ap.parse_args())

# load our serialized face detector model from disk
print("[INFO] loading face detector model...")
prototxtPath = os.path.sep.join([args["face"], "deploy.prototxt"])
weightsPath = os.path.sep.join([args["face"],
                                "res10_300x300_ssd_iter_140000.caffemodel"])
faceNet = cv2.dnn.readNet(prototxtPath, weightsPath)

# load the face mask detector model from disk
print("[INFO] loading face mask detector model...")
maskNet = load_model(args["model"])

# initialize the video stream and allow the camera sensor to warm up
print("[INFO] starting video stream...")
vs = VideoStream(src=0).start()
time.sleep(2.0)

# blink ready LED
th = Thread(target=toggleReadLed)
th.start()

# loop over the frames from the video stream
while True:

    # grab the frame from the threaded video stream and resize it
    # to have a maximum width of 400 pixels
    frame = vs.read()
    frame = imutils.resize(frame, width=400)

    # detect faces in the frame and determine if they are wearing a
    # face mask or not
    (locs, preds) = detect_and_predict_mask(frame, faceNet, maskNet)

    # loop over the detected face locations and their corresponding
    # locations
    allHaveMask = -1
    for (box, pred) in zip(locs, preds):
        # unpack the bounding box and predictions
        (startX, startY, endX, endY) = box
        (mask, withoutMask) = pred

        # Parsing predicted percentage
        label = "Mask" if mask > withoutMask else "No Mask"
        # color = (0, 255, 0) if label == "Mask" else (0, 0, 255)
        if(label == "Mask"):
            color = (0, 255, 0)
            GPIO.output(faceRead, GPIO.LOW)
            GPIO.output(maskOn, GPIO.HIGH)
            GPIO.output(maskOff, GPIO.LOW)
            if(allHaveMask != 0):
                allHaveMask = 1
        else:
            color = (0, 0, 255)
            GPIO.output(faceRead, GPIO.LOW)
            GPIO.output(maskOff, GPIO.HIGH)
            GPIO.output(maskOn, GPIO.LOW)
            allHaveMask = 0


        # include the probability in the label
        label = "{}: {:.2f}%".format(label, max(mask, withoutMask) * 100)

        # display the label and bounding box rectangle on the output
        # frame
        cv2.putText(frame, label, (startX - 50, startY - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        #cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)

    # Door Control
    doorControl(allHaveMask == 1, allHaveMask != -1)
    # show the output frame
    #try:
    #    cv2.imshow("Face Mask Detector", frame)
    #    key = cv2.waitKey(1) & 0xFF
        # if the `q` key was pressed, break from the loop
    #    if key == ord("q"):
    #        break
    #except cv2.error as error:
    #    pass
        #print("[Error]: {}".format(error))

    
    #sleep(0.001)
    

# cleanup
GPIO.cleanup()
cv2.destroyAllWindows()
vs.stop()