import os

import cv2

from agno.tools import Toolkit


class ImageTools(Toolkit):
    def __init__(self):
        super().__init__(name="Image_tools")
        self.register(self.capture_image)

    def capture_image(self, save_dir="captured_images"):
        # Create save directory if it doesn't exist
        os.makedirs(save_dir, exist_ok=True)

        # Initialize webcam with explicit permission request
        cam = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

        if not cam.isOpened():
            print("Please ensure your terminal has camera permissions")
            print("Go to: System Settings > Privacy & Security > Camera")
            return {"status": "error", "message": "Could not open webcam"}

        try:
            # Wait a moment for camera to initialize
            cv2.waitKey(1000)

            # Capture frame
            ret, frame = cam.read()

            if not ret:
                return {"status": "error", "message": "Failed to capture image"}

            filename = os.path.join(save_dir, "capture.jpg")

            # Save image
            cv2.imwrite(filename, frame)

            print(f"Image successfully captured: {filename}")
            return {"status": "success", "filename": filename}

        except Exception as e:
            return {"status": "error", "message": str(e)}

        finally:
            # Release the camera
            cam.release()
