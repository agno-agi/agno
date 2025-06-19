import base64
import time
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact, VideoArtifact
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    import cv2
except ImportError:
    raise ImportError("`opencv-python` package not found. Please install it with `pip install opencv-python`")


class OpenCVTools(Toolkit):
    """Tools for capturing images and videos from the webcam using OpenCV"""

    def __init__(self, show_preview=False, **kwargs):
        super().__init__(
            name="opencv_tools",
            tools=[
                self.capture_image,
                self.capture_video,
            ],
            **kwargs,
        )

        self.show_preview = show_preview

    def capture_image(
        self,
        agent: Agent,
        prompt: str = "Webcam capture",
    ) -> str:
        """Capture an image from the webcam.

        Args:
            prompt (str): Description of the image capture. Defaults to "Webcam capture".

        Returns:
            str: A message indicating success or failure.
        """
        try:
            log_debug("Initializing webcam for image capture...")
            cam = cv2.VideoCapture(0)

            if not cam.isOpened():
                cam = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)  # macOS
            if not cam.isOpened():
                cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Windows
            if not cam.isOpened():
                cam = cv2.VideoCapture(0, cv2.CAP_V4L2)  # Linux

            if not cam.isOpened():
                error_msg = "Could not open webcam. Please ensure your terminal has camera permissions and the camera is not being used by another application."
                log_error(error_msg)
                return error_msg

            try:
                cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cam.set(cv2.CAP_PROP_FPS, 30)

                log_debug("Camera initialized successfully")
                captured_frame = None

                if self.show_preview:
                    log_info("Live preview started. Press 'c' to capture image, 'q' to quit.")

                    while True:
                        ret, frame = cam.read()
                        if not ret:
                            error_msg = "Failed to read frame from webcam"
                            log_error(error_msg)
                            return error_msg

                        cv2.imshow('Camera Preview - Press "c" to capture, "q" to quit', frame)

                        key = cv2.waitKey(1) & 0xFF
                        if key == ord("c"):
                            captured_frame = frame.copy()
                            log_info("Image captured!")
                            break
                        elif key == ord("q"):
                            log_info("Capture cancelled by user")
                            return "Image capture cancelled by user"
                else:
                    ret, captured_frame = cam.read()
                    if not ret:
                        error_msg = "Failed to capture image from webcam"
                        log_error(error_msg)
                        return error_msg

                if captured_frame is None:
                    error_msg = "No frame captured"
                    log_error(error_msg)
                    return error_msg

                success, encoded_image = cv2.imencode(".png", captured_frame)

                if not success:
                    error_msg = "Failed to encode captured image"
                    log_error(error_msg)
                    return error_msg

                image_bytes = encoded_image.tobytes()
                base64_encoded_image = base64.b64encode(image_bytes)

                media_id = str(uuid4())
                agent.add_image(
                    ImageArtifact(
                        id=media_id,
                        content=base64_encoded_image,
                        original_prompt=prompt,
                        mime_type="image/png",
                    )
                )

                log_debug(f"Successfully captured and attached image {media_id}")
                return "Image captured successfully"

            finally:
                # Release the camera and close windows
                cam.release()
                cv2.destroyAllWindows()
                log_debug("Camera resources released")

        except Exception as e:
            error_msg = f"Error capturing image: {str(e)}"
            log_error(error_msg)
            return error_msg

    def capture_video(
        self,
        agent: Agent,
        duration: int = 10,
        prompt: str = "Webcam video capture",
    ) -> str:
        """Capture a video from the webcam.

        Args:
            duration (int): Duration in seconds to record video. Defaults to 10 seconds.
            prompt (str): Description of the video capture. Defaults to "Webcam video capture".

        Returns:
            str: A message indicating success or failure.
        """
        try:
            log_debug("Initializing webcam for video capture...")
            cap = cv2.VideoCapture(0)

            # Try different backends for better compatibility
            if not cap.isOpened():
                cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)  # macOS
            if not cap.isOpened():
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Windows
            if not cap.isOpened():
                cap = cv2.VideoCapture(0, cv2.CAP_V4L2)  # Linux

            if not cap.isOpened():
                error_msg = "Could not open webcam. Please ensure your terminal has camera permissions and the camera is not being used by another application."
                log_error(error_msg)
                return error_msg

            try:
                frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = cap.get(cv2.CAP_PROP_FPS)

                # Use actual FPS or default to 30 if detection fails
                if actual_fps <= 0 or actual_fps > 60:
                    actual_fps = 30.0

                log_debug(f"Video properties: {frame_width}x{frame_height} at {actual_fps} FPS")

                # Try different codecs in order of preference for compatibility
                codecs_to_try = [
                    ("avc1", "H.264"),  # Most compatible
                    ("mp4v", "MPEG-4"),  # Fallback
                    ("XVID", "Xvid"),  # Another fallback
                ]

                import os
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
                    temp_filepath = temp_file.name

                out = None
                successful_codec = None

                for codec_fourcc, codec_name in codecs_to_try:
                    try:
                        fourcc = getattr(cv2, "VideoWriter_fourcc")(*codec_fourcc)
                        out = cv2.VideoWriter(temp_filepath, fourcc, actual_fps, (frame_width, frame_height))

                        if out.isOpened():
                            successful_codec = codec_name
                            log_debug(f"Successfully initialized video writer with {codec_name} codec")
                            break
                        else:
                            out.release()
                            out = None
                    except Exception as e:
                        log_debug(f"Failed to initialize {codec_name} codec: {e}")
                        if out:
                            out.release()
                            out = None

                if not out or not out.isOpened():
                    error_msg = "Failed to initialize video writer with any codec"
                    log_error(error_msg)
                    return error_msg

                start_time = time.time()
                frame_count = 0

                if self.show_preview:
                    log_info(f"Recording {duration}s video with live preview using {successful_codec} codec...")
                else:
                    log_info(f"Recording {duration}s video using {successful_codec} codec...")

                while True:
                    ret, frame = cap.read()

                    if not ret:
                        error_msg = "Failed to capture video frame"
                        log_error(error_msg)
                        return error_msg

                    # Write the frame to the output file
                    out.write(frame)
                    frame_count += 1

                    # Show live preview if enabled
                    if self.show_preview:
                        # Add recording indicator
                        elapsed = time.time() - start_time
                        remaining = max(0, duration - elapsed)

                        # Draw recording info on frame
                        display_frame = frame.copy()
                        cv2.putText(
                            display_frame,
                            f"REC {remaining:.1f}s",
                            (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 255),
                            2,
                        )
                        cv2.circle(display_frame, (30, 60), 10, (0, 0, 255), -1)  # Red dot

                        cv2.imshow(f"Recording Video - {remaining:.1f}s remaining", display_frame)
                        cv2.waitKey(1)

                    # Check if recording duration is reached
                    if time.time() - start_time >= duration:
                        break

                # Release video writer
                out.release()

                # Verify the file was created and has content
                if not os.path.exists(temp_filepath) or os.path.getsize(temp_filepath) == 0:
                    error_msg = "Video file was not created or is empty"
                    log_error(error_msg)
                    return error_msg

                # Read the video file and encode to base64
                with open(temp_filepath, "rb") as video_file:
                    video_bytes = video_file.read()

                # Clean up temporary file
                os.unlink(temp_filepath)

                base64_encoded_video = base64.b64encode(video_bytes)

                media_id = str(uuid4())
                agent.add_video(
                    VideoArtifact(
                        id=media_id,
                        content=base64_encoded_video,
                        original_prompt=prompt,
                        mime_type="video/mp4",
                    )
                )

                actual_duration = time.time() - start_time
                log_debug(
                    f"Successfully captured and attached video {media_id} ({actual_duration:.1f}s, {frame_count} frames)"
                )
                return f"Video captured successfully and attached as artifact {media_id} ({actual_duration:.1f}s, {frame_count} frames, {successful_codec} codec)"

            finally:
                if "cap" in locals():
                    cap.release()
                cv2.destroyAllWindows()
                log_debug("Video capture resources released")

        except Exception as e:
            error_msg = f"Error capturing video: {str(e)}"
            log_error(error_msg)
            return error_msg
