from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TraceNode(BaseModel):
    """Recursive node structure for rendering trace hierarchy in the frontend"""

    id: str = Field(..., description="Span ID")
    name: str = Field(..., description="Span name (e.g., 'agent.run', 'llm.invoke')")
    type: str = Field(..., description="Span kind (AGENT, LLM, TOOL)")
    duration: str = Field(..., description="Human-readable duration (e.g., '123ms', '1.5s')")
    start_time: int = Field(..., description="Start time in nanoseconds")
    end_time: int = Field(..., description="End time in nanoseconds")
    status: str = Field(..., description="Status code (OK, ERROR)")
    input: Optional[str] = Field(None, description="Input to the span")
    output: Optional[str] = Field(None, description="Output from the span")
    error: Optional[str] = Field(None, description="Error message if status is ERROR")
    spans: Optional[List["TraceNode"]] = Field(None, description="Child spans in the trace hierarchy")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional span attributes and data")
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Flexible field for custom attributes and additional data"
    )

    @classmethod
    def from_span(cls, span: Any, spans: Optional[List["TraceNode"]] = None) -> "TraceNode":
        """Create TraceNode from a Span object"""
        # Format duration
        duration_ms = span.duration_ms
        if duration_ms < 1000:
            duration_str = f"{duration_ms}ms"
        else:
            duration_str = f"{duration_ms / 1000:.2f}s"

        # Extract span kind from attributes
        span_kind = span.attributes.get("openinference.span.kind", "UNKNOWN")

        # Extract input/output at root level (for all span types)
        input_val = span.attributes.get("input.value")
        output_val = span.attributes.get("output.value")

        # Extract error information
        error_val = None
        if span.status_code == "ERROR":
            error_val = span.status_message or span.attributes.get("exception.message")
            output_val = None

        # Build metadata with key attributes based on span kind
        metadata: Dict[str, Any] = {}

        if span_kind == "AGENT":
            if run_id := span.attributes.get("agno.run.id"):
                metadata["run_id"] = run_id

        elif span_kind == "LLM":
            if model_name := span.attributes.get("llm.model_name"):
                metadata["model"] = model_name
            if input_tokens := span.attributes.get("llm.token_count.prompt"):
                metadata["input_tokens"] = input_tokens
            if output_tokens := span.attributes.get("llm.token_count.completion"):
                metadata["output_tokens"] = output_tokens

        elif span_kind == "TOOL":
            if tool_name := span.attributes.get("tool.name"):
                metadata["tool_name"] = tool_name
            if tool_params := span.attributes.get("tool.parameters"):
                metadata["parameters"] = tool_params

        # Add session/user context if present
        if session_id := span.attributes.get("session.id"):
            metadata["session_id"] = session_id
        if user_id := span.attributes.get("user.id"):
            metadata["user_id"] = user_id

        return cls(
            id=span.span_id,
            name=span.name,
            type=span_kind,
            duration=duration_str,
            start_time=span.start_time_ns,
            end_time=span.end_time_ns,
            status=span.status_code,
            input=input_val,
            output=output_val,
            error=error_val,
            spans=spans,
            metadata=metadata if metadata else None,
            extra_data=None,
        )


class TraceSummary(BaseModel):
    """Summary information for trace list view"""

    trace_id: str = Field(..., description="Unique trace identifier")
    name: str = Field(..., description="Trace name (usually root span name)")
    status: str = Field(..., description="Overall status (OK, ERROR, UNSET)")
    duration: str = Field(..., description="Human-readable total duration")
    start_time: int = Field(..., description="Trace start time in nanoseconds")
    total_spans: int = Field(..., description="Total number of spans in this trace")
    error_count: int = Field(..., description="Number of spans with errors")
    input: Optional[str] = Field(None, description="Input to the agent")
    run_id: Optional[str] = Field(None, description="Associated run ID")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    created_at: int = Field(..., description="Unix timestamp when trace was created")

    @classmethod
    def from_trace(cls, trace: Any, input: Optional[str] = None) -> "TraceSummary":
        # Format duration
        duration_ms = trace.duration_ms
        if duration_ms < 1000:
            duration_str = f"{duration_ms}ms"
        else:
            duration_str = f"{duration_ms / 1000:.2f}s"

        return cls(
            trace_id=trace.trace_id,
            name=trace.name,
            status=trace.status,
            duration=duration_str,
            start_time=trace.start_time_ns,
            total_spans=trace.total_spans,
            error_count=trace.error_count,
            input=input,
            run_id=trace.run_id,
            session_id=trace.session_id,
            user_id=trace.user_id,
            agent_id=trace.agent_id,
            team_id=trace.team_id,
            created_at=trace.created_at,
        )


class TraceSessionStats(BaseModel):
    """Aggregated trace statistics grouped by session"""

    session_id: str = Field(..., description="Session identifier")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_id: Optional[str] = Field(None, description="Agent ID(s) used in the session")
    team_id: Optional[str] = Field(None, description="Team ID associated with the session")
    total_traces: int = Field(..., description="Total number of traces in this session")
    first_trace_at: int = Field(..., description="Unix timestamp of first trace in session")
    last_trace_at: int = Field(..., description="Unix timestamp of last trace in session")


