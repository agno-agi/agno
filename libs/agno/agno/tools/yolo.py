from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from ultralytics import YOLO
except ImportError:
    raise ImportError("`ultralytics` not installed. Please install using `pip install ultralytics`")


class YOLOTools(Toolkit):
    def __init__(
        self,
        enable_detect_objects: bool = True,
        enable_count_objects: bool = True,
        all: bool = False,
        model: str = "yolo11n.pt",
        conf_threshold: float = 0.25,
        **kwargs,
    ):
        self.model_name = model
        self.conf_threshold = conf_threshold
        self._yolo_model: Optional[Any] = None

        tools: List[Any] = []
        if all or enable_detect_objects:
            tools.append(self.detect_objects)
        if all or enable_count_objects:
            tools.append(self.count_objects)

        super().__init__(name="yolo_tools", tools=tools, **kwargs)

    def _get_model(self) -> Any:
        """Return the loaded YOLO model, initializing it on first call.

        Returns:
            YOLO: The loaded Ultralytics YOLO model instance.
        """
        if self._yolo_model is None:
            log_debug(f"Loading YOLO model: {self.model_name}")
            self._yolo_model = YOLO(self.model_name)
        return self._yolo_model

    def detect_objects(self, image_path: str) -> str:
        """Use this function to detect all objects in an image.

        Each detected object is reported with its class label, confidence score,
        and bounding box coordinates [x1, y1, x2, y2] in pixels.

        Args:
            image_path: The path to the local image file to analyse.

        Returns:
            str: A formatted list of detected objects with their labels, confidence scores,
                 and bounding boxes, or an error message if detection fails.
        """
        if not image_path:
            return "No image path provided"

        log_debug(f"Detecting objects in image: {image_path}")

        path = Path(image_path)
        if not path.exists():
            return f"Error: image file not found at '{image_path}'"
        if not path.is_file():
            return f"Error: '{image_path}' is not a file"

        try:
            model = self._get_model()
            results = model(str(path), conf=self.conf_threshold, verbose=False)
            result = results[0]
        except Exception as e:
            return f"Error running object detection: {e}"

        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return f"No objects detected in '{path.name}' (confidence threshold: {self.conf_threshold})"

        names: Dict[int, str] = result.names
        lines = [f"Detected {len(boxes)} object(s) in '{path.name}':"]
        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i].item())
            label = names.get(cls_id, str(cls_id))
            conf = float(boxes.conf[i].item())
            xyxy = boxes.xyxy[i].tolist()
            x1, y1, x2, y2 = (round(v, 1) for v in xyxy)
            lines.append(f"  {i + 1}. {label} (conf={conf:.2f}, box=[{x1}, {y1}, {x2}, {y2}])")

        return "\n".join(lines)

    def count_objects(self, image_path: str, class_name: Optional[str] = None) -> str:
        """Use this function to count objects in an image, optionally filtered by class name.

        Args:
            image_path: The path to the local image file to analyse.
            class_name: If provided, count only detections matching this label (case-insensitive),
                e.g. "car" or "person". If omitted, counts are returned for every detected class.

        Returns:
            str: A plain-English summary of object counts, or an error message if detection fails.
        """
        if not image_path:
            return "No image path provided"

        log_debug(f"Counting objects in image: {image_path}")

        path = Path(image_path)
        if not path.exists():
            return f"Error: image file not found at '{image_path}'"
        if not path.is_file():
            return f"Error: '{image_path}' is not a file"

        try:
            model = self._get_model()
            results = model(str(path), conf=self.conf_threshold, verbose=False)
            result = results[0]
        except Exception as e:
            return f"Error running object detection: {e}"

        boxes = result.boxes
        filename = path.name

        if boxes is None or len(boxes) == 0:
            if class_name:
                return f"0 '{class_name}' detected in '{filename}'"
            return f"No objects detected in '{filename}' (confidence threshold: {self.conf_threshold})"

        names: Dict[int, str] = result.names
        counts: Dict[str, int] = {}
        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i].item())
            label = names.get(cls_id, str(cls_id))
            counts[label.lower()] = counts.get(label.lower(), 0) + 1

        if class_name:
            n = counts.get(class_name.lower(), 0)
            return f"{n} '{class_name}' detected in '{filename}'"

        total = sum(counts.values())
        parts = [f"{v} {k}(s)" for k, v in sorted(counts.items())]
        return f"Detected {total} object(s) in '{filename}': {', '.join(parts)}"
