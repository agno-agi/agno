"""Send a local image or text file through Prime's native @file arguments.

Set PRIME_AGENT_IMAGE and/or PRIME_AGENT_FILE to existing local files.
Images require a model that supports image input. Non-image files are read as
UTF-8 text by Prime; this is not native PDF or audio/video understanding.
"""

from os import getenv

from agno.agents.prime import PrimeAgent
from agno.media import File, Image

agent = PrimeAgent(name="Prime Reader", cwd=getenv("PRIME_AGENT_CWD", "."))

if __name__ == "__main__":
    image_path = getenv("PRIME_AGENT_IMAGE")
    file_path = getenv("PRIME_AGENT_FILE")
    if not image_path and not file_path:
        raise ValueError("Set PRIME_AGENT_IMAGE or PRIME_AGENT_FILE to a local path")
    agent.print_response(
        "Describe the attached image and summarize the attached text, whichever is provided.",
        images=[Image(filepath=image_path)] if image_path else None,
        files=[File(filepath=file_path)] if file_path else None,
        stream=True,
    )
