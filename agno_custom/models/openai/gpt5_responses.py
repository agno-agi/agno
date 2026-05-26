"""
GPT-5 on the Responses API with reasoning + tools requires chaining: each function_call in
`input` must be accompanied by its reasoning item unless we continue from `previous_response_id`
and only send the new tail (same pattern Agno uses for o3/o4-mini in OpenAIResponses).

Also:
- Bind `response_id` on `response.completed` (Agno only set it on `response.created`; the final
  text-only assistant turn often missed `response_id`, so the next request chained from the wrong
  response and re-sent `function_call` rows without `rs_*`).
- If history has no `response_id` (e.g. persisted chat), strip assistant `tool_calls` and **drop**
  `tool` messages so we do not replay `function_call` / `function_call_output` pairs the API cannot
  resolve (remapped `call_*` outputs would otherwise orphan after tool_calls are stripped).
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from agno.models.base import MessageData
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses
from agno.models.response import ModelResponse
from agno.utils.log import log_debug
from pydantic import BaseModel


@dataclass
class GPT5ReasoningOpenAIResponses(OpenAIResponses):
    """Extends Agno OpenAIResponses for GPT-5.* + reasoning multi-turn / tool loops."""

    def _gpt5_with_reasoning(self) -> bool:
        return (self.id or "").lower().startswith("gpt-5") and bool(self.reasoning)

    @staticmethod
    def _is_chain_anchor_role(m: Message) -> bool:
        return getattr(m, "role", None) in ("assistant", "model")

    @staticmethod
    def _index_last_assistant_with_response_id(messages: List[Message]) -> Optional[int]:
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if not GPT5ReasoningOpenAIResponses._is_chain_anchor_role(m):
                continue
            pd = getattr(m, "provider_data", None) or {}
            if pd.get("response_id"):
                return i
        return None

    def get_request_params(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        request_params = super().get_request_params(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )
        if not self._gpt5_with_reasoning():
            return request_params

        # Persist response state so follow-up turns can use previous_response_id.
        request_params["store"] = True
        cut = self._index_last_assistant_with_response_id(messages)
        if cut is not None:
            prev_id = (getattr(messages[cut], "provider_data", None) or {}).get("response_id")
            if prev_id:
                request_params["previous_response_id"] = prev_id
                log_debug(f"GPT-5 Responses API: chaining previous_response_id={prev_id}")
        return request_params

    @staticmethod
    def _normalize_tool_property_type(prop: Dict[str, Any]) -> None:
        """
        Agno's Responses API formatter assumes every JSON-schema property has a top-level
        ``type`` key. Optional / union params from ``get_json_schema`` use ``anyOf`` instead,
        which raises KeyError('type') when formatting tools (e.g. shoplc_product_search).
        """
        prop_type = prop.get("type")
        if isinstance(prop_type, list):
            non_null = [t for t in prop_type if t != "null"]
            prop["type"] = non_null[0] if non_null else (prop_type[0] if prop_type else "string")
            return
        if prop_type is not None:
            return
        for key in ("anyOf", "oneOf"):
            variants = prop.get(key)
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                vt = variant.get("type")
                if isinstance(vt, list):
                    non_null = [t for t in vt if t != "null"]
                    vt = non_null[0] if non_null else (vt[0] if vt else None)
                if vt and vt != "null":
                    prop["type"] = vt
                    return

    @classmethod
    def _normalize_tools_for_responses_api(cls, tools: List[Dict[str, Any]]) -> None:
        for _tool in tools:
            if _tool.get("type") != "function":
                continue
            function_def = _tool.get("function") or {}
            parameters = function_def.get("parameters") or {}
            for prop in (parameters.get("properties") or {}).values():
                if isinstance(prop, dict):
                    cls._normalize_tool_property_type(prop)

    def _format_tool_params(
        self, messages: List[Message], tools: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        if tools:
            self._normalize_tools_for_responses_api(tools)
        return super()._format_tool_params(messages=messages, tools=tools)

    @staticmethod
    def _strip_assistant_tool_calls_when_no_response_chain(messages: List[Message]) -> List[Message]:
        """
        Avoid replaying function_call / rs_* rows when provider_data was lost (e.g. DB).

        OpenAIChat may have already remapped tool_message.tool_call_id to call_*; if we strip
        assistant tool_calls we must not leave orphan function_call_output items.
        """
        out: List[Message] = []
        for m in messages:
            if getattr(m, "role", None) == "tool":
                continue
            if GPT5ReasoningOpenAIResponses._is_chain_anchor_role(m) and getattr(m, "tool_calls", None):
                mc = copy(m)
                mc.tool_calls = None
                out.append(mc)
            else:
                out.append(m)
        return out

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        msgs = list(messages)
        if self._gpt5_with_reasoning():
            cut = self._index_last_assistant_with_response_id(msgs)
            if cut is not None:
                msgs = msgs[cut + 1 :]
                log_debug(f"GPT-5 Responses API: sending {len(msgs)} input item(s) after stored response")
            else:
                msgs = self._strip_assistant_tool_calls_when_no_response_chain(msgs)
                log_debug(
                    "GPT-5 Responses API: no response_id in history; stripped assistant tool_calls "
                    f"and dropped tool rows for safe replay ({len(msgs)} messages)"
                )
        return super()._format_messages(msgs)

    def _process_stream_response(
        self,
        stream_event: Any,
        assistant_message: Message,
        stream_data: MessageData,
        tool_use: Dict[str, Any],
    ) -> Tuple[Optional[ModelResponse], Dict[str, Any]]:
        model_response, tool_use = super()._process_stream_response(
            stream_event, assistant_message, stream_data, tool_use
        )
        # Agno only set response_id on response.created; ensure completed carries id for text-only turns.
        if getattr(stream_event, "type", None) == "response.completed":
            resp = getattr(stream_event, "response", None)
            rid = getattr(resp, "id", None) if resp is not None else None
            if rid:
                if stream_data.response_provider_data is None:
                    stream_data.response_provider_data = {}
                stream_data.response_provider_data["response_id"] = rid
                log_debug(f"GPT-5 Responses API: response_id from response.completed: {rid}")
        return model_response, tool_use
