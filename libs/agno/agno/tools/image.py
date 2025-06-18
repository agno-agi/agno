import json
import os
from typing import Optional

from agno.agent import Agent
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error

try:
    import cv2
except ImportError:
    raise ImportError("`opencv-python` package not found. Please install it with `pip install opencv-python`")


class ImageTools(Toolkit):
    def __init__(self, **kwargs):
        super().__init__(
            name="image_tools",
            tools=[
                self.capture_image,
            ],
            **kwargs,
        )

    def capture_image(
        self,
        agent: Agent,
        save_dir: str = "captured_images",
        filename: Optional[str] = None,
    ) -> str:
        """Capture an image from the webcam and save it to a specified directory.

        Args:
            save_dir (str): Directory to save the captured image. Defaults to "captured_images".
            filename (str, optional): Custom filename for the image. If not provided, defaults to "capture.jpg".

        Returns:
            str: JSON-encoded response with status and filename, or error message.
        """
        try:
            os.makedirs(save_dir, exist_ok=True)
            log_debug(f"Save directory created/verified: {save_dir}")

            # Set default filename if not provided
            if filename is None:
                filename = "capture.jpg"

            filepath = os.path.join(save_dir, filename)

            # Initialize webcam with explicit permission request
            log_debug("Initializing webcam...")
            cam = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

            if not cam.isOpened():
                error_msg = "Could not open webcam. Please ensure your terminal has camera permissions. Go to: System Settings > Privacy & Security > Camera"
                log_error(error_msg)
                return json.dumps({"status": "error", "message": error_msg})

            try:
                # Wait a moment for camera to initialize
                cv2.waitKey(1000)
                log_debug("Camera initialized successfully")

                # Capture frame
                ret, frame = cam.read()

                if not ret:
                    error_msg = "Failed to capture image from webcam"
                    log_error(error_msg)
                    return json.dumps({"status": "error", "message": error_msg})

                # Save image
                success = cv2.imwrite(filepath, frame)

                if not success:
                    error_msg = f"Failed to save image to {filepath}"
                    log_error(error_msg)
                    return json.dumps({"status": "error", "message": error_msg})

                log_debug(f"Image successfully captured and saved: {filepath}")
                return json.dumps(
                    {"status": "success", "filename": filepath, "message": f"Image successfully captured: {filepath}"}
                )

            finally:
                # Release the camera
                cam.release()
                cv2.destroyAllWindows()
                log_debug("Camera resources released")

        except Exception as e:
            error_msg = f"Error capturing image: {str(e)}"
            log_error(error_msg)
            return json.dumps({"status": "error", "message": error_msg})
