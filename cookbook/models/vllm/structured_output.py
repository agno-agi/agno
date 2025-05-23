"""Quick start with Nous-Hermes-2 (Mistral-7B-DPO) running on vLLM.

Prerequisites
-------------
Launch the server (needs ~10 GB RAM for 8 K context, increase VLLM_CPU_KVCACHE_SPACE for larger):

```bash
# 8 K context on CPU
vllm serve NousResearch/Nous-Hermes-2-Mistral-7B-DPO \
  --dtype float32 \
  --max-model-len 8192 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

Then run this script.
"""

from typing import List

from agno.agent import Agent
from agno.models.vllm import Vllm
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


agent = Agent(
    model=Vllm(id="NousResearch/Nous-Hermes-2-Mistral-7B-DPO"),
    description="You write movie scripts.",
    response_model=MovieScript,
)

agent.print_response(
    "A movie about a young woman who discovers she has the ability to time travel."
)
