import cv2
import argparse
import time
import numpy as np
from ultralytics import YOLO
import math


class CentroidTracker:
    def __init__(self, maxDisappeared=50):
        # Initialize next available object ID
        self.nextObjectID = 0
        # Store currently tracked objects: key=object_id, value=centroid coordinates
        self.objects = {}
        # Store disappeared frames count: key=object_id, value=number of frames disappeared
        self.disappeared = {}
        # Store latest bounding box for each object: key=object_id, value=box coordinates
        self.object_boxes = {}
        # Maximum consecutive frames an object is allowed to be marked as "disappeared"
        self.maxDisappeared = maxDisappeared

    def register(self, centroid, box):
        # Register a new object using the next available object ID
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.object_boxes[self.nextObjectID] = box
        self.nextObjectID += 1

    def deregister(self, objectID):
        # Deregister an object ID by deleting it from all dictionaries
        del self.objects[objectID]
        del self.disappeared[objectID]
        del self.object_boxes[objectID]

    def update(self, detections):
        # Check if there are any detections in the current frame
        if len(detections) == 0:
            # Mark all existing tracked objects as disappeared
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1

                # Deregister object if it has disappeared for too long
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)

            return self.objects, self.object_boxes

        # Initialize arrays for current frame detections
        inputCentroids = np.zeros((len(detections), 2), dtype="int")
        inputBoxes = []

        # Process each detection in the current frame
        for (i, (startX, startY, endX, endY)) in enumerate(detections):
            # Calculate centroid of bounding box
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            inputCentroids[i] = (cX, cY)
            inputBoxes.append((startX, startY, endX, endY))

        # Register all detections if no objects are being tracked
        if len(self.objects) == 0:
            for i in range(0, len(inputCentroids)):
                self.register(inputCentroids[i], inputBoxes[i])

        # Match existing objects with new detections
        else:
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())

            # Calculate Euclidean distances between existing objects and new detections
            D = np.zeros((len(objectCentroids), len(inputCentroids)))
            for i in range(len(objectCentroids)):
                for j in range(len(inputCentroids)):
                    D[i, j] = math.dist(objectCentroids[i], inputCentroids[j])

            # Perform greedy matching based on minimum distances
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            # Track used rows and columns for matching
            usedRows = set()
            usedCols = set()

            # Update matched objects
            for (row, col) in zip(rows, cols):
                if row in usedRows or col in usedCols:
                    continue

                objectID = objectIDs[row]
                self.objects[objectID] = inputCentroids[col]
                self.object_boxes[objectID] = inputBoxes[col]
                self.disappeared[objectID] = 0

                usedRows.add(row)
                usedCols.add(col)

            # Handle unmatched existing objects
            unusedRows = set(range(0, D.shape[0])).difference(usedRows)
            for row in unusedRows:
                objectID = objectIDs[row]
                self.disappeared[objectID] += 1

                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)

            # Register new detections that weren't matched
            unusedCols = set(range(0, D.shape[1])).difference(usedCols)
            for col in unusedCols:
                self.register(inputCentroids[col], inputBoxes[col])

        return self.objects, self.object_boxes


def load_yolov11s_model(weights_path, device):
    """
    Load YOLOv11s model and weights on specified device.
    Returns the loaded model or None if loading fails.
    """
    try:
        model = YOLO(weights_path)
        model.to(device)
        print(f"YOLOv11s model loaded successfully on device: {device}.")
        return model
    except Exception as e:
        print(f"Error loading YOLOv11s model from {weights_path} on device {device}: {e}")
        print("Please ensure you have the ultralytics library installed, the weights file is correct,")
        print("and your specified device is available and configured correctly (e.g., CUDA for GPU).")
        return None


