"""Deprecated: DalleTools has been consolidated into OpenAITools.

Use OpenAITools with the openai_generate_image method instead:

    from agno.tools.models.openai import OpenAITools

    agent = Agent(tools=[OpenAITools(generate_image=True)])
"""

import warnings


class DalleTools:
    """Deprecated: Use OpenAITools.openai_generate_image() instead."""

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "DalleTools is deprecated. Use OpenAITools(generate_image=True) instead. "
            "See: from agno.tools.models.openai import OpenAITools",
            DeprecationWarning,
            stacklevel=2,
        )
        raise ImportError("DalleTools has been removed. Use OpenAITools(generate_image=True) instead.")
