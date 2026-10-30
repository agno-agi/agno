import re
from typing import Any, Dict

from agno.utils.log import log_warning

# The o-series and the gpt-5 family that ships as gpt-5, gpt-5-mini, gpt-5-nano and gpt-5-pro
# only accept the default sampling values; gpt-5.1 and later take the full set again.
_FIXED_SAMPLING_MODEL_RE = re.compile(r"^(o\d|gpt-5(-|$))")

# What the API answers for each parameter on those models: only the default value, or nothing.
_DEFAULT_ONLY = {"temperature": 1, "top_p": 1, "presence_penalty": 0, "frequency_penalty": 0}
_NEVER = ("logit_bias", "logprobs", "top_logprobs", "stop")


def has_fixed_sampling_params(model_id: str) -> bool:
    """Return True if the model rejects any non-default sampling parameter with a 400."""
    return _FIXED_SAMPLING_MODEL_RE.match(model_id) is not None


def drop_fixed_sampling_params(request_params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove the sampling parameters a fixed-sampling model would reject.

    ``temperature`` and ``top_p`` survive only at 1, ``presence_penalty`` and ``frequency_penalty``
    only at 0; ``logit_bias``, ``logprobs``, ``top_logprobs`` and ``stop`` never do. ``max_tokens``
    becomes ``max_completion_tokens`` when that is not set, as the API's own error suggests.
    A value that would have been rejected is dropped with a warning, so a ``temperature=0``
    carried over from an older configuration degrades to the default instead of failing every
    request. Mutates and returns the dict it is given.
    """
    dropped = []
    for name, default in _DEFAULT_ONLY.items():
        if name in request_params and request_params[name] != default:
            dropped.append(f"{name}={request_params.pop(name)}")
    for name in _NEVER:
        if name in request_params:
            dropped.append(f"{name}={request_params.pop(name)}")
    if "max_tokens" in request_params:
        max_tokens = request_params.pop("max_tokens")
        if "max_completion_tokens" not in request_params:
            request_params["max_completion_tokens"] = max_tokens
        dropped.append(f"max_tokens={max_tokens} (sent as max_completion_tokens)")
    if dropped:
        log_warning(
            f"Dropping {', '.join(dropped)} from the request: this model only accepts the default sampling "
            "values. Unset them to silence this warning."
        )
    return request_params