class TraceDetail(BaseModel):
    """Detailed trace information with hierarchical span tree"""

    trace_id: str = Field(..., description="Unique trace identifier")
    name: str = Field(..., description="Trace name (usually root span name)")
    status: str = Field(..., description="Overall status (OK, ERROR, UNSET)")
    duration: str = Field(..., description="Human-readable total duration")
    start_time: int = Field(..., description="Trace start time in nanoseconds")
    end_time: int = Field(..., description="Trace end time in nanoseconds")
    total_spans: int = Field(..., description="Total number of spans in this trace")
    error_count: int = Field(..., description="Number of spans with errors")
    input: Optional[str] = Field(None, description="Input to the agent/workflow")
    output: Optional[str] = Field(None, description="Output from the agent/workflow")
    error: Optional[str] = Field(None, description="Error message if status is ERROR")
    run_id: Optional[str] = Field(None, description="Associated run ID")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    created_at: int = Field(..., description="Unix timestamp when trace was created")
    tree: List[TraceNode] = Field(..., description="Hierarchical tree of spans (root nodes)")

    @classmethod
    def from_trace_and_spans(cls, trace: Any, spans: List[Any]) -> "TraceDetail":
        """Create TraceDetail from a Trace and its Spans, building the tree structure"""
        # Format duration
        duration_ms = trace.duration_ms
        if duration_ms < 1000:
            duration_str = f"{duration_ms}ms"
        else:
            duration_str = f"{duration_ms / 1000:.2f}s"

        # Find root span to extract input/output/error
        root_span = next((s for s in spans if not s.parent_span_id), None)
        trace_input = None
        trace_output = None
        trace_error = None

        if root_span:
            trace_input = root_span.attributes.get("input.value")
            output_val = root_span.attributes.get("output.value")

            # If trace status is ERROR, extract error and set output to None
            if trace.status == "ERROR" or root_span.status_code == "ERROR":
                trace_error = root_span.status_message or root_span.attributes.get("exception.message")
                trace_output = None
            else:
                trace_output = output_val

        # Calculate total tokens from all LLM spans
        total_input_tokens = 0
        total_output_tokens = 0
        for span in spans:
            if span.attributes.get("openinference.span.kind") == "LLM":
                input_tokens = span.attributes.get("llm.token_count.prompt", 0)
                output_tokens = span.attributes.get("llm.token_count.completion", 0)
                if input_tokens:
                    total_input_tokens += input_tokens
                if output_tokens:
                    total_output_tokens += output_tokens

        # Build span tree with token totals
        span_tree = cls._build_span_tree(spans, total_input_tokens, total_output_tokens)

        return cls(
            trace_id=trace.trace_id,
            name=trace.name,
            status=trace.status,
            duration=duration_str,
            start_time=trace.start_time_ns,
            end_time=trace.end_time_ns,
            total_spans=trace.total_spans,
            error_count=trace.error_count,
            input=trace_input,
            output=trace_output,
            error=trace_error,
            run_id=trace.run_id,
            session_id=trace.session_id,
            user_id=trace.user_id,
            agent_id=trace.agent_id,
            team_id=trace.team_id,
            created_at=trace.created_at,
            tree=span_tree,
        )

    @staticmethod
    def _build_span_tree(spans: List[Any], total_input_tokens: int, total_output_tokens: int) -> List[TraceNode]:
        """Build hierarchical tree from flat list of spans"""
        if not spans:
            return []

        # Create a map of parent_id -> list of spans
        spans_map: Dict[Optional[str], List[Any]] = {}
        for span in spans:
            parent_id = span.parent_span_id
            if parent_id not in spans_map:
                spans_map[parent_id] = []
            spans_map[parent_id].append(span)

        # Recursive function to build tree for a span
        def build_node(span: Any, is_root: bool = False) -> TraceNode:
            span_id = span.span_id
            children_spans = spans_map.get(span_id, [])

            # Sort children spans by start time
            if children_spans:
                children_spans.sort(key=lambda s: s.start_time_ns)

            # Recursively build spans
            children_nodes = [build_node(child) for child in children_spans] if children_spans else None

            # For root span, create custom metadata with token totals
            if is_root:
                # Build simplified metadata for root with token totals
                root_metadata = {}
                if total_input_tokens > 0:
                    root_metadata["total_input_tokens"] = total_input_tokens
                if total_output_tokens > 0:
                    root_metadata["total_output_tokens"] = total_output_tokens

                # Create TraceNode manually for root with custom metadata
                duration_ms = span.duration_ms
                duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms / 1000:.2f}s"
                span_kind = span.attributes.get("openinference.span.kind", "UNKNOWN")

                # Skip input/output/error for root span (already at top level of TraceDetail)

                return TraceNode(
                    id=span.span_id,
                    name=span.name,
                    type=span_kind,
                    duration=duration_str,
                    start_time=span.start_time_ns,
                    end_time=span.end_time_ns,
                    status=span.status_code,
                    input=None,  # Skip for root span (already at TraceDetail level)
                    output=None,  # Skip for root span (already at TraceDetail level)
                    error=None,  # Skip for root span (already at TraceDetail level)
                    spans=children_nodes,
                    metadata=root_metadata if root_metadata else None,
                    extra_data=None,
                )
            else:
                return TraceNode.from_span(span, spans=children_nodes)

        # Find root spans (spans with no parent)
        root_spans = spans_map.get(None, [])

        # Sort root spans by start time
        root_spans.sort(key=lambda s: s.start_time_ns)

        # Build tree starting from roots
        return [build_node(root, is_root=True) for root in root_spans]
