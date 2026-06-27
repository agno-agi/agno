"""Unit tests for YOLOTools.

Run with:
    pytest libs/agno/tests/unit/tools/test_yolo_tools.py -v

These tests use mocked ultralytics inference so no GPU, internet access,
or model weights are required in CI.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(detections: list, names: dict):
    """Return a real ultralytics Results object pre-loaded with fake boxes.

    Args:
        detections: List of (x1, y1, x2, y2, conf, cls_id) tuples.
        names: Mapping of class id to label string.
    """
    from ultralytics.engine.results import Results

    orig_img = np.zeros((480, 640, 3), dtype=np.uint8)
    if detections:
        boxes_data = torch.tensor(detections, dtype=torch.float32)
    else:
        boxes_data = torch.zeros((0, 6), dtype=torch.float32)
    return Results(orig_img=orig_img, path="/tmp/test.jpg", names=names, boxes=boxes_data)


COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle"}

STREET_SCENE = [
    (10.0, 20.0, 100.0, 80.0, 0.92, 2),  # car
    (50.0, 60.0, 200.0, 180.0, 0.85, 2),  # car
    (300.0, 100.0, 400.0, 300.0, 0.77, 0),  # person
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_image(tmp_path: Path) -> str:
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff")
    return str(img)


@pytest.fixture()
def yolo_tools():
    with patch("agno.tools.yolo.YOLO"):
        from agno.tools.yolo import YOLOTools

        t = YOLOTools()
    return t


def _inject(tools, detections, names=COCO_NAMES):
    """Replace the internal model with a mock that returns fake results."""
    fake_result = _make_result(detections, names)
    mock_model = MagicMock()
    mock_model.return_value = [fake_result]
    tools._yolo_model = mock_model


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestYOLOToolsRegistration:
    def test_name(self, yolo_tools):
        assert yolo_tools.name == "yolo_tools"

    def test_default_functions_registered(self, yolo_tools):
        assert "detect_objects" in yolo_tools.functions
        assert "count_objects" in yolo_tools.functions

    def test_disable_detect_objects(self):
        with patch("agno.tools.yolo.YOLO"):
            from agno.tools.yolo import YOLOTools

            t = YOLOTools(enable_detect_objects=False)
        assert "detect_objects" not in t.functions
        assert "count_objects" in t.functions

    def test_disable_count_objects(self):
        with patch("agno.tools.yolo.YOLO"):
            from agno.tools.yolo import YOLOTools

            t = YOLOTools(enable_count_objects=False)
        assert "count_objects" not in t.functions
        assert "detect_objects" in t.functions

    def test_all_flag(self):
        with patch("agno.tools.yolo.YOLO"):
            from agno.tools.yolo import YOLOTools

            t = YOLOTools(all=True)
        assert "detect_objects" in t.functions
        assert "count_objects" in t.functions


# ---------------------------------------------------------------------------
# detect_objects
# ---------------------------------------------------------------------------


class TestDetectObjects:
    def test_returns_correct_count(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.detect_objects(tmp_image)
        assert "3 object(s)" in out

    def test_labels_present(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.detect_objects(tmp_image)
        assert "car" in out
        assert "person" in out

    def test_confidence_scores_present(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.detect_objects(tmp_image)
        assert "conf=0.92" in out
        assert "conf=0.77" in out

    def test_empty_detections(self, yolo_tools, tmp_image):
        _inject(yolo_tools, [])
        out = yolo_tools.detect_objects(tmp_image)
        assert "No objects detected" in out

    def test_empty_path(self, yolo_tools):
        out = yolo_tools.detect_objects("")
        assert "No image path provided" in out

    def test_missing_file(self, yolo_tools):
        out = yolo_tools.detect_objects("/nonexistent/totally/fake.jpg")
        assert "Error" in out


# ---------------------------------------------------------------------------
# count_objects
# ---------------------------------------------------------------------------


class TestCountObjects:
    def test_count_all_classes(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.count_objects(tmp_image)
        assert "2 car(s)" in out
        assert "1 person(s)" in out

    def test_count_specific_class(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.count_objects(tmp_image, "car")
        assert "2" in out
        assert "car" in out

    def test_count_case_insensitive(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        assert "2" in yolo_tools.count_objects(tmp_image, "car")
        assert "2" in yolo_tools.count_objects(tmp_image, "CAR")

    def test_count_absent_class_returns_zero(self, yolo_tools, tmp_image):
        _inject(yolo_tools, STREET_SCENE)
        out = yolo_tools.count_objects(tmp_image, "elephant")
        assert out.startswith("0")

    def test_count_empty_image(self, yolo_tools, tmp_image):
        _inject(yolo_tools, [])
        out = yolo_tools.count_objects(tmp_image)
        assert "No objects detected" in out

    def test_empty_path(self, yolo_tools):
        out = yolo_tools.count_objects("")
        assert "No image path provided" in out

    def test_missing_file(self, yolo_tools):
        out = yolo_tools.count_objects("/nonexistent/fake.jpg")
        assert "Error" in out
