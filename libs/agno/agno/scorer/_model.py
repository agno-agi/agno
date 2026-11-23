"""Model identity payload -- private; shared with agno.environments.

The judge is part of the scoring rule, and the policy fingerprint identifies the
model under test: both need the same answer to "which model is this?", so the payload
is built once here. agno.environments imports it -- the allowed direction; scorer
imports neither eval nor environments.

The payload enumerates the model's public attributes and excludes what provably is
not policy: ~50 provider classes each carry their own request-shaping fields
(verbosity, logit_bias, reasoning, ...), an open set no fixed allowlist can track.
The exclusion groups below
are pinned by a drift test over the shipped OpenAI classes, so a new upstream field
must be classified before it ships.
"""

import json
from typing import Any, Dict, List, Optional

from agno.models.base import Model

# Connection plumbing: never policy, and often non-serializable once populated.
_INFRASTRUCTURE_FIELDS = frozenset(
    {
        "api_key",
        "organization",
        "timeout",
        "max_retries",
        "default_headers",
        "default_query",
        "extra_headers",
        "extra_query",
        "http_client",
        "client",
        "async_client",
        "client_params",
    }
)

# Assigned by agno at run time (get_models stamps model_type in place), so the same
# config would hash differently before and after its first run.
_RUNTIME_FIELDS = frozenset({"model_type"})

# Local client behavior -- retries, response cache, display names, capability
# flags -- plus provider-side bookkeeping (metadata request tags, store, the
# abuse-attribution user id). None of it changes the sampled distribution.
# service_tier is NOT here: it routes requests to different processing
# infrastructure and is not provably output-neutral, so it stays enumerated.
# Message-role fields (role_map, tool_message_role, assistant_message_role) are NOT
# here either: providers relabel every message's wire role through them (e.g. a
# system prompt sent as a user turn), which changes the sampled distribution, so
# they are policy identity and stay enumerated.
_LOCAL_BEHAVIOR_FIELDS = frozenset(
    {
        "retries",
        "delay_between_retries",
        "exponential_backoff",
        "retry_with_guidance",
        "retry_with_guidance_limit",
        "cache_response",
        "cache_ttl",
        "cache_dir",
        "background_poll_interval",
        "background_max_wait",
        "vector_store_name",
        "collect_metrics_on_completion",
        "name",
        "supports_native_structured_outputs",
        "supports_json_schema_outputs",
        "metadata",
        "store",
        "user",
    }
)

# Prompt-shaped model fields are environment, not policy: they change what the model
# is asked, not which policy answers. They enter the env fingerprint through
# model_prompt_payload, exactly like agent-level instructions.
PROMPT_FIELDS = ("system_prompt", "instructions")

# Credential-bearing names on provider classes this module has never seen: excluded
# by pattern so key rotation never flips a policy fingerprint. "_token" (singular)
# deliberately does not match max_tokens/max_output_tokens.
_CREDENTIAL_MARKERS = ("key", "secret", "password", "credential", "header", "client", "proxy")
_CREDENTIAL_SUFFIXES = ("_token",)


def _excluded(name: str) -> bool:
    if name.startswith("_"):
        return True
    if name in _INFRASTRUCTURE_FIELDS or name in _RUNTIME_FIELDS or name in _LOCAL_BEHAVIOR_FIELDS:
        return True
    if name in PROMPT_FIELDS:
        return True
    if any(marker in name for marker in _CREDENTIAL_MARKERS):
        return True
    if name == "token" or name.endswith(_CREDENTIAL_SUFFIXES):
        return True
    return False


def fingerprint_fields(model: Model) -> List[str]:
    """The enumerated payload field names for this instance, sorted.

    Exposed for the drift test: pinning this list per shipped class makes a new
    upstream field fail CI until it is classified. id/provider/base_url are handled
    explicitly by model_identity_payload and are not repeated here.
    """
    return sorted(name for name in vars(model) if not _excluded(name) and name not in ("id", "provider", "base_url"))


def model_identity_payload(model: Model) -> Dict[str, Any]:
    """Class qualname, id, provider, base_url, and every public request-shaping
    attribute, None-skipped.

    Excluded, by group: credentials/clients/headers (key rotation is not policy
    drift), retry/cache/display knobs (local behavior, not the sampled
    distribution), model_type (runtime-assigned), and the prompt-shaped fields
    (environment, not policy -- see model_prompt_payload). A non-JSON-serializable
    value cannot enter the hash without risking repr-embedded addresses, so its
    NAME is recorded under "unserializable_params" instead: presence still
    fingerprints, the value does not.
    """
    payload: Dict[str, Any] = {
        "class": type(model).__qualname__,
        "id": model.id,
        "provider": model.provider,
        "base_url": str(getattr(model, "base_url", None)),
    }
    unserializable: List[str] = []
    for param in fingerprint_fields(model):
        value = getattr(model, param, None)
        if value is None:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            unserializable.append(param)
            continue
        payload[param] = value
    if unserializable:
        payload["unserializable_params"] = unserializable
    return payload


def model_prompt_payload(model: Optional[Model]) -> Dict[str, Any]:
    """The prompt-shaped model fields, for the ENV fingerprint.

    Normalized so a model-less agent and one on a default model hash identically:
    both keys are present and None in either case.
    """
    if model is None:
        return {"system_prompt": None, "instructions": None}
    instructions = getattr(model, "instructions", None)
    return {
        "system_prompt": getattr(model, "system_prompt", None),
        "instructions": list(instructions) if isinstance(instructions, (list, tuple)) else instructions,
    }
