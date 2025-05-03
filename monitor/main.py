import cv2
import argparse
import time
import numpy as np
from ultralytics import YOLO
import math


class CentroidTracker:
    def __init__(self, maxDisappeared=50):
        # 初始化下一个可用的对象 ID
        self.nextObjectID = 0
        # 存储当前正在被跟踪的对象：键是对象 ID，值是对象的中心点坐标 (centroid)
        self.objects = {}
        # 存储每个对象“消失”的帧数：键是对象 ID，值是消失的帧数
        self.disappeared = {}
        # 存储每个对象对应的最新 bounding box
        self.object_boxes = {}

        # 在 deregister 一个对象之前，允许它连续“消失”的最大帧数
        self.maxDisappeared = maxDisappeared

    def register(self, centroid, box):
        # 使用下一个可用的对象 ID 注册一个新的对象
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.object_boxes[self.nextObjectID] = box
        self.nextObjectID += 1

    def deregister(self, objectID):
        # 要 deregister 一个对象 ID，我们只需要从所有字典中删除它
        del self.objects[objectID]
        del self.disappeared[objectID]
        del self.object_boxes[objectID]

    def update(self, detections):
        # 检查当前帧中是否有任何检测
        if len(detections) == 0:
            # 如果没有检测，增加所有现有跟踪对象的消失计数
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1

                # 如果对象消失的帧数超过了最大允许值，则 deregister 它
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)

            # 返回更新后的跟踪对象列表和它们的 bounding boxes
            # 返回的 boxes 对应的是 tracker 中存储的最新 box
            return self.objects, self.object_boxes

        # 初始化当前帧检测到的对象的中心点列表和 bounding boxes 列表
        inputCentroids = np.zeros((len(detections), 2), dtype="int")
        inputBoxes = []

        # 遍历当前帧的检测
        for (i, (startX, startY, endX, endY)) in enumerate(detections):
            # 计算 bounding box 的中心点
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            inputCentroids[i] = (cX, cY)
            inputBoxes.append((startX, startY, endX, endY))

        # 如果当前没有正在跟踪的对象，则注册所有新的输入检测
        if len(self.objects) == 0:
            for i in range(0, len(inputCentroids)):
                self.register(inputCentroids[i], inputBoxes[i])

        # 否则，当前有正在跟踪的对象，我们需要尝试将现有的跟踪对象与新的输入检测进行匹配
        else:
            # 获取现有跟踪对象的 ID 和中心点
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())

            # 计算每个现有对象中心点与每个新的输入检测中心点之间的距离
            # D 是一个矩阵，其中 D[i, j] 是第 i 个现有对象与第 j 个输入检测之间的欧几里得距离
            D = np.zeros((len(objectCentroids), len(inputCentroids)))
            for i in range(len(objectCentroids)):
                for j in range(len(inputCentroids)):
                    # 使用欧几里得距离
                    D[i, j] = math.dist(objectCentroids[i], inputCentroids[j])

            # 执行贪婪匹配，找到距离最小的匹配对
            # 在这个简单的实现中，我们使用 argmin 找到每行的最小距离索引
            # 然后处理这些匹配，确保每个输入检测最多匹配一个现有对象
            # 找到每行的最小距离，并按这些最小距离对行（现有对象）进行排序
            rows = D.min(axis=1).argsort()
            # 获取排序后的行对应的最小距离的列（输入检测）索引
            cols = D.argmin(axis=1)[rows]

            # 用于记录已经匹配的现有对象和输入检测的索引
            usedRows = set()
            usedCols = set()

            # 遍历排序后的匹配对
            for (row, col) in zip(rows, cols):
                # 如果当前行（现有对象）或列（输入检测）已经被使用，则跳过
                if row in usedRows or col in usedCols:
                    continue

                # 否则，这是一个有效的匹配
                # 将这个输入检测的中心点和 bounding box 更新到对应的现有对象上
                objectID = objectIDs[row]
                self.objects[objectID] = inputCentroids[col]
                self.object_boxes[objectID] = inputBoxes[col]
                self.disappeared[objectID] = 0 # 重置消失计数

                # 标记当前行和列为已使用
                usedRows.add(row)
                usedCols.add(col)

            # 处理未匹配的现有对象（行）
            # 获取所有现有对象索引，减去已使用的行索引，得到未使用的行索引
            unusedRows = set(range(0, D.shape[0])).difference(usedRows)
            for row in unusedRows:
                objectID = objectIDs[row]
                self.disappeared[objectID] += 1 # 增加消失计数

                # 如果对象消失的帧数超过了最大允许值，则 deregister 它
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)

            # 处理未匹配的新的输入检测（列）
            # 获取所有输入检测索引，减去已使用的列索引，得到未使用的列索引
            unusedCols = set(range(0, D.shape[1])).difference(usedCols)
            for col in unusedCols:
                # 注册新的对象
                self.register(inputCentroids[col], inputBoxes[col])

        # 返回更新后的跟踪对象列表和它们的 bounding boxes
        return self.objects, self.object_boxes


