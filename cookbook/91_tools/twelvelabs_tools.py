"""
TwelveLabs Tools
=============================

Demonstrates using TwelveLabs video understanding tools with an agent.

`analyze_video` answers questions about a video using the Pegasus model.
`embed_text` generates a multimodal (Marengo) embedding that lives in the same
latent space as TwelveLabs video/audio/image embeddings.
`embed_video` embeds a whole video into the same Marengo latent space (one vector
per 2-10s segment). It is long-running (async task polling) so it is opt-in
(`enable_embed_video=True`), and it returns a compact summary of the segmentation
(segment count, dimensions and per-segment time offsets) rather than the raw
vectors, which would flood the model context.

Set your API key first: `export TWELVELABS_API_KEY=...`
Grab a free key at https://twelvelabs.io.

Install dependencies: `pip install twelvelabs`
"""

from agno.agent import Agent
from agno.tools.twelvelabs import TwelveLabsTools

# Example 1: Enable all tools
agent = Agent(
    tools=[TwelveLabsTools(all=True)],
    markdown=True,
)

agent.print_response(
    "What is happening in this video? https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
)

# Example 2: Enable only text embedding (useful for embedding search queries
# against a TwelveLabs video index)
embedding_agent = Agent(
    tools=[
        TwelveLabsTools(
            enable_analyze_video=False,
            enable_embed_text=True,
        )
    ],
    markdown=True,
)

embedding_agent.print_response(
    "Embed the text 'a cat playing piano' and tell me how many dimensions it has."
)

# Example 3: Embed a whole video with Marengo (one vector per segment). This is
# asynchronous under the hood — the tool waits for the embedding task to finish.
video_embedding_agent = Agent(
    tools=[
        TwelveLabsTools(
            enable_analyze_video=False,
            enable_embed_text=False,
            enable_embed_video=True,
        )
    ],
    markdown=True,
)

video_embedding_agent.print_response(
    "Embed this video and tell me how many segments and dimensions it has: "
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"
)
