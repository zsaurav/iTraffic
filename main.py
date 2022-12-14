from flask import Flask, render_template, Response
from flask_navigation import Navigation
import cv2
import time
import sys
import numpy as np
from scipy.spatial import distance as dist

app = Flask(__name__)

nav = Navigation(app)
nav.Bar('top', [
    nav.Item('Dashboard', 'index'),
    nav.Item('Analytics',  'analytics'),
    nav.Item('Live View',  'live_view'),
])


def build_model(is_cuda):
    net = cv2.dnn.readNet("best.onnx")
    if is_cuda:
        print("Attempty to use CUDA")
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA_FP16)
    else:
        print("Running on CPU")
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


INPUT_WIDTH = 640
INPUT_HEIGHT = 640
SCORE_THRESHOLD = 0.2
NMS_THRESHOLD = 0.4
CONFIDENCE_THRESHOLD = 0.4


def detect(image, net):
    blob = cv2.dnn.blobFromImage(image, 1 / 255.0, (INPUT_WIDTH, INPUT_HEIGHT), swapRB=True, crop=False)
    net.setInput(blob)
    preds = net.forward()
    return preds


def load_capture():
    capture = cv2.VideoCapture("vid 1.mp4")
    return capture


def load_classes():
    class_list = []
    with open("classes.txt", "r") as f:
        class_list = [cname.strip() for cname in f.readlines()]
    return class_list


class_list = load_classes()


def wrap_detection(input_image, output_data):
    class_ids = []
    confidences = []
    boxes = []

    rows = output_data.shape[0]

    image_width, image_height, _ = input_image.shape

    x_factor = image_width / INPUT_WIDTH
    y_factor = image_height / INPUT_HEIGHT

    for r in range(rows):
        row = output_data[r]
        confidence = row[4]
        if confidence >= 0.4:

            classes_scores = row[5:]
            _, _, _, max_indx = cv2.minMaxLoc(classes_scores)
            class_id = max_indx[1]
            if (classes_scores[class_id] > .25):
                confidences.append(confidence)

                class_ids.append(class_id)

                x, y, w, h = row[0].item(), row[1].item(), row[2].item(), row[3].item()
                left = int((x - 0.5 * w) * x_factor)
                top = int((y - 0.5 * h) * y_factor)
                width = int(w * x_factor)
                height = int(h * y_factor)
                box = np.array([left, top, width, height])
                boxes.append(box)

    indexes = cv2.dnn.NMSBoxes(boxes, confidences, 0.25, 0.45)

    result_class_ids = []
    result_confidences = []
    result_boxes = []

    for i in indexes:
        result_confidences.append(confidences[i])
        result_class_ids.append(class_ids[i])
        result_boxes.append(boxes[i])

    return result_class_ids, result_confidences, result_boxes


def format_yolov5(frame):
    row, col, _ = frame.shape
    _max = max(col, row)
    result = np.zeros((_max, _max, 3), np.uint8)
    result[0:row, 0:col] = frame
    return result


camera = load_capture()

colors = [(255, 255, 0), (0, 255, 0), (0, 255, 255), (255, 0, 0)]

is_cuda = len(sys.argv) > 1 and sys.argv[1] == "cuda"

net = build_model(is_cuda)
capture = load_capture()

def gen_frames():  # generate frame by frame from camera
    start = time.time_ns()
    frame_count = 0
    total_frames = 0
    fps = -1
    while True:
        _, frame = capture.read()
        if frame is None:
            print("End of stream")
            break

        inputImage = format_yolov5(frame)
        outs = detect(inputImage, net)

        class_ids, confidences, boxes = wrap_detection(inputImage, outs[0])
        distances = []
        subDistance = []
        for i in range(len(boxes)):
            subDistance.append(10000)
        for i in range(len(boxes)):
            distances.append(subDistance.copy());
        for i in range(len(boxes)):
            subDistance = []
            for k in range(len(boxes)):
                subDistance.append(10000)
            for j in range(len(boxes)):
                if i != j:
                    distances[i][j] = dist.euclidean(boxes[i], boxes[j])

        nearMiss = []
        unsafe = []
        for i in range(len(boxes)):
            nearMiss.append(0)
        for i in range(len(boxes)):
            m = min(distances[i])
            idx = distances[i].index(m)
            if m < 89:
                nearMiss[idx] = 1
            else:
                nearMiss[i] = 0

        frame_count += 1

        i = 0
        for (classid, confidence, box, j) in zip(class_ids, confidences, boxes, range(len(boxes))):
            color = colors[int(classid) % len(colors)]
            if nearMiss[j] == 1:
                color = (165, 85, 236)
            cv2.rectangle(frame, box, color, 2)
            cv2.rectangle(frame, (box[0], box[1] - 20), (box[0] + box[2], box[1]), color, -1)
            cv2.putText(frame, "{} - {}".format(class_list[classid], j), (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0))

        if frame_count >= 30:
            end = time.time_ns()
            fps = 1000000000 * frame_count / (end - start)
            frame_count = 0
            start = time.time_ns()
        incidentProb = round(sum(nearMiss) * 100 / len(nearMiss))
        accidnetProb = round(incidentProb / 10)
        if fps > 0:
            fps_label = "FPS: %.2f" % fps
            cv2.putText(frame, fps_label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(frame, "Incident Probability: {}%".format(incidentProb), (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1,
                        (0, 0, 255), 2)
            cv2.putText(frame, "Accident Probability: {}%".format(accidnetProb), (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        #cv2.imshow("output", frame)
        ret1, buffer1 = cv2.imencode('.jpg', frame)
        myFrame = buffer1.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + myFrame + b'\r\n')


@app.route('/video_feed')
def video_feed():
    # Video streaming route. Put this in the src attribute of an img tag
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    return render_template('map.html')

@app.route('/analytics')
def analytics():
    return render_template('analytics.html')

@app.route('/live-view')
def live_view():
    """Video streaming home page."""
    return render_template('index.html')


if __name__ == '__main__':
    app.run(debug=True)
