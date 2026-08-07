"""Unit tests for the model identity payload (agno.scorer._model).

The payload enumerates public attributes and excludes what provably is not policy;
these tests pin both directions -- request-shaping params split payloads, plumbing
does not -- and the drift pins fail when a provider class gains a field that has not
been classified yet.
"""

from agno.metrics import ModelType
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.scorer import JudgeScorer
from agno.scorer._model import fingerprint_fields, model_identity_payload, model_prompt_payload


def test_output_affecting_params_split_payloads():
    # The allowlist hole the enumeration closes: params that change the sampled
    # output must change the payload.
    plain = model_identity_payload(OpenAIResponses(id="gpt-5.5"))
    assert plain != model_identity_payload(OpenAIResponses(id="gpt-5.5", verbosity="high"))
    assert plain != model_identity_payload(OpenAIResponses(id="gpt-5.5", reasoning={"effort": "high"}))
    assert plain != model_identity_payload(OpenAIResponses(id="gpt-5.5", temperature=0.0))
    chat_plain = model_identity_payload(OpenAIChat(id="gpt-5.5"))
    assert chat_plain != model_identity_payload(OpenAIChat(id="gpt-5.5", logit_bias={"1234": -100}))


def test_credentials_and_clients_do_not_split():
    # Key rotation is not policy drift -- by name for the fields this module knows,
    # by pattern for provider fields it has never seen.
    assert model_identity_payload(OpenAIResponses(id="gpt-5.5", api_key="sk-a")) == model_identity_payload(
        OpenAIResponses(id="gpt-5.5", api_key="sk-b")
    )
    with_foreign_credentials = OpenAIResponses(id="gpt-5.5")
    with_foreign_credentials.aws_secret_access_key = "x"  # type: ignore[attr-defined]
    with_foreign_credentials.azure_ad_token = "y"  # type: ignore[attr-defined]
    assert model_identity_payload(with_foreign_credentials) == model_identity_payload(OpenAIResponses(id="gpt-5.5"))


def test_runtime_and_local_behavior_fields_do_not_split():
    # model_type is stamped in place by agent init: the same config must not hash
    # differently before and after its first run. The cache/retry knobs are local
    # client behavior, not the sampled distribution.
    ran = OpenAIResponses(id="gpt-5.5")
    ran.model_type = ModelType.OUTPUT_MODEL
    assert model_identity_payload(ran) == model_identity_payload(OpenAIResponses(id="gpt-5.5"))
    assert model_identity_payload(OpenAIResponses(id="gpt-5.5", cache_response=True)) == model_identity_payload(
        OpenAIResponses(id="gpt-5.5")
    )
    # Provider-side bookkeeping: request tags, response storage, and the
    # abuse-attribution user id never shape the sampled distribution, and they
    # routinely differ between otherwise-identical baseline and current runs.
    plain = model_identity_payload(OpenAIResponses(id="gpt-5.5"))
    assert model_identity_payload(OpenAIResponses(id="gpt-5.5", metadata={"run": "a"})) == plain
    assert model_identity_payload(OpenAIResponses(id="gpt-5.5", store=True)) == plain
    assert model_identity_payload(OpenAIResponses(id="gpt-5.5", user="tenant-42")) == plain


def test_prompt_fields_are_env_not_policy():
    prompted = OpenAIResponses(id="gpt-5.5", system_prompt="You are a pirate.", instructions=["Answer in French."])
    plain = OpenAIResponses(id="gpt-5.5")
    assert model_identity_payload(prompted) == model_identity_payload(plain)
    assert model_prompt_payload(prompted) != model_prompt_payload(plain)
    # No-model and default-model agents hash identically on the env side.
    assert model_prompt_payload(None) == model_prompt_payload(plain)


def test_unserializable_value_recorded_by_name():
    exotic = OpenAIResponses(id="gpt-5.5", extra_body={"handle": object()})
    payload = model_identity_payload(exotic)
    assert "extra_body" not in payload
    assert payload["unserializable_params"] == ["extra_body"]


def test_judge_digest_covers_enumerated_params_and_prompts():
    def digest(model):
        return JudgeScorer(model=model, criteria="Answer is correct.").digest()

    assert digest(OpenAIResponses(id="gpt-5.5", verbosity="low")) != digest(
        OpenAIResponses(id="gpt-5.5", verbosity="high")
    )
    assert digest(OpenAIResponses(id="gpt-5.5", system_prompt="Be lenient.")) != digest(
        OpenAIResponses(id="gpt-5.5", system_prompt="Be brutal.")
    )
    assert digest(OpenAIResponses(id="gpt-5.5")) == digest(OpenAIResponses(id="gpt-5.5"))


# ---------------------------------------------------------------------------
# Drift pins: a new upstream field fails here until it is classified
# ---------------------------------------------------------------------------

# Message-role fields (assistant_message_role, role_map, tool_message_role) are
# enumerated policy: they relabel every message's wire role, which changes the
# sampled distribution -- see the note on _LOCAL_BEHAVIOR_FIELDS in agno.scorer._model.
_PINNED_OPENAI_RESPONSES_FIELDS = [
    "assistant_message_role",
    "background",
    "extra_body",
    "include",
    "max_output_tokens",
    "max_tool_calls",
    "parallel_tool_calls",
    "reasoning",
    "reasoning_effort",
    "reasoning_summary",
    "request_params",
    "role_map",
    "service_tier",
    "strict_output",
    "temperature",
    "tool_message_role",
    "top_p",
    "truncation",
    "verbosity",
]

_PINNED_OPENAI_CHAT_FIELDS = [
    "assistant_message_role",
    "audio",
    "extra_body",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "max_completion_tokens",
    "max_tokens",
    "modalities",
    "presence_penalty",
    "reasoning_effort",
    "request_params",
    "role_map",
    "seed",
    "service_tier",
    "stop",
    "strict_output",
    "temperature",
    "tool_message_role",
    "top_logprobs",
    "top_p",
    "verbosity",
]


def test_fingerprint_field_classification_pinned():
    # When this fails, a provider gained (or lost) a public field: decide whether it
    # is policy (leave it enumerated, update the pin) or plumbing (add it to the
    # exclusion groups in agno.scorer._model), then update the pin. Do not blindly
    # re-pin -- the decision is the point.
    assert fingerprint_fields(OpenAIResponses(id="gpt-5.5")) == _PINNED_OPENAI_RESPONSES_FIELDS
    assert fingerprint_fields(OpenAIChat(id="gpt-5.5")) == _PINNED_OPENAI_CHAT_FIELDS
