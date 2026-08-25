"""Types for OpenAI request parameters whose value set grows with each model release.

Every alias names the values OpenAI documents today and also accepts any other string, so a value
introduced by a later model works without an agno release. Editors keep offering the named values
as completions. Which of them a request may use depends on the model and the endpoint, and the API
rejects a value the target model does not support.
"""

from typing import Literal, Union

__all__ = [
    "ReasoningEffort",
    "ReasoningSummary",
    "ServiceTier",
    "Verbosity",
]

# How much the model thinks before it answers. The values a model takes are listed on its model
# page. See https://platform.openai.com/docs/guides/reasoning
ReasoningEffort = Union[Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"], str]

# Level of detail of the reasoning summary returned with the response. "auto" gives the most
# detailed summary a model offers.
ReasoningSummary = Union[Literal["auto", "concise", "detailed"], str]

# Processing tier that serves the request. The tiers an account may use vary, and "ultrafast" is
# Responses only.
ServiceTier = Union[Literal["auto", "default", "flex", "scale", "priority", "fast", "ultrafast"], str]

# Length of the answer, from terse to expansive.
Verbosity = Union[Literal["low", "medium", "high"], str]
