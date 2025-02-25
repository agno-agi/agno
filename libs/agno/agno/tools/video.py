import os

import cv2

from agno.tools import Toolkit


class VideoTools(Toolkit):
    def __init__(self):
        super().__init__(name="video_tools")
        self.register(self.capture_video)


    def capture_video(self,duration=20, save_dir='captured_videos'):
        # Create save directory if it doesn't exist
        os.makedirs(save_dir, exist_ok=True)
        
        # Initialize webcam
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("Please ensure your terminal has camera permissions")
            print("Go to: System Settings > Privacy & Security > Camera")
            return {'status': 'error', 'message': 'Could not open webcam'}
        
        # Define video codec and create VideoWriter object
        
        filename = os.path.join(save_dir, 'video_capture.mp4')
        
        # Get frame dimensions
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Create VideoWriter object
        out = cv2.VideoWriter(filename, 0x7634706d , 20.0, (frame_width, frame_height))
        
        start_time = cv2.getTickCount()
        
        try:
            while True:
                # Capture frame-by-frame
                ret, frame = cap.read()
                
                if not ret:
                    return {'status': 'error', 'message': 'Failed to capture video'}
                
                # Write the frame to the output file
                out.write(frame)
                
                # Calculate elapsed time
                elapsed_time = (cv2.getTickCount() - start_time) / cv2.getTickFrequency()
                
                # Break the loop if the recording duration is reached
                if elapsed_time >= duration:
                    break
                
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
        
        finally:
            # Release everything when job is finished
            cap.release()
            out.release()
            cv2.destroyAllWindows()
            
            print(f"Video successfully captured: {filename}")
            return {'status': 'success', 'filename': filename}