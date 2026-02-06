from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

from agno.agent.trait.run_options import ReplayMode, ResolvedRunOptions
from agno.run.base import RunStatus

if TYPE_CHECKING:
    from agno.run import RunContext
    from agno.run.agent import RunOutput


RUN_ERROR_EVENT = "RunError"


@dataclass
class ReplayPayload:
    payload: Union[Dict[str, Any], str]
    encoding: str
    payload_bytes: int
    truncated: bool


def parse_replay_mode(mode: Optional[Union[str, ReplayMode]]) -> ReplayMode:
    if isinstance(mode, ReplayMode):
        return mode
    if isinstance(mode, str):
        normalised = mode.strip().lower()
        for replay_mode in ReplayMode:
            if replay_mode.value == normalised:
                return replay_mode
    return ReplayMode.OFF


def normalise_sample_rate(sample_rate: Optional[float]) -> float:
    if sample_rate is None:
        return 0.1
    if sample_rate < 0:
        return 0.0
    if sample_rate > 1:
        return 1.0
    return sample_rate


def should_record_replay(options: ResolvedRunOptions, status: RunStatus, run_id: Optional[str]) -> bool:
    if not options.replay_enabled:
        return False
    if options.replay_mode == ReplayMode.FULL:
        return True
    if options.replay_mode == ReplayMode.ERRORS_ONLY:
        return status in (RunStatus.error, RunStatus.cancelled)
    if options.replay_mode == ReplayMode.SAMPLED:
        if run_id is None:
            return False
        digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        return bucket < options.replay_sample_rate
    return False


def prepare_replay_record(
    *,
    run_response: RunOutput,
    run_context: Optional[RunContext],
    options: ResolvedRunOptions,
    phase_trace: Optional[Dict[str, Any]] = None,
    schema_version: int = 1,
) -> Optional[Dict[str, Any]]:
    status = _normalise_run_status(run_response.status)
    if not should_record_replay(options, status=status, run_id=run_response.run_id):
        return None

    payload_dict, truncated = _build_payload(
        run_response=run_response,
        run_context=run_context,
        options=options,
        phase_trace=phase_trace,
    )
    payload_obj = _enforce_payload_limit(
        payload=payload_dict,
        max_payload_bytes=options.replay_max_payload_bytes,
        max_message_chars=options.replay_max_message_chars,
    )
    truncated = truncated or payload_obj.truncated

    encoded_payload = _encode_payload(
        cast(Dict[str, Any], payload_obj.payload), compress=options.replay_compress_payload
    )
    now_ts = int(time())
    replay_status = _get_replay_status(run_response=run_response)

    return {
        "session_id": run_response.session_id,
        "agent_id": run_response.agent_id,
        "user_id": run_response.user_id,
        "team_id": getattr(run_response, "team_id", None),
        "workflow_id": run_response.workflow_id,
        "status": replay_status,
        "mode": options.replay_mode.value,
        "schema_version": schema_version,
        "payload_encoding": encoded_payload.encoding,
        "payload_bytes": encoded_payload.payload_bytes,
        "truncated": truncated,
        "created_at": now_ts,
        "updated_at": now_ts,
        "payload": encoded_payload.payload,
    }


def _build_payload(
    *,
    run_response: RunOutput,
    run_context: Optional[RunContext],
    options: ResolvedRunOptions,
    phase_trace: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], bool]:
    truncation_state = {"truncated": False}
    max_chars = options.replay_max_message_chars
    status = _normalise_run_status(run_response.status)

    model_metrics = run_response.metrics.to_dict() if run_response.metrics is not None else {}
    message_snapshot = _serialise_messages(
        run_response.messages, max_chars=max_chars, truncation_state=truncation_state
    )
    tool_snapshot = _serialise_tools(run_response.tools, max_chars=max_chars, truncation_state=truncation_state)
    error_taxonomy = _extract_error_taxonomy(run_response)

    payload: Dict[str, Any] = {
        "run_id": run_response.run_id,
        "status": status.value,
        "resolved_options": {
            "stream": options.stream,
            "stream_events": options.stream_events,
            "yield_run_output": options.yield_run_output,
            "add_history_to_context": options.add_history_to_context,
            "add_dependencies_to_context": options.add_dependencies_to_context,
            "add_session_state_to_context": options.add_session_state_to_context,
            "knowledge_filters": _truncate_value(options.knowledge_filters, max_chars, truncation_state),
            "output_schema": _truncate_value(_safe_schema_dump(options.output_schema), max_chars, truncation_state),
        },
        "model_request": {
            "model": run_response.model,
            "model_provider": run_response.model_provider,
            "metrics": model_metrics,
        },
        "final_messages": message_snapshot,
        "tool_calls": tool_snapshot,
        "timings": {
            "created_at": run_response.created_at,
            "duration": model_metrics.get("duration"),
            "time_to_first_token": model_metrics.get("time_to_first_token"),
        },
        "run_context": {
            "dependencies": _truncate_value(
                run_context.dependencies if run_context is not None else None, max_chars, truncation_state
            ),
            "knowledge_filters": _truncate_value(
                run_context.knowledge_filters if run_context is not None else None, max_chars, truncation_state
            ),
            "metadata": _truncate_value(
                run_context.metadata if run_context is not None else None, max_chars, truncation_state
            ),
        },
        "error_taxonomy": error_taxonomy,
        "phase_trace": phase_trace,
    }
    return payload, truncation_state["truncated"]


def _serialise_messages(
    messages: Optional[List[Any]], max_chars: int, truncation_state: Dict[str, bool]
) -> Optional[List[Dict[str, Any]]]:
    if not messages:
        return None

    serialised: List[Dict[str, Any]] = []
    for message in messages:
        message_dict: Dict[str, Any]
        if hasattr(message, "to_dict"):
            message_dict = message.to_dict()  # type: ignore[assignment]
        elif isinstance(message, dict):
            message_dict = dict(message)
        else:
            message_dict = {"content": str(message)}
        serialised.append(_truncate_value(message_dict, max_chars, truncation_state))
    return serialised


def _serialise_tools(
    tools: Optional[List[Any]], max_chars: int, truncation_state: Dict[str, bool]
) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None

    serialised: List[Dict[str, Any]] = []
    for tool in tools:
        tool_dict: Dict[str, Any]
        if hasattr(tool, "to_dict"):
            tool_dict = tool.to_dict()  # type: ignore[assignment]
        elif isinstance(tool, dict):
            tool_dict = dict(tool)
        else:
            tool_dict = {"result": str(tool)}
        serialised.append(_truncate_value(tool_dict, max_chars, truncation_state))
    return serialised


def _extract_error_taxonomy(run_response: RunOutput) -> Optional[Dict[str, Any]]:
    status = _normalise_run_status(run_response.status)
    if status not in (RunStatus.error, RunStatus.cancelled):
        return None

    error_event = None
    for event in run_response.events or []:
        event_name = getattr(event, "event", None)
        if event_name == RUN_ERROR_EVENT:
            error_event = event
            break

    content = run_response.content if isinstance(run_response.content, str) else None
    inferred_error_type = getattr(error_event, "error_type", None)
    if inferred_error_type is None and content is not None and "timeout" in content.lower():
        inferred_error_type = "timeout"

    return {
        "status": status.value,
        "error_type": inferred_error_type,
        "error_id": getattr(error_event, "error_id", None),
        "message": content,
        "additional_data": getattr(error_event, "additional_data", None),
    }


def _safe_schema_dump(output_schema: Optional[Any]) -> Optional[Any]:
    if output_schema is None:
        return None
    if isinstance(output_schema, dict):
        return output_schema
    if hasattr(output_schema, "__name__"):
        return output_schema.__name__
    return str(output_schema)


def _truncate_value(value: Any, max_chars: int, truncation_state: Dict[str, bool]) -> Any:
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        truncation_state["truncated"] = True
        return f"{value[:max_chars]}...[truncated]"
    if isinstance(value, list):
        return [_truncate_value(item, max_chars, truncation_state) for item in value]
    if isinstance(value, tuple):
        return [_truncate_value(item, max_chars, truncation_state) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_value(val, max_chars, truncation_state) for key, val in value.items()}
    return value


def _enforce_payload_limit(payload: Dict[str, Any], max_payload_bytes: int, max_message_chars: int) -> ReplayPayload:
    truncation_state = {"truncated": False}
    payload_bytes = _json_len(payload)
    if payload_bytes <= max_payload_bytes:
        return ReplayPayload(payload=payload, encoding="json", payload_bytes=payload_bytes, truncated=False)

    truncation_state["truncated"] = True
    payload = dict(payload)
    payload["final_messages"] = (payload.get("final_messages") or [])[-5:]
    payload["tool_calls"] = (payload.get("tool_calls") or [])[-5:]
    payload["truncation"] = {
        "truncated": True,
        "reason": "max_payload_bytes_exceeded",
        "max_payload_bytes": max_payload_bytes,
        "payload_bytes_before": payload_bytes,
    }

    reduced_chars = max(128, min(max_message_chars, 512))
    payload = _truncate_value(payload, reduced_chars, truncation_state)
    payload_bytes = _json_len(payload)
    if payload_bytes <= max_payload_bytes:
        return ReplayPayload(payload=payload, encoding="json", payload_bytes=payload_bytes, truncated=True)

    minimal_payload = {
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "truncation": {
            "truncated": True,
            "reason": "max_payload_bytes_exceeded",
            "max_payload_bytes": max_payload_bytes,
        },
    }
    minimal_payload_bytes = _json_len(minimal_payload)
    return ReplayPayload(payload=minimal_payload, encoding="json", payload_bytes=minimal_payload_bytes, truncated=True)


def _encode_payload(payload: Dict[str, Any], compress: bool) -> ReplayPayload:
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if not compress:
        return ReplayPayload(payload=payload, encoding="json", payload_bytes=len(json_bytes), truncated=False)

    import base64
    import gzip

    compressed = gzip.compress(json_bytes)
    if len(compressed) >= len(json_bytes):
        return ReplayPayload(payload=payload, encoding="json", payload_bytes=len(json_bytes), truncated=False)
    encoded_payload = base64.b64encode(compressed).decode("ascii")
    return ReplayPayload(payload=encoded_payload, encoding="gzip+json", payload_bytes=len(compressed), truncated=False)


def _json_len(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _get_replay_status(run_response: RunOutput) -> str:
    status = _normalise_run_status(run_response.status)
    if status == RunStatus.completed:
        return "success"
    if status == RunStatus.cancelled:
        return "cancelled"
    taxonomy = _extract_error_taxonomy(run_response)
    if taxonomy is not None and taxonomy.get("error_type") == "timeout":
        return "timeout"
    return "error"


def _normalise_run_status(value: Any) -> RunStatus:
    if isinstance(value, RunStatus):
        return value
    if isinstance(value, str):
        try:
            return RunStatus(value)
        except ValueError:
            normalised = value.strip().lower()
            for status in RunStatus:
                if status.value == normalised:
                    return status
    return RunStatus.error
