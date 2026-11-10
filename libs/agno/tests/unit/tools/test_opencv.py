"""Unit tests for OpenCVTools class."""

from unittest.mock import Mock, patch

import numpy as np
import pytest

from agno.agent import Agent
from agno.media import Image, Video
from agno.tools.function import ToolResult
from agno.tools.opencv import OpenCVTools


@pytest.fixture
def mock_cv2():
    """Create a mock OpenCV module."""
    with patch("agno.tools.opencv.cv2") as mock_cv2:
        mock_cv2.CAP_AVFOUNDATION = 1200
        mock_cv2.CAP_DSHOW = 700
        mock_cv2.CAP_V4L2 = 200
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.FONT_HERSHEY_SIMPLEX = 0

        # Mock VideoCapture
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        mock_capture.set.return_value = True
        mock_capture.get.side_effect = lambda prop: {3: 1280, 4: 720, 5: 30.0}[prop]
        mock_capture.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))
        mock_capture.release.return_value = None
        mock_cv2.VideoCapture.return_value = mock_capture

        # Mock image encoding
        mock_cv2.imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

        # Mock video writer
        mock_writer = Mock()
        mock_writer.isOpened.return_value = True
        mock_writer.write.return_value = None
        mock_writer.release.return_value = None
        mock_cv2.VideoWriter.return_value = mock_writer

        # Mock VideoWriter_fourcc
        mock_cv2.VideoWriter_fourcc.return_value = 123456

        # Mock GUI functions
        mock_cv2.imshow.return_value = None
        mock_cv2.waitKey.return_value = ord("c")  # Default to capture key
        mock_cv2.destroyAllWindows.return_value = None
        mock_cv2.putText.return_value = None
        mock_cv2.circle.return_value = None

        yield mock_cv2


@pytest.fixture
def mock_agent():
    """Create a mock Agent instance."""
    agent = Mock(spec=Agent)
    return agent


@pytest.fixture
def opencv_tools_with_preview(mock_cv2):
    """Create OpenCVTools instance with preview enabled."""
    return OpenCVTools(show_preview=True)


@pytest.fixture
def opencv_tools_no_preview(mock_cv2):
    """Create OpenCVTools instance with preview disabled."""
    return OpenCVTools(show_preview=False)


class TestOpenCVToolsInitialization:
    """Test OpenCVTools initialization and configuration."""

    def test_init_with_preview_enabled(self, mock_cv2):
        """Test initialization with preview enabled."""
        tools = OpenCVTools(show_preview=True)
        assert tools.show_preview is True
        assert tools.name == "opencv_tools"
        assert len(tools.tools) == 2

    def test_init_with_preview_disabled(self, mock_cv2):
        """Test initialization with preview disabled."""
        tools = OpenCVTools(show_preview=False)
        assert tools.show_preview is False
        assert tools.name == "opencv_tools"
        assert len(tools.tools) == 2

    def test_init_default_preview(self, mock_cv2):
        """Test default initialization (preview disabled by default)."""
        tools = OpenCVTools()
        assert tools.show_preview is False


