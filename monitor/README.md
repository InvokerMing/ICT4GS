# Tourist Monitoring System

A real-time tourist detection and tracking system using YOLOv11s object detection model for Information and Communication Technologies for the Global South (ICT4GS).

## System Purpose

This system is designed to monitor and count tourists at attraction sites. The intended deployment scenario is to position a camera at one side of a ticket checkpoint entrance. As tourists pass through the entrance after ticket verification, the system detects and counts each individual, adding them to the total tourist count.

## Features

- Real-time person detection using YOLOv11s
- Object tracking with centroid-based tracker
- Total tourist count display
- Support for camera input, video files, and image files
- Visualization of detection results

## Requirements

- Python 3.8+
- CUDA-compatible GPU (recommended) or CPU
- Dependencies listed in `requirements.txt`

## Installation

1. Navigate to the backend directory:
   ```
   cd monitor
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Ensure the YOLOv11s model weights (`yolov11s.pt`) are in the monitor directory.

## Usage

### Process a video file:
```
python main.py --source path/to/video.mp4 --weights monitor/yolov11s.pt --device cuda
```

### Use webcam:
```
python main.py --source 0 --weights monitor/yolov11s.pt --device cuda
```

### Process a single image:
```
python main.py --source path/to/image.jpg --weights monitor/yolov11s.pt --device cuda
```

### Options:
- `--source`: Input source (camera index, video file, or image file), mandatory
- `--weights`: Path to YOLOv11s model weights, optional
- `--device`: Device to run inference on ('cpu', 'cuda', 'cuda:0', etc.), optional

## Controls
- Press 'q' to exit when processing video or webcam feed
- Press any key to exit when processing an image

## System Architecture

The system consists of:
1. YOLOv11s model for object detection
2. CentroidTracker for maintaining object IDs across frames
3. Visualization component for displaying results 