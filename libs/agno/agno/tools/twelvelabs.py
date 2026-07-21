import json
from os import getenv
from typing import Any, List, Optional

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

    It exposes two opt-in capabilities for agents:
      - `analyze_video`: ask a natural-language question about a video and get a text answer
        back, powered by the Pegasus video understanding model.
      - `embed_text`: generate a multimodal embedding for a piece of text using the Marengo
        model. Marengo embeds text, video, audio and images into the same latent space, so
        these vectors can be used to search a video corpus by text.

    Args:
        api_key (Optional[str]): TwelveLabs API key. Read from the `TWELVELABS_API_KEY`
            environment variable if not provided.
        analyze_model (str): The Pegasus model used for `analyze_video`. Default is "pegasus1.5".
        embed_model (str): The Marengo model used for `embed_text`. Default is "marengo3.0".
        max_tokens (int): Maximum number of tokens for `analyze_video` responses. Default is 2048.
        enable_analyze_video (bool): Enable the `analyze_video` tool. Default is True.
        enable_embed_text (bool): Enable the `embed_text` tool. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        analyze_model: str = "pegasus1.5",
        embed_model: str = "marengo3.0",
        max_tokens: int = 2048,
        enable_analyze_video: bool = True,
        enable_embed_text: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("TWELVELABS_API_KEY")
        if not self.api_key:
            logger.warning("No TwelveLabs API key provided. Set TWELVELABS_API_KEY or pass api_key.")

        self.analyze_model = analyze_model
        self.embed_model = embed_model
        self.max_tokens = max_tokens
        self._client: Optional[TwelveLabs] = None

        tools: List[Any] = []
        if all or enable_analyze_video:
            tools.append(self.analyze_video)
        if all or enable_embed_text:
            tools.append(self.embed_text)

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