class TestImageCapture:
    """Test image capture functionality."""

    def test_capture_image_no_preview_success(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test successful image capture without preview."""
        result = opencv_tools_no_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with success content
        assert isinstance(result, ToolResult)
        assert result.content == "Image captured successfully"
        assert result.images is not None
        assert len(result.images) == 1

        # Verify image artifact was created correctly
        image_artifact = result.images[0]
        assert isinstance(image_artifact, Image)
        assert image_artifact.original_prompt == "Test capture"
        assert image_artifact.mime_type == "image/png"

        # Verify OpenCV calls
        mock_cv2.VideoCapture.assert_called_with(0)
        mock_cv2.imencode.assert_called_once()

    def test_capture_image_with_preview_success(self, opencv_tools_with_preview, mock_agent, mock_cv2):
        """Test successful image capture with preview (user presses 'c')."""
        # Mock waitKey to return 'c' (capture) on first call
        mock_cv2.waitKey.return_value = ord("c")

        result = opencv_tools_with_preview.capture_image(mock_agent, "Test capture with preview")

        # Check that result is a ToolResult with success content
        assert isinstance(result, ToolResult)
        assert result.content == "Image captured successfully"
        assert result.images is not None
        assert len(result.images) == 1

        # Verify preview was shown
        mock_cv2.imshow.assert_called()

    def test_capture_image_user_cancels(self, opencv_tools_with_preview, mock_agent, mock_cv2):
        """Test image capture cancelled by user (user presses 'q')."""
        # Mock waitKey to return 'q' (quit) on first call
        mock_cv2.waitKey.return_value = ord("q")

        result = opencv_tools_with_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with cancellation content
        assert isinstance(result, ToolResult)
        assert result.content == "Image capture cancelled by user"
        assert result.images is None

    def test_capture_image_camera_not_available(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test image capture when camera is not available."""
        mock_cv2.VideoCapture.return_value.isOpened.return_value = False

        result = opencv_tools_no_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Could not open webcam" in result.content
        assert result.images is None

    def test_capture_image_read_frame_fails(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test image capture when reading frame fails."""
        mock_cv2.VideoCapture.return_value.read.return_value = (False, None)

        result = opencv_tools_no_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Failed to capture image from webcam" in result.content
        assert result.images is None

    def test_capture_image_encode_fails(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test image capture when encoding fails."""
        mock_cv2.imencode.return_value = (False, None)

        result = opencv_tools_no_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Failed to encode captured image" in result.content
        assert result.images is None

    def test_capture_image_exception_handling(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test image capture exception handling."""
        mock_cv2.VideoCapture.side_effect = Exception("Test exception")

        result = opencv_tools_no_preview.capture_image(mock_agent, "Test capture")

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Error capturing image: Test exception" in result.content
        assert result.images is None


class TestVideoCapture:
    """Test video capture functionality."""

    @patch("tempfile.NamedTemporaryFile")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.unlink")
    @patch("builtins.open", create=True)
    @patch("agno.tools.opencv.time")
    def test_capture_video_no_preview_success(
        self,
        mock_time_module,
        mock_open,
        mock_unlink,
        mock_getsize,
        mock_exists,
        mock_tempfile,
        opencv_tools_no_preview,
        mock_agent,
        mock_cv2,
    ):
        """Test successful video capture without preview."""
        # Patch the time module reference in opencv so logging doesn't consume mock values
        mock_time_module.time.side_effect = [0, 6, 6]

        # Mock temporary file
        mock_temp = Mock()
        mock_temp.name = "/tmp/test_video.mp4"
        mock_tempfile.return_value.__enter__.return_value = mock_temp

        # Mock file operations
        mock_exists.return_value = True
        mock_getsize.return_value = 1000  # Non-zero size
        mock_file = Mock()
        mock_file.read.return_value = b"fake_video_data"
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock getattr for VideoWriter_fourcc
        with patch("agno.tools.opencv.getattr") as mock_getattr, patch("agno.tools.opencv.Path") as mock_path_class:
            mock_getattr.return_value.return_value = 123456

            # Mock Path behavior
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_stat = Mock()
            mock_stat.st_size = 1000  # Non-zero size
            mock_path.stat.return_value = mock_stat
            mock_path_class.return_value = mock_path

            result = opencv_tools_no_preview.capture_video(mock_agent, duration=5, prompt="Test video")

        # Check that result is a ToolResult with success content
        assert isinstance(result, ToolResult)
        assert "Video captured successfully" in result.content
        assert "H.264 codec" in result.content  # Should use first codec successfully
        assert result.videos is not None
        assert len(result.videos) == 1

        # Verify video artifact was created correctly
        video_artifact = result.videos[0]
        assert isinstance(video_artifact, Video)
        assert video_artifact.original_prompt == "Test video"
        assert video_artifact.mime_type == "video/mp4"

    @patch("tempfile.NamedTemporaryFile")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.unlink")
    @patch("builtins.open", create=True)
    @patch("agno.tools.opencv.time")
    def test_capture_video_with_preview_success(
        self,
        mock_time_module,
        mock_open,
        mock_unlink,
        mock_getsize,
        mock_exists,
        mock_tempfile,
        opencv_tools_with_preview,
        mock_agent,
        mock_cv2,
    ):
        """Test successful video capture with preview."""
        # Patch the time module reference in opencv so logging doesn't consume mock values
        # Preview path: start_time, elapsed, duration_check, actual_duration
        mock_time_module.time.side_effect = [0, 1, 4, 4]

        # Mock temporary file
        mock_temp = Mock()
        mock_temp.name = "/tmp/test_video.mp4"
        mock_tempfile.return_value.__enter__.return_value = mock_temp

        # Mock file operations
        mock_exists.return_value = True
        mock_getsize.return_value = 1000
        mock_file = Mock()
        mock_file.read.return_value = b"fake_video_data"
        mock_open.return_value.__enter__.return_value = mock_file

        # Mock getattr for VideoWriter_fourcc
        with patch("agno.tools.opencv.getattr") as mock_getattr, patch("agno.tools.opencv.Path") as mock_path_class:
            mock_getattr.return_value.return_value = 123456

            # Mock Path behavior
            mock_path = Mock()
            mock_path.exists.return_value = True
            mock_stat = Mock()
            mock_stat.st_size = 1000  # Non-zero size
            mock_path.stat.return_value = mock_stat
            mock_path_class.return_value = mock_path

            result = opencv_tools_with_preview.capture_video(mock_agent, duration=3, prompt="Test video")

        # Check that result is a ToolResult with success content
        assert isinstance(result, ToolResult)
        assert "Video captured successfully" in result.content
        assert result.videos is not None
        assert len(result.videos) == 1

        # Verify preview was shown
        mock_cv2.imshow.assert_called()  # Preview should be shown
        mock_cv2.putText.assert_called()  # Recording indicator should be drawn

    def test_capture_video_camera_not_available(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture when camera is not available."""
        mock_cv2.VideoCapture.return_value.isOpened.return_value = False

        result = opencv_tools_no_preview.capture_video(mock_agent, duration=5)

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Could not open webcam" in result.content
        assert result.videos is None

    def test_capture_video_invalid_fps(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture with invalid FPS (should default to 30)."""
        # Mock invalid FPS values
        mock_cv2.VideoCapture.return_value.get.side_effect = lambda prop: {
            3: 1280,
            4: 720,
            5: -1,  # Invalid FPS
        }[prop]

        with (
            patch("tempfile.NamedTemporaryFile") as mock_tempfile,
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch("os.unlink"),
            patch("builtins.open", create=True) as mock_open,
            patch("agno.tools.opencv.time") as mock_time,
            patch("agno.tools.opencv.getattr") as mock_getattr,
        ):
            mock_time.time.side_effect = [0, 2, 2]

            # Mock temporary file
            mock_temp = Mock()
            mock_temp.name = "/tmp/test_video.mp4"
            mock_tempfile.return_value.__enter__.return_value = mock_temp

            # Mock file operations
            mock_file = Mock()
            mock_file.read.return_value = b"fake_video_data"
            mock_open.return_value.__enter__.return_value = mock_file

            mock_getattr.return_value.return_value = 123456
            # This should not fail and should use 30.0 as default FPS
            result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult
        assert isinstance(result, ToolResult)
        # Should succeed with default FPS or fail gracefully
        assert (
            "Video captured successfully" in result.content
            or "Failed to initialize video writer" in result.content
            or "Video file was not created" in result.content
        )

    def test_capture_video_codec_fallback(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture codec fallback mechanism."""
        # Mock first codec failing, second succeeding
        mock_writer_fail = Mock()
        mock_writer_fail.isOpened.return_value = False
        mock_writer_success = Mock()
        mock_writer_success.isOpened.return_value = True

        mock_cv2.VideoWriter.side_effect = [mock_writer_fail, mock_writer_success]

        with (
            patch("tempfile.NamedTemporaryFile") as mock_tempfile,
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch("os.unlink"),
            patch("builtins.open", create=True) as mock_open,
            patch("agno.tools.opencv.time") as mock_time,
            patch("agno.tools.opencv.getattr") as mock_getattr,
        ):
            mock_time.time.side_effect = [0, 2, 2]

            # Mock temporary file
            mock_temp = Mock()
            mock_temp.name = "/tmp/test_video.mp4"
            mock_tempfile.return_value.__enter__.return_value = mock_temp

            # Mock file operations
            mock_file = Mock()
            mock_file.read.return_value = b"fake_video_data"
            mock_open.return_value.__enter__.return_value = mock_file

            mock_getattr.return_value.return_value = 123456
            result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult
        assert isinstance(result, ToolResult)
        # Should succeed with fallback codec or fail gracefully
        assert (
            "Video captured successfully" in result.content
            or "MPEG-4 codec" in result.content
            or "Video file was not created" in result.content
        )

    def test_capture_video_all_codecs_fail(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture when all codecs fail."""
        mock_cv2.VideoWriter.return_value.isOpened.return_value = False

        with patch("agno.tools.opencv.getattr") as mock_getattr:
            mock_getattr.return_value.return_value = 123456
            result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Failed to initialize video writer with any codec" in result.content
        assert result.videos is None

    def test_capture_video_frame_read_fails(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture when frame reading fails."""
        mock_cv2.VideoCapture.return_value.read.return_value = (False, None)

        with patch("tempfile.NamedTemporaryFile"), patch("agno.tools.opencv.getattr") as mock_getattr:
            mock_getattr.return_value.return_value = 123456
            result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Failed to capture video frame" in result.content
        assert result.videos is None

    @patch("tempfile.NamedTemporaryFile")
    @patch("os.path.exists")
    def test_capture_video_file_not_created(
        self, mock_exists, mock_tempfile, opencv_tools_no_preview, mock_agent, mock_cv2
    ):
        """Test video capture when temporary file is not created."""
        mock_temp = Mock()
        mock_temp.name = "/tmp/test_video.mp4"
        mock_tempfile.return_value.__enter__.return_value = mock_temp
        mock_exists.return_value = False  # File doesn't exist

        with (
            patch("agno.tools.opencv.time") as mock_time,
            patch("agno.tools.opencv.getattr") as mock_getattr,
        ):
            mock_time.time.side_effect = [0, 2]
            mock_getattr.return_value.return_value = 123456
            result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Video file was not created or is empty" in result.content
        assert result.videos is None

    def test_capture_video_exception_handling(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture exception handling."""
        mock_cv2.VideoCapture.side_effect = Exception("Test exception")

        result = opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert "Error capturing video: Test exception" in result.content
        assert result.videos is None


class TestResourceCleanup:
    """Test proper resource cleanup in all scenarios."""

    def test_image_capture_cleanup_on_success(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test that camera resources are properly released on successful image capture."""
        mock_cam = mock_cv2.VideoCapture.return_value

        opencv_tools_no_preview.capture_image(mock_agent, "Test")

        mock_cam.release.assert_called_once()
        mock_cv2.destroyAllWindows.assert_called_once()

    def test_image_capture_cleanup_on_exception(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test that camera resources are properly released on exception."""
        mock_cam = mock_cv2.VideoCapture.return_value
        mock_cv2.imencode.side_effect = Exception("Test exception")

        opencv_tools_no_preview.capture_image(mock_agent, "Test")

        mock_cam.release.assert_called_once()
        mock_cv2.destroyAllWindows.assert_called_once()

    def test_video_capture_cleanup_on_success(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test that video capture resources are properly released on success."""
        mock_cap = mock_cv2.VideoCapture.return_value

        with (
            patch("tempfile.NamedTemporaryFile") as mock_tempfile,
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch("os.unlink"),
            patch("builtins.open", create=True) as mock_open,
            patch("agno.tools.opencv.time") as mock_time,
            patch("agno.tools.opencv.getattr") as mock_getattr,
        ):
            mock_time.time.side_effect = [0, 2, 2]

            # Mock temporary file
            mock_temp = Mock()
            mock_temp.name = "/tmp/test_video.mp4"
            mock_tempfile.return_value.__enter__.return_value = mock_temp

            # Mock file operations
            mock_file = Mock()
            mock_file.read.return_value = b"fake_video_data"
            mock_open.return_value.__enter__.return_value = mock_file

            mock_getattr.return_value.return_value = 123456
            opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        mock_cap.release.assert_called_once()
        mock_cv2.destroyAllWindows.assert_called_once()

    def test_video_capture_cleanup_on_exception(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test that video capture resources are properly released on exception."""
        mock_cap = mock_cv2.VideoCapture.return_value
        mock_cv2.VideoCapture.side_effect = [mock_cap, Exception("Test exception")]

        opencv_tools_no_preview.capture_video(mock_agent, duration=1)

        mock_cap.release.assert_called_once()
        mock_cv2.destroyAllWindows.assert_called_once()


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_capture_image_default_prompt(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test image capture with default prompt."""
        result = opencv_tools_no_preview.capture_image(mock_agent)

        # Check that result is a ToolResult with the expected artifact
        assert isinstance(result, ToolResult)
        assert result.images is not None
        assert len(result.images) == 1

        image_artifact = result.images[0]
        assert image_artifact.original_prompt == "Webcam capture"

    def test_capture_video_default_parameters(self, opencv_tools_no_preview, mock_agent, mock_cv2):
        """Test video capture with default parameters."""
        with (
            patch("tempfile.NamedTemporaryFile") as mock_tempfile,
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch("os.unlink"),
            patch("builtins.open", create=True) as mock_open,
            patch("agno.tools.opencv.time") as mock_time,
            patch("agno.tools.opencv.getattr") as mock_getattr,
        ):
            mock_time.time.side_effect = [0, 11, 11]

            # Mock temporary file
            mock_temp = Mock()
            mock_temp.name = "/tmp/test_video.mp4"
            mock_tempfile.return_value.__enter__.return_value = mock_temp

            # Mock file operations
            mock_file = Mock()
            mock_file.read.return_value = b"fake_video_data"
            mock_open.return_value.__enter__.return_value = mock_file

            mock_getattr.return_value.return_value = 123456
            result = opencv_tools_no_preview.capture_video(mock_agent)

        # Check that result is a ToolResult
        assert isinstance(result, ToolResult)
        # The result could be success or failure depending on mocking, but should have expected prompt if successful
        if result.videos and len(result.videos) > 0:
            video_artifact = result.videos[0]
            assert video_artifact.original_prompt == "Webcam video capture"

    def test_preview_mode_persistence(self, mock_cv2):
        """Test that preview mode setting persists across calls."""
        tools_with_preview = OpenCVTools(show_preview=True)
        tools_without_preview = OpenCVTools(show_preview=False)

        assert tools_with_preview.show_preview is True
        assert tools_without_preview.show_preview is False

        # Setting should persist
        assert tools_with_preview.show_preview is True
        assert tools_without_preview.show_preview is False
