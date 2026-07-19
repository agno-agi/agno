"""Model identity payload -- private; shared with agno.environments.

The judge is part of the reward function, and the policy fingerprint identifies the
model under test: both need the same answer to "which model is this?", so the payload
is built once here. agno.environments imports it -- the allowed direction; scorer
imports neither eval nor environments.
"""

from typing import Any, Dict

from agno.models.base import Model

# The named sampling params that make two same-id models different policies.
SAMPLING_PARAMS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_output_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "reasoning_effort",
    "seed",
    "stop",
)


def model_identity_payload(model: Model) -> Dict[str, Any]:
    """Class qualname, id, provider, base_url, and the named sampling params, None-skipped.

    Explicitly excluded: api_key (key rotation is not policy drift), headers, and
    client objects.
    """
    payload: Dict[str, Any] = {
        "class": type(model).__qualname__,
        "id": model.id,
        "provider": model.provider,
        "base_url": str(getattr(model, "base_url", None)),
    }
    for param in SAMPLING_PARAMS:
        value = getattr(model, param, None)
        if value is not None:
            payload[param] = value
    return payload