def process_input(model, source):
    """
    Process video stream, image, or camera input using the model.
    Handles object detection, tracking, and visualization.
    """
    print(f"Processing source: {source}")

    target_display_width = 800
    display_size = None

    # Determine if input is a stream (camera or video)
    is_stream = False
    try:
        source_int = int(source)
        is_stream = True
    except ValueError:
        if source.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
            is_stream = True

    tracker = CentroidTracker(maxDisappeared=30)
    results_generator = model.predict(source=source, stream=is_stream)

    cv2.namedWindow('Tourist Monitoring System', cv2.WINDOW_NORMAL)

    if is_stream:
        print("Processing stream. Press 'q' to exit.")
        window_size_set = False
        results_iterator = iter(results_generator)

        while True:
            try:
                result = next(results_iterator)
                frame = result.orig_img

                # Set window size on first frame
                if not window_size_set:
                    original_height, original_width = frame.shape[:2]
                    aspect_ratio = original_height / original_width
                    display_height = int(target_display_width * aspect_ratio)
                    display_size = (target_display_width, display_height)
                    cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height)
                    window_size_set = True

                processed_frame = frame.copy()

                # Extract person detections
                person_detections = []
                for box in result.boxes:
                    class_id = int(box.cls[0].cpu().numpy())
                    class_name = model.names[class_id]
                    conf = box.conf[0].cpu().numpy()

                    if class_name == 'person' and conf > 0.5:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        person_detections.append((x1, y1, x2, y2))

                # Update tracker and draw tracked objects
                tracked_objects, tracked_boxes = tracker.update(person_detections)

                for objectID in tracked_objects.keys():
                    box = tracked_boxes[objectID]
                    color = (0, 255, 0)
                    cv2.rectangle(processed_frame, (box[0], box[1]), (box[2], box[3]), color, 2)
                    text = f'ID: {objectID}'
                    cv2.putText(processed_frame, text, (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                # Display total tourist count
                total_tourists = tracker.nextObjectID
                count_text = f'Total Tourists Detected: {total_tourists}'
                cv2.putText(processed_frame, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                resized_frame = cv2.resize(processed_frame, display_size)
                cv2.imshow('Tourist Monitoring System', resized_frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            except StopIteration:
                print("End of stream.")
                break
            except Exception as e:
                print(f"Error processing frame: {e}")
                break

        cv2.destroyAllWindows()

    else:
        # Process single image
        print("Processing image.")
        results_generator = model.predict(source=source, stream=is_stream)
        results_list = list(results_generator)

        if results_list:
            result = results_list[0]
            frame = result.orig_img
            original_height, original_width = frame.shape[:2]
            aspect_ratio = original_height / original_width
            display_height = int(target_display_width * aspect_ratio)
            display_size = (target_display_width, display_height)

            cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height)
            processed_frame = frame.copy()

            # Detect and count people in image
            person_count = 0
            for box in result.boxes:
                class_id = int(box.cls[0].cpu().numpy())
                class_name = model.names[class_id]
                conf = box.conf[0].cpu().numpy()

                if class_name == 'person' and conf > 0.5:
                    person_count += 1
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    color = (0, 255, 0)
                    cv2.rectangle(processed_frame, (x1, y1), (x2, y2), color, 2)
                    label = f'{class_name}: {conf:.2f}'
                    cv2.putText(processed_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            count_text = f'Tourists in Frame: {person_count}'
            cv2.putText(processed_frame, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            resized_frame = cv2.resize(processed_frame, display_size)
            cv2.imshow('Tourist Monitoring System', resized_frame)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            print("No results found for the image.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tourist Monitoring System using YOLOv11s.')
    parser.add_argument('--source', type=str, required=True,
                        help="Input source: '0' for camera, or path to video/image file.")
    parser.add_argument('--weights', type=str, default='monitor/yolov11s.pt',
                        help="Path to YOLOv11s model weights (e.g., yolov11s.pt).")
    parser.add_argument('--device', type=str, default='cuda',
                        help="Device to run inference on (e.g., 'cpu', 'cuda', 'cuda:0').")

    args = parser.parse_args()
    model = load_yolov11s_model(args.weights, args.device)

    if model:
        process_input(model, args.source)
    else:
        print("Model loading failed. Exiting.")
