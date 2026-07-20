"""Run an agno agent on a Tinker checkpoint.

`TinkerModel` wraps a Tinker sampling client as an `agno.models.Model`, which is what
lets `run_rollouts(env, model=...)` measure a real pass rate for a base model and for
the checkpoint trained from it. It is the half of the loop that turns a training
receipt into a measurement.

**Scope.** This first cut targets text tasks (haiku, math, format transfer). Tool
calling through the renderer depends on its function-calling support and is a
follow-up, so tool-call parts in a parsed response are not surfaced here.

**Import style is a deliberate deviation.** Every other adapter in `agno/models/`
imports its SDK at module level inside a try/except. This one imports `tinker` and
`tinker_cookbook` lazily, *inside* methods, so the module imports cleanly with the SDK
uninstalled and its tests can inject fake clients. That is load-bearing for the offline
test contract -- do not "fix" it to the module-level guard convention.
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_warning

# A sample that did not end on a stop sequence was cut off mid-answer; the renderer
# reports it and we refuse to pass the fragment off as an answer.
_CLEAN_TERMINATIONS = frozenset({"stop_sequence", "eos"})

# Sampling clients and renderers, shared across every attempt of a run.
#
# The rollout engine shallow-copies the model per attempt, and `copy.copy` gives the
# copy its own __dict__ -- so a client lazily assigned to `self` lands on the throwaway
# copy and the next attempt starts from None again. Without this cache every single
# attempt would build a fresh ServiceClient, JWT exchange, session and sampler: five
# network round trips before the first token, hundreds of sessions per round.
#
# Keyed on what actually identifies a sampler. A duplicate build under concurrency is
# harmless (last writer wins, both are equivalent), so no lock.
_SAMPLING_CLIENTS: Dict[Tuple[str, Optional[str]], Any] = {}
_RENDERERS: Dict[str, Any] = {}


class TinkerModel(Model):
    """An agno Model backed by a Tinker sampling client.

    `model_path` selects a tuned checkpoint; leaving it None samples the untuned base.
    The `id` is derived from both and never passed in, because the policy fingerprint
    is built from `{class, id, provider, base_url, request-params}`: if base and tuned
    shared an id they would fingerprint identically, and a before/after would report
    `policy_changed=False` while the pass rate moved. Conversely `system_prompt` and
    `instructions` stay None -- those are model-level *prompt* fields, which fold into
    the ENVIRONMENT fingerprint, and base and tuned must agree there or `diff()` raises
    instead of measuring.
    """

    def __init__(
        self,
        base_model: str,
        *,
        model_path: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        seed: Optional[int] = None,
        sampling_client: Optional[Any] = None,
        renderer: Optional[Any] = None,
    ) -> None:
        super().__init__(
            id=base_model if model_path is None else f"{base_model}@{model_path}",
            name=base_model,
            provider="Tinker",
        )
        self.base_model = base_model
        self.model_path = model_path
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Default None, and it must stay that way for a rollout: a fixed seed makes all
        # k attempts identical, every task unanimous, the learning zone empty by
        # construction, and the loop reports "converged" having trained nothing.
        self.seed = seed
        # Underscore-private: the identity payload skips underscored attributes, and
        # names matching credential markers (client) are excluded outright.
        self._sampling_client = sampling_client
        self._renderer = renderer

    # -- lazy SDK wiring ---------------------------------------------------------

    def _get_sampling_client(self) -> Any:
        if self._sampling_client is not None:
            return self._sampling_client
        key = (self.base_model, self.model_path)
        client = _SAMPLING_CLIENTS.get(key)
        if client is None:
            import tinker

            service_client = tinker.ServiceClient()
            if self.model_path is not None:
                client = service_client.create_sampling_client(model_path=self.model_path)
            else:
                client = service_client.create_sampling_client(base_model=self.base_model)
            _SAMPLING_CLIENTS[key] = client
        return client

    def _get_renderer(self) -> Any:
        if self._renderer is not None:
            return self._renderer
        renderer = _RENDERERS.get(self.base_model)
        if renderer is None:
            from tinker_cookbook.model_info import get_recommended_renderer_name
            from tinker_cookbook.renderers import get_renderer

            tokenizer = self._get_sampling_client().get_tokenizer()
            renderer = get_renderer(get_recommended_renderer_name(self.base_model), tokenizer)
            _RENDERERS[self.base_model] = renderer
        return renderer

    def _sampling_params(self, renderer: Any) -> Any:
        from tinker import types

        return types.SamplingParams(
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            seed=self.seed,
            # Without the renderer's stop sequences a Qwen sample never terminates at
            # <|im_end|> and every parse comes back unclean.
            stop=renderer.get_stop_sequences(),
        )

    # -- sampling ----------------------------------------------------------------

    def _sample(self, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> ModelResponse:
        """One blocking sample. Called directly by the sync doors, off-thread by async."""
        if kwargs.get("tools"):
            # Tool calling is a documented follow-up. Failing loudly here is the point:
            # sampling anyway returns a tool call the adapter cannot represent, which
            # parses to empty visible text, terminates CLEANLY, and is therefore SCORED
            # as a wrong answer -- a whole env printing a plausible 0.0 pass rate.
            raise ValueError(
                "TinkerModel does not support tool calling yet; this environment's agent declares tools. "
                "Use a text-answer environment, or serve the checkpoint through a tool-capable adapter."
            )

        renderer = self._get_renderer()
        client = self._get_sampling_client()
        prompt = renderer.build_generation_prompt(_to_renderer_messages(_messages_from(args, kwargs)))

        response = client.sample(
            prompt=prompt,
            num_samples=1,
            sampling_params=self._sampling_params(renderer),
        ).result()

        sequences = getattr(response, "sequences", None)
        if not sequences:
            raise ValueError("Tinker returned no sampled sequences")

        message, termination = renderer.parse_response(list(sequences[0].tokens))
        if not _is_clean(termination):
            # An unclean sample is a fragment, not an answer. Raising makes the attempt
            # errored and unscored -- visible in n_scored, never silently counted as a
            # wrong answer.
            log_warning(
                f"TinkerModel sample did not terminate cleanly ({termination}); "
                f"raise max_tokens above {self.max_tokens} if this repeats"
            )
            raise ValueError(f"Tinker returned an unclean sample ({termination})")

        if isinstance(message, dict) and message.get("tool_calls"):
            # The renderer parsed a tool call even though none were offered. Raising
            # makes it an errored (unscored) attempt rather than an empty answer scored
            # as wrong.
            log_warning("TinkerModel received a sample containing a tool call, which it cannot represent")
            raise ValueError("Tinker returned a tool call; TinkerModel supports text answers only")

        content, reasoning = _split_content(message)
        return ModelResponse(role="assistant", content=content, reasoning_content=reasoning)

    # -- the six abstract methods ------------------------------------------------

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._sample(args, kwargs)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        # A Tinker sample is a network call of seconds to tens of seconds. Called
        # inline it would serialize every concurrent attempt and make the engine's
        # per-attempt timeout unenforceable.
        return await asyncio.to_thread(self._sample, args, kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._sample(args, kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield await asyncio.to_thread(self._sample, args, kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        # `_sample` already returns a complete ModelResponse.
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _messages_from(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> List[Message]:
    """The engine calls through by keyword; accept a positional list defensively."""
    candidate = kwargs.get("messages")
    if candidate is None:
        for value in args:
            if isinstance(value, list) and value and all(isinstance(item, Message) for item in value):
                candidate = value
                break
    if not candidate:
        # Failing open would sample from an empty prompt: a clean, plausible,
        # task-unrelated answer that scores normally and makes a whole measured pass
        # rate meaningless, with nothing anywhere saying so.
        raise ValueError("TinkerModel was invoked with no messages; nothing to sample from")
    return candidate


def _to_renderer_messages(messages: List[Message]) -> List[Dict[str, str]]:
    """agno messages to the renderer's plain role/content dicts."""
    converted: List[Dict[str, str]] = []
    for message in messages:
        role = getattr(message, "role", None)
        if role not in ("system", "user", "assistant"):
            # Tool turns have no representation on this path; tool-calling through the
            # renderer is a follow-up.
            continue
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            content = message.get_content_string() if hasattr(message, "get_content_string") else str(content or "")
        converted.append({"role": role, "content": content})
    return converted


