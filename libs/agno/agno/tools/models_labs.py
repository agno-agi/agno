import json
import time
from os import getenv
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Audio, Image, Video
from agno.models.response import FileType
from agno.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_info, logger

try:
    import requests
    from requests.exceptions import RequestException
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")

MODELS_LAB_URLS = {
    "MP4": "https://modelslab.com/api/v6/video/text2video",
    "MP3": "https://modelslab.com/api/v6/voice/music_gen",
    "GIF": "https://modelslab.com/api/v6/video/text2video",
}

MODELS_LAB_FETCH_URLS = {
    "MP4": "https://modelslab.com/api/v6/video/fetch",
    "MP3": "https://modelslab.com/api/v6/voice/fetch",
    "GIF": "https://modelslab.com/api/v6/video/fetch",
}


class ModelsLabTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        wait_for_completion: bool = False,
        add_to_eta: int = 15,
        max_wait_time: int = 60,
        file_type: FileType = FileType.MP4,
        **kwargs,
    ):
        file_type_str = file_type.value.upper()
        self.url = MODELS_LAB_URLS[file_type_str]
        self.fetch_url = MODELS_LAB_FETCH_URLS[file_type_str]
        self.wait_for_completion = wait_for_completion
        self.add_to_eta = add_to_eta
        self.max_wait_time = max_wait_time
        self.file_type = file_type
        self.api_key = api_key or getenv("MODELS_LAB_API_KEY")

        if not self.api_key:
            logger.error("MODELS_LAB_API_KEY not set. Please set the MODELS_LAB_API_KEY environment variable.")

        tools: List[Any] = []
        tools.append(self.generate_media)

        super().__init__(name="models_labs", tools=tools, **kwargs)

    def _create_payload(self, prompt: str) -> Dict[str, Any]:
        """Create payload based on file type."""
        base_payload: Dict[str, Any] = {
            "key": self.api_key,
            "prompt": prompt,
            "webhook": None,
            "track_id": None,
        }

        if self.file_type in [FileType.MP4, FileType.GIF]:
            video_template = {
                "height": 512,
                "width": 512,
                "num_frames": 25,
                "negative_prompt": "low quality",
                "model_id": "cogvideox",
                "instant_response": False,
                "output_type": self.file_type.value,
            }
            base_payload |= video_template  # Use |= instead of update()
        else:
            audio_template = {
                "base64": False,
                "temp": False,
            }
            base_payload |= audio_template  # Use |= instead of update()

        return base_payload

    def _create_media_artifacts(self, media_id: str, media_url: str, eta: Optional[str] = None) -> Dict[str, List]:
        """Create appropriate media artifacts based on file type."""
        artifacts: Dict[str, List[Union[Image, Video, Audio]]] = {
            "images": [],
            "videos": [],
            "audios": [],
        }

        if self.file_type == FileType.MP4:
            video_artifact = Video(id=str(media_id), url=media_url, eta=str(eta))
            artifacts["videos"].append(video_artifact)
        elif self.file_type == FileType.GIF:
            image_artifact = Image(id=str(media_id), url=media_url)
            artifacts["images"].append(image_artifact)
        elif self.file_type == FileType.MP3:
            audio_artifact = Audio(id=str(media_id), url=media_url)
            artifacts["audios"].append(audio_artifact)

        return artifacts

    def _wait_for_media(self, media_id: str, eta: int) -> bool:
        """Wait for media generation to complete."""
        time_to_wait = min(eta + self.add_to_eta, self.max_wait_time)
        log_info(f"Waiting for {time_to_wait} seconds for {self.file_type.value} to be ready")

        for seconds_waited in range(time_to_wait):
            try:
                fetch_response = requests.post(
                    f"{self.fetch_url}/{media_id}",
                    json={"key": self.api_key},
                    headers={"Content-Type": "application/json"},
                )
                fetch_result = fetch_response.json()

                if fetch_result.get("status") == "success":
                    return True

                time.sleep(1)

            except RequestException as e:
                logger.warning(f"Error during fetch attempt {seconds_waited}: {e}")

        return False

    def generate_media(self, agent: Union[Agent, Team], prompt: str) -> ToolResult:
        """Generate media (video, image, or audio) given a prompt."""
        if not self.api_key:
            return ToolResult(content="Please set the MODELS_LAB_API_KEY")

        try:
            payload = json.dumps(self._create_payload(prompt))
            headers = {"Content-Type": "application/json"}

            log_debug(f"Generating {self.file_type.value} for prompt: {prompt}")
            response = requests.post(self.url, data=payload, headers=headers)
            response.raise_for_status()

            result = response.json()

            status = result.get("status")
            if status == "error":
                logger.error(f"Error in response: {result.get('message')}")
                return ToolResult(content=f"Error: {result.get('message')}")

            if "error" in result:
                error_msg = f"Failed to generate {self.file_type.value}: {result['error']}"
                logger.error(error_msg)
                return ToolResult(content=f"Error: {result['error']}")

            eta = result.get("eta")
            url_links = result.get("future_links")
            media_id = str(uuid4())

            # Collect all media artifacts
            all_images = []
            all_videos = []
            all_audios = []

            for media_url in url_links:
                artifacts = self._create_media_artifacts(media_id, media_url, str(eta))
                all_images.extend(artifacts["images"])
                all_videos.extend(artifacts["videos"])
                all_audios.extend(artifacts["audios"])

            if self.wait_for_completion and isinstance(eta, int):
                if self._wait_for_media(media_id, eta):
                    log_info("Media generation completed successfully")
                else:
                    logger.warning("Media generation timed out")

            # Return ToolResult with appropriate media artifacts
            return ToolResult(
                content=f"{self.file_type.value.capitalize()} has been generated successfully and will be ready in {eta} seconds",
                images=all_images if all_images else None,
                videos=all_videos if all_videos else None,
                audios=all_audios if all_audios else None,
            )

        except RequestException as e:
            error_msg = f"Network error while generating {self.file_type.value}: {e}"
            logger.error(error_msg)
            return ToolResult(content=f"Error: {error_msg}")
        except Exception as e:
            error_msg = f"Unexpected error while generating {self.file_type.value}: {e}"
            logger.error(error_msg)
            return ToolResult(content=f"Error: {error_msg}")