def load_yolov11s_model(weights_path, device):
    """
    加载 YOLOv11s 模型及权重，并指定设备。
    """
    try:
        # 使用 ultralytics.YOLO 加载模型，并通过 device 参数指定设备
        model = YOLO(weights_path)
        # 将模型发送到指定设备
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
    根据输入源处理视频流、图片或摄像头。
    使用 ultralytics 的 predict 方法直接处理不同源。
    并在显示前固定窗口宽度，高度按比例自适应，同时进行跟踪和编号。
    """
    print(f"Processing source: {source}")

    # 定义目标显示窗口宽度
    target_display_width = 800
    display_size = None # 用于存储计算出的自适应显示尺寸

    # 判断是否是流输入 (摄像头或视频文件)
    is_stream = False
    try:
        # 尝试将 source 转换为整数，如果是，则认为是摄像头
        source_int = int(source)
        is_stream = True
    except ValueError:
        # 如果不是整数，检查是否是视频文件扩展名
        if source.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
            is_stream = True
        # 其他情况认为是图片文件

    tracker = CentroidTracker(maxDisappeared=30)
    results_generator = model.predict(source=source, stream=is_stream)

    cv2.namedWindow('Tourist Monitoring System', cv2.WINDOW_NORMAL) # 创建可调整大小的窗口

    if is_stream:
        print("Processing stream. Press 'q' to exit.")

        # 标志，用于确定是否已设置窗口尺寸
        window_size_set = False

        # 使用 iter() 确保可以遍历生成器
        results_iterator = iter(results_generator)

        while True:
            try:
                # 获取下一帧的预测结果
                result = next(results_iterator)
                frame = result.orig_img # 获取原始帧 (numpy array)

                if not window_size_set:
                    # 仅在第一次获取帧时计算并设置窗口尺寸
                    original_height, original_width = frame.shape[:2]
                    aspect_ratio = original_height / original_width
                    display_height = int(target_display_width * aspect_ratio)
                    display_size = (target_display_width, display_height)
                    cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height)
                    window_size_set = True # 标记为已设置

                processed_frame = frame.copy() # 复制一份帧用于绘制

                # 提取当前帧中“人”的 bounding boxes
                person_detections = []
                # 遍历所有检测结果
                for box in result.boxes:
                     # 获取类别名称
                    class_id = int(box.cls[0].cpu().numpy())
                    class_name = model.names[class_id]
                    conf = box.conf[0].cpu().numpy()

                    # 检查是否是“人”类别且置信度高于阈值
                    if class_name == 'person' and conf > 0.5: # 使用与 predict 中相同的阈值
                         # 获取 bounding box 坐标 (x1, y1, x2, y2)
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        person_detections.append((x1, y1, x2, y2))


                # 更新跟踪器并获取跟踪到的对象及其 ID
                tracked_objects, tracked_boxes = tracker.update(person_detections)

                # 在帧上绘制跟踪到的对象和它们的 ID
                # person_count = len(tracked_objects) # 跟踪到的对象数量即为人数
                for objectID in tracked_objects.keys():
                    box = tracked_boxes[objectID]
                    # 绘制 bounding box
                    color = (0, 255, 0) # 绿色
                    cv2.rectangle(processed_frame, (box[0], box[1]), (box[2], box[3]), color, 2)
                    # 绘制对象 ID
                    text = f'ID: {objectID}'
                    cv2.putText(processed_frame, text, (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                # 在帧上显示游客总数 (跟踪器分配的最大 ID)
                # tracker.nextObjectID 是下一个将被分配的 ID，代表总共检测到的唯一对象数量
                total_tourists = tracker.nextObjectID
                count_text = f'Total Tourists Detected: {total_tourists}'
                cv2.putText(processed_frame, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2) # 红色文本

                # 缩放帧到目标显示大小
                resized_frame = cv2.resize(processed_frame, display_size)

                cv2.imshow('Tourist Monitoring System', resized_frame)

                # 检查退出按键
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            except StopIteration:
                print("End of stream.")
                break # 流结束，退出循环
            except Exception as e:
                print(f"Error processing frame: {e}")
                break # 发生其他错误，退出循环


        cv2.destroyAllWindows()

    else: # 处理图片文件 (单帧，无需跟踪)
        print("Processing image.")

        # 对于图片，predict 返回一个 results 列表 (即使 stream=False)
        results_generator = model.predict(source=source, stream=is_stream)
        results_list = list(results_generator) # Convert generator to list for single image

        if results_list:
            result = results_list[0]
            frame = result.orig_img
            original_height, original_width = frame.shape[:2]
            aspect_ratio = original_height / original_width
            display_height = int(target_display_width * aspect_ratio)
            display_size = (target_display_width, display_height)

            # 设置窗口初始大小
            cv2.resizeWindow('Tourist Monitoring System', target_display_width, display_height)

            processed_frame = frame.copy() # 复制一份帧用于绘制

            # 提取当前帧中“人”的 bounding boxes 并计数
            person_count = 0
            for box in result.boxes:
                 # 获取类别名称
                class_id = int(box.cls[0].cpu().numpy())
                class_name = model.names[class_id]
                conf = box.conf[0].cpu().numpy()

                # 检查是否是“人”类别且置信度高于阈值
                if class_name == 'person' and conf > 0.5: # 使用与 predict 中相同的阈值
                    person_count += 1
                    # 获取 bounding box 坐标 (x1, y1, x2, y2)
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    # 绘制 bounding box
                    color = (0, 255, 0) # 绿色
                    cv2.rectangle(processed_frame, (x1, y1), (x2, y2), color, 2)
                    # 绘制类别和置信度（可选）
                    label = f'{class_name}: {conf:.2f}'
                    cv2.putText(processed_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


            # 在帧上显示游客数量 (对于图片，显示当前帧检测到的人数)
            count_text = f'Tourists in Frame: {person_count}'
            cv2.putText(processed_frame, count_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2) # 红色文本


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