def _split_content(message: Any) -> Tuple[str, Optional[str]]:
    """The visible answer byte-for-byte, with reasoning separated out.

    `parse_response` returns content as either a string or a list of typed parts --
    and on thinking models (Qwen3, i.e. essentially every real sample here) the
    renderer rewrites it into parts. A str-only assumption passes every offline test
    and breaks on the first live sample.

    Note the two parts carry their text under different keys: `TextPart` uses "text",
    `ThinkingPart` uses "thinking". Joined with no separator and never stripped, so
    what reaches `Message.content` -- and therefore the exported dataset -- is exactly
    what the model emitted.
    """
    content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content, None

    visible: List[str] = []
    thinking: List[str] = []
    for part in content or []:
        kind = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
        if kind == "text":
            visible.append(_part_field(part, "text"))
        elif kind == "thinking":
            thinking.append(_part_field(part, "thinking"))
    reasoning = "".join(thinking)
    return "".join(visible), (reasoning or None)


def _part_field(part: Any, field: str) -> str:
    value = part.get(field, "") if isinstance(part, dict) else getattr(part, field, "")
    return value if isinstance(value, str) else ""


def _is_clean(termination: Any) -> bool:
    """`ParseTermination` exposes is_clean; fall back to its string form."""
    explicit = getattr(termination, "is_clean", None)
    if isinstance(explicit, bool):
        return explicit
    return str(termination) in _CLEAN_TERMINATIONS
