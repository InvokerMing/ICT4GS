import torch
import cv2
import argparse
import time
import numpy as np
from ultralytics import YOLO #

def load_yolov11s_model(weights_path):
    """
    加载 YOLOv11s 模型及权重。
    """
    try:
        model = YOLO(weights_path)
        print(f"YOLOv11s model loaded successfully from {weights_path}.")
        return model
    except Exception as e:
        print(f"Error loading YOLOv11s model from {weights_path}: {e}")
        print("Please ensure you have the ultralytics library installed and the weights file is correct.")
        return None

def detect_and_count_people(model, frame):
    """
    在帧上进行检测并计数“人”的数量。
    """
    # 使用模型进行预测，输入可以是 numpy 数组
    # 设置 conf 阈值和 classes 过滤，只检测 'person'
    # results = model.predict(source=frame, conf=0.5, classes=[model.names.index('person')]) # 如果只想检测person，可以这样过滤
    # 考虑到用户可能希望看到其他检测结果，我们先获取所有结果，再过滤计数
    results = model.predict(source=frame, conf=0.5) # 设置置信度阈值

    person_count = 0
    processed_frame = frame.copy() # 复制一份帧用于绘制，不修改原始帧

    # 遍历所有检测结果
    for result in results:
        # result.boxes 包含了检测框的信息
        boxes = result.boxes
        # 遍历每个检测框
        for box in boxes:
            # 获取 bounding box 坐标 (x1, y1, x2, y2)
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            # 获取置信度
            conf = box.conf[0].cpu().numpy()
            # 获取类别 ID
            class_id = int(box.cls[0].cpu().numpy())
            # 获取类别名称
            class_name = model.names[class_id]

            # 检查是否是“人”类别且置信度高于阈值（predict 函数中已经设置了，这里可以再次确认或用于其他逻辑）
            if class_name == 'person':
                person_count += 1
                # 绘制 bounding box
                color = (0, 255, 0) # 绿色
                cv2.rectangle(processed_frame, (x1, y1), (x2, y2), color, 2)
                # 绘制类别和置信度（可选）
                label = f'{class_name}: {conf:.2f}'
                cv2.putText(processed_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            # else:
                # 如果需要显示其他类别的检测框，可以在这里添加绘制逻辑

    # 在帧上显示游客数量
    count_text = f'Tourist Count: {person_count}'
    cv2.putText(processed_frame, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2) # 红色文本

    return processed_frame, person_count

def process_input(model, source):
    """
    根据输入源处理视频流、图片或摄像头。
    使用 ultralytics 的 predict 方法直接处理不同源。
    并在显示前固定窗口宽度，高度按比例自适应。
    """
    print(f"Processing source: {source}")

    # 定义目标显示窗口宽度
    target_display_width = 640
    display_size = None # 用于存储计算出的自适应显示尺寸

    # 使用 model.predict 方法处理输入源
    # stream=True 适用于视频流和摄像头，可以更高效地处理连续帧
    # stream=False 适用于图片文件
    is_stream = source == 'camera' or source.endswith(('.mp4', '.avi', '.mov', '.mkv'))

    # 调用 predict 方法，它会根据 source 类型自动处理
    results_generator = model.predict(source=source, stream=is_stream)

    if is_stream:
        print("Processing stream. Press 'q' to exit.")
        cv2.namedWindow('Tourist Monitoring System', cv2.WINDOW_NORMAL) # 创建可调整大小的窗口

        # 从第一帧获取原始尺寸并计算自适应高度
        try:
            first_result = next(results_generator)
            original_frame = first_result.orig_img
            original_height, original_width = original_frame.shape[:2]
            aspect_ratio = original_height / original_width
            display_height = int(target_display_width * aspect_ratio)
            display_size = (target_display_width, display_height)
            cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height) # 设置窗口初始大小

            # 处理第一帧
            processed_frame, count = detect_and_count_people(model, original_frame)
            resized_frame = cv2.resize(processed_frame, display_size)
            cv2.imshow('Tourist Monitoring System', resized_frame)

        except StopIteration:
            print("No frames received from the stream.")
            return # 没有帧则直接退出

        # 继续处理剩余帧
        for result in results_generator:
            frame = result.orig_img
            processed_frame, count = detect_and_count_people(model, frame)

            # 缩放帧到目标显示大小
            resized_frame = cv2.resize(processed_frame, display_size)

            cv2.imshow('Tourist Monitoring System', resized_frame)

            # 按 'q' 键退出
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        cv2.destroyAllWindows()

    else: # 处理图片文件
        print("Processing image.")
        cv2.namedWindow('Tourist Monitoring System', cv2.WINDOW_NORMAL) # 创建可调整大小的窗口

        # 对于图片，predict 返回一个 results 列表
        results_list = list(results_generator) # Convert generator to list for single image
        if results_list:
            result = results_list[0]
            frame = result.orig_img
            original_height, original_width = frame.shape[:2]
            aspect_ratio = original_height / original_width
            display_height = int(target_display_width * aspect_ratio)
            display_size = (target_display_width, display_height)
            cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height) # 设置窗口初始大小

            processed_frame, count = detect_and_count_people(model, frame)

            # 缩放帧到目标显示大小
            resized_frame = cv2.resize(processed_frame, display_size)

            cv2.imshow('Tourist Monitoring System', resized_frame)
            # 等待按任意键关闭窗口
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            print("No results found for the image.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tourist Monitoring System using YOLOv11s.')
    parser.add_argument('--source', type=str, required=True,
                        help="Input source: 'camera' or path to video/image file.")
    parser.add_argument('--weights', type=str, default='monitor/yolov11s.pt',
                        help="Path to YOLOv11s model weights (e.g., yolov11s.pt).")

    args = parser.parse_args()

    model = load_yolov11s_model(args.weights)

    if model:
        process_input(model, args.source)
    else:
        print("Model loading failed. Exiting.")
