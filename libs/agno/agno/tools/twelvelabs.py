import json
import time
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

try:
    from twelvelabs import TwelveLabs
    from twelvelabs.types.video_context import VideoContext_Url
except ImportError:
    raise ImportError("`twelvelabs` not installed. Please install using `pip install twelvelabs`")


class TwelveLabsTools(Toolkit):
    """
    TwelveLabsTools is a toolkit for interfacing with TwelveLabs' video understanding APIs.

    It exposes three video-understanding capabilities for agents (`analyze_video` and
    `embed_text` are enabled by default; `embed_video` is long-running and opt-in):
      - `analyze_video`: ask a natural-language question about a video and get a text answer
        back, powered by the Pegasus video understanding model.
      - `embed_text`: generate a multimodal embedding for a piece of text using the Marengo
        model. Marengo embeds text, video, audio and images into the same latent space, so
        these vectors can be used to search a video corpus by text.
      - `embed_video`: embed a whole video into the same Marengo latent space with one
        vector per 2-10s segment. Video embedding is asynchronous: the tool creates a task,
        waits for it to finish, and returns a summary of the resulting segments (their count,
        the embedding dimensionality and each segment's time offsets and scope). The raw
        vectors are not returned to the agent (see `embed_video` for why); this tool is
        long-running, so it is disabled by default and must be enabled explicitly.

    Args:
        api_key (Optional[str]): TwelveLabs API key. Read from the `TWELVELABS_API_KEY`
            environment variable if not provided.
        analyze_model (str): The Pegasus model used for `analyze_video`. Default is "pegasus1.5".
        embed_model (str): The Marengo model used for `embed_text` and `embed_video`. Default is "marengo3.0".
        max_tokens (int): Maximum number of tokens for `analyze_video` responses. Default is 2048.
        embed_poll_interval (float): Seconds to wait between status checks while an `embed_video`
            task is processing. Default is 5.0.
        embed_timeout (float): Maximum seconds to wait for an `embed_video` task to finish before
            giving up. Default is 300.0.
        enable_analyze_video (bool): Enable the `analyze_video` tool. Default is True.
        enable_embed_text (bool): Enable the `embed_text` tool. Default is True.
        enable_embed_video (bool): Enable the `embed_video` tool. Because video embedding is
            long-running (it polls an async task), this is opt-in and defaults to False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        analyze_model: str = "pegasus1.5",
        embed_model: str = "marengo3.0",
        max_tokens: int = 2048,
        embed_poll_interval: float = 5.0,
        embed_timeout: float = 300.0,
        enable_analyze_video: bool = True,
        enable_embed_text: bool = True,
        enable_embed_video: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("TWELVELABS_API_KEY")
        if not self.api_key:
            logger.warning("No TwelveLabs API key provided. Set TWELVELABS_API_KEY or pass api_key.")

        self.analyze_model = analyze_model
        self.embed_model = embed_model
        self.max_tokens = max_tokens
        self.embed_poll_interval = embed_poll_interval
        self.embed_timeout = embed_timeout
        self._client: Optional[TwelveLabs] = None

        tools: List[Any] = []
        if all or enable_analyze_video:
            tools.append(self.analyze_video)
        if all or enable_embed_text:
            tools.append(self.embed_text)
        if all or enable_embed_video:
            tools.append(self.embed_video)

        super().__init__(name="twelvelabs_tools", tools=tools, **kwargs)

    @property
    def client(self) -> TwelveLabs:
        if self._client is None:
            if not self.api_key:
                raise ValueError("No TwelveLabs API key provided. Set TWELVELABS_API_KEY or pass api_key.")
            self._client = TwelveLabs(api_key=self.api_key)
        return self._client

    def analyze_video(self, video_url: str, prompt: str) -> str:
        """Analyze a video and answer a question about it using the Pegasus model.

        Args:
            video_url (str): A publicly accessible URL of the video to analyze.
            prompt (str): The natural-language question or instruction about the video.

        Returns:
            str: The text answer generated from the video, or an error message.
        """
        if not video_url:
            return "No video_url provided"
        if not prompt:
            return "No prompt provided"

        log_info(f"Analyzing video with Pegasus: {video_url}")
        try:
            response = self.client.analyze(
                model_name=self.analyze_model,
                video=VideoContext_Url(url=video_url),
                prompt=prompt,
                max_tokens=self.max_tokens,
            )
            return response.data or "No analysis returned"
        except Exception as e:
            log_error(f"Error analyzing video {video_url}: {e}")
            return f"Error analyzing video: {e}"

    def embed_text(self, text: str) -> str:
        """Generate a multimodal embedding for the given text using the Marengo model.

        The returned vector lives in the same latent space as TwelveLabs video, audio and
        image embeddings, so it can be used to search a video corpus by text.

        Args:
            text (str): The text to embed.

        Returns:
            str: A JSON object with the model name and the embedding vector, or an error message.
        """
        if not text:
            return "No text provided"

        log_info(f"Embedding text with Marengo: {text[:50]}")
        try:
            response = self.client.embed.create(model_name=self.embed_model, text=text)
            if response.text_embedding is None or not response.text_embedding.segments:
                return "No embedding returned"
            vector = response.text_embedding.segments[0].float_
            if not vector:
                return "No embedding returned"
            return json.dumps({"model": self.embed_model, "dimensions": len(vector), "embedding": vector})
        except Exception as e:
            log_error(f"Error embedding text: {e}")
            return f"Error embedding text: {e}"

    def embed_video(self, video_url: str) -> str:
        """Generate Marengo multimodal embeddings for a video.

        TwelveLabs embeds video asynchronously, so this creates an embedding task, waits for
        it to finish, and embeds the video into the same latent space as `embed_text` with
        one vector per 2-10s segment.

        The raw float vectors are deliberately NOT returned: Marengo emits one ~512-dim
        vector per segment, so a long video is hundreds of KB of floats that would flood (or
        exceed) the model context, and the model cannot use raw vectors anyway. Instead this
        returns a compact summary of the segmentation. Consume the vectors from a vector
        store or a TwelveLabs index if you need to run similarity search over them.

        Args:
            video_url (str): A publicly accessible URL of the video to embed.

        Returns:
            str: A JSON object with the model name, embedding dimensions, segment count and a
                list of per-segment metadata (start/end offsets and scope), or an error
                message.
        """
        if not video_url:
            return "No video_url provided"

        log_info(f"Embedding video with Marengo: {video_url}")
        try:
            task = self.client.embed.tasks.create(model_name=self.embed_model, video_url=video_url)
            task_id = task.id
            if not task_id:
                return "No embedding task id returned"

            # Video embedding is asynchronous: poll the task status until it is terminal
            # (`ready` or `failed`), bounded by `embed_timeout` so the tool never blocks forever.
            deadline = time.monotonic() + self.embed_timeout
            status = self.client.embed.tasks.status(task_id).status
            while status not in ("ready", "failed"):
                if time.monotonic() >= deadline:
                    return f"Video embedding task timed out after {self.embed_timeout:.0f}s (status: {status})"
                time.sleep(self.embed_poll_interval)
                status = self.client.embed.tasks.status(task_id).status
            if status != "ready":
                return f"Video embedding task did not complete (status: {status})"

            result = self.client.embed.tasks.retrieve(task_id=task_id)
            if result.video_embedding is None or not result.video_embedding.segments:
                return "No embedding returned"

            dimensions = 0
            segments: List[Dict[str, Any]] = []
            for segment in result.video_embedding.segments:
                vector = segment.float_
                if not vector:
                    continue
                if not dimensions:
                    dimensions = len(vector)
                # Only the segment metadata is returned. The raw float vectors are
                # deliberately omitted: Marengo emits one ~512-dim vector per 2-10s clip,
                # so a long video is hundreds of KB of floats that would flood (or exceed)
                # the model context, and the model cannot do anything useful with them.
                segments.append(
                    {
                        "start_offset_sec": segment.start_offset_sec,
                        "end_offset_sec": segment.end_offset_sec,
                        "embedding_scope": segment.embedding_scope,
                    }
                )
            if not segments:
                return "No embedding returned"

            return json.dumps(
                {
                    "model": self.embed_model,
                    "dimensions": dimensions,
                    "num_segments": len(segments),
                    "segments": segments,
                }
            )
        except Exception as e:
            log_error(f"Error embedding video {video_url}: {e}")
            return f"Error embedding video: {e}"
