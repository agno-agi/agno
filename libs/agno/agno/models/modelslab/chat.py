from dataclasses import dataclass, field
from typing import Optional

from agno.models.openai.chat import OpenAIChat


@dataclass
class ModelsLab(OpenAIChat):
    """
    ModelsLab model provider for Agno.

    Provides uncensored Llama 3.1 language models via ModelsLab's
    OpenAI-compatible API. Ideal for AI agents that need unrestricted
    language generation, creative writing, or research without content filters.

    Models (128K context window):
        - ``llama-3.1-8b-uncensored`` — fast, efficient (default)
        - ``llama-3.1-70b-uncensored`` — higher quality, deeper reasoning

    Example::

        from agno.agent import Agent
        from agno.models.modelslab import ModelsLab

        agent = Agent(
            model=ModelsLab(
                id="llama-3.1-8b-uncensored",
                api_key="your-modelslab-api-key",
            ),
            instructions="You are a helpful coding assistant.",
        )
        agent.print_response("Write a Python function to merge two sorted lists.")

    Get your API key at: https://modelslab.com
    API docs: https://docs.modelslab.com/uncensored-chat
    """

    id: str = "llama-3.1-8b-uncensored"
    name: str = "ModelsLab"
    provider: str = "ModelsLab"

    # ModelsLab OpenAI-compatible endpoint
    base_url: str = "https://modelslab.com/uncensored-chat/v1"

    # Set via MODELSLAB_API_KEY env var or pass directly
    api_key: Optional[str] = None

    # ModelsLab's endpoint uses standard Bearer auth — same as OpenAI SDK default
    # No override needed.
