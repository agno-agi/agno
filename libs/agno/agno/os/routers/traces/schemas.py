from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agno.os.utils import format_duration_ms


def _derive_span_type(span: Any) -> str:
    """
    Derive the correct span type from span attributes.

    OpenInference sets span_kind to:
    - AGENT for both agents and teams
    - CHAIN for workflows

    We use additional context (agno.team.id, agno.workflow.id) to differentiate:
    - WORKFLOW: CHAIN spans or spans with agno.workflow.id
    - TEAM: AGENT spans with agno.team.id
    - AGENT: AGENT spans without agno.team.id
    - LLM, TOOL, etc.: unchanged
    """
    span_kind = span.attributes.get("openinference.span.kind", "UNKNOWN")

    # Check for workflow (CHAIN kind or has workflow.id)
    if span_kind == "CHAIN":
        return "WORKFLOW"

    # Check for team vs agent
    if span_kind == "AGENT":
        # If it has a team.id attribute, it's a TEAM span
        if span.attributes.get("agno.team.id") or span.attributes.get("team.id"):
            return "TEAM"
        return "AGENT"

    # Return original span kind for LLM, TOOL, etc.
    return span_kind


class TraceNode(BaseModel):
    """Recursive node structure for rendering trace hierarchy in the frontend"""

    id: str = Field(..., description="Span ID")
    name: str = Field(..., description="Span name (e.g., 'agent.run', 'llm.invoke')")
    type: str = Field(..., description="Span kind (AGENT, TEAM, WORKFLOW, LLM, TOOL)")
    duration: str = Field(..., description="Human-readable duration (e.g., '123ms', '1.5s')")
    start_time: datetime = Field(..., description="Start time (Pydantic auto-serializes to ISO 8601)")
    end_time: datetime = Field(..., description="End time (Pydantic auto-serializes to ISO 8601)")
    status: str = Field(..., description="Status code (OK, ERROR)")
    input: Optional[str] = Field(None, description="Input to the span")
    output: Optional[str] = Field(None, description="Output from the span")
    error: Optional[str] = Field(None, description="Error message if status is ERROR")
    spans: Optional[List["TraceNode"]] = Field(None, description="Child spans in the trace hierarchy")
    step_type: Optional[str] = Field(None, description="Workflow step type (Step, Condition, function, Agent, Team)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional span attributes and data")
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Flexible field for custom attributes and additional data"
    )

    @classmethod
    def from_span(cls, span: Any, spans: Optional[List["TraceNode"]] = None) -> "TraceNode":
        """Create TraceNode from a Span object"""
        # Derive the correct span type (AGENT, TEAM, WORKFLOW, LLM, TOOL, etc.)
        span_type = _derive_span_type(span)

        # Also get the raw span_kind for metadata extraction logic
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

        elif span_kind == "CHAIN":
            if workflow_description := span.attributes.get("agno.workflow.description"):
                metadata["description"] = workflow_description
            if steps_count := span.attributes.get("agno.workflow.steps_count"):
                metadata["steps_count"] = steps_count
            if steps := span.attributes.get("agno.workflow.steps"):
                metadata["steps"] = steps
            if step_types := span.attributes.get("agno.workflow.step_types"):
                metadata["step_types"] = step_types

        # Add session/user context if present
        if session_id := span.attributes.get("session.id"):
            metadata["session_id"] = session_id
        if user_id := span.attributes.get("user.id"):
            metadata["user_id"] = user_id

        # Use datetime objects directly
        return cls(
            id=span.span_id,
            name=span.name,
            type=span_type,
            duration=format_duration_ms(span.duration_ms),
            start_time=span.start_time,
            end_time=span.end_time,
            status=span.status_code,
            input=input_val,
            output=output_val,
            error=error_val,
            spans=spans,
            step_type=None,  # Set by _build_span_tree for workflow steps
            metadata=metadata if metadata else None,
            extra_data=None,
        )


class TraceSummary(BaseModel):
    """Summary information for trace list view"""

    trace_id: str = Field(..., description="Unique trace identifier")
    name: str = Field(..., description="Trace name (usually root span name)")
    status: str = Field(..., description="Overall status (OK, ERROR, UNSET)")
    duration: str = Field(..., description="Human-readable total duration")
    start_time: datetime = Field(..., description="Trace start time (Pydantic auto-serializes to ISO 8601)")
    end_time: datetime = Field(..., description="Trace end time (Pydantic auto-serializes to ISO 8601)")
    total_spans: int = Field(..., description="Total number of spans in this trace")
    error_count: int = Field(..., description="Number of spans with errors")
    input: Optional[str] = Field(None, description="Input to the agent")
    run_id: Optional[str] = Field(None, description="Associated run ID")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    team_id: Optional[str] = Field(None, description="Associated team ID")
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")
    created_at: datetime = Field(..., description="Time when trace was created (Pydantic auto-serializes to ISO 8601)")

    @classmethod
    def from_trace(cls, trace: Any, input: Optional[str] = None) -> "TraceSummary":
        # Use datetime objects directly (Pydantic will auto-serialize to ISO 8601)
        return cls(
            trace_id=trace.trace_id,
            name=trace.name,
            status=trace.status,
            duration=format_duration_ms(trace.duration_ms),
            start_time=trace.start_time,
            end_time=trace.end_time,
            total_spans=trace.total_spans,
            error_count=trace.error_count,
            input=input,
            run_id=trace.run_id,
            session_id=trace.session_id,
            user_id=trace.user_id,
            agent_id=trace.agent_id,
            team_id=trace.team_id,
            workflow_id=trace.workflow_id,
            created_at=trace.created_at,
        )


class TraceSessionStats(BaseModel):
    """Aggregated trace statistics grouped by session"""

    session_id: str = Field(..., description="Session identifier")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_id: Optional[str] = Field(None, description="Agent ID(s) used in the session")
    team_id: Optional[str] = Field(None, description="Team ID associated with the session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID associated with the session")
    total_traces: int = Field(..., description="Total number of traces in this session")
    first_trace_at: datetime = Field(..., description="Time of first trace (Pydantic auto-serializes to ISO 8601)")
    last_trace_at: datetime = Field(..., description="Time of last trace (Pydantic auto-serializes to ISO 8601)")


class TraceDetail(BaseModel):
    """Detailed trace information with hierarchical span tree"""

    trace_id: str = Field(..., description="Unique trace identifier")
    name: str = Field(..., description="Trace name (usually root span name)")
    status: str = Field(..., description="Overall status (OK, ERROR)")
    duration: str = Field(..., description="Human-readable total duration")
    start_time: datetime = Field(..., description="Trace start time (Pydantic auto-serializes to ISO 8601)")
    end_time: datetime = Field(..., description="Trace end time (Pydantic auto-serializes to ISO 8601)")
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
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")
    created_at: datetime = Field(..., description="Time when trace was created (Pydantic auto-serializes to ISO 8601)")
    tree: List[TraceNode] = Field(..., description="Hierarchical tree of spans (root nodes)")

    @classmethod
    def from_trace_and_spans(cls, trace: Any, spans: List[Any]) -> "TraceDetail":
        """Create TraceDetail from a Trace and its Spans, building the tree structure"""
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

            span_kind = root_span.attributes.get("openinference.span.kind", "")
            output_is_empty = not trace_output or trace_output == "None" or str(trace_output).strip() == "None"
            if span_kind == "CHAIN" and output_is_empty and trace.status != "ERROR":
                # Find direct children of root span (workflow steps)
                root_span_id = root_span.span_id
                direct_children = [s for s in spans if s.parent_span_id == root_span_id]
                if direct_children:
                    # Sort by end_time to get the last executed step
                    direct_children.sort(key=lambda s: s.end_time, reverse=True)
                    last_step = direct_children[0]
                    # Get output from the last step
                    trace_output = last_step.attributes.get("output.value")

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
        span_tree = cls._build_span_tree(
            spans,
            total_input_tokens,
            total_output_tokens,
            trace_start_time=trace.start_time,
            trace_end_time=trace.end_time,
            trace_duration_ms=trace.duration_ms,
        )

        # Use datetime objects directly (Pydantic will auto-serialize to ISO 8601)
        return cls(
            trace_id=trace.trace_id,
            name=trace.name,
            status=trace.status,
            duration=format_duration_ms(trace.duration_ms),
            start_time=trace.start_time,
            end_time=trace.end_time,
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
            workflow_id=trace.workflow_id,
            created_at=trace.created_at,
            tree=span_tree,
        )

    @staticmethod
    def _build_span_tree(
        spans: List[Any],
        total_input_tokens: int,
        total_output_tokens: int,
        trace_start_time: Optional[datetime] = None,
        trace_end_time: Optional[datetime] = None,
        trace_duration_ms: Optional[int] = None,
    ) -> List[TraceNode]:
        """Build hierarchical tree from flat list of spans

        Args:
            spans: List of span objects
            total_input_tokens: Total input tokens across all spans
            total_output_tokens: Total output tokens across all spans
            trace_start_time: Corrected start time from trace aggregation
            trace_end_time: Corrected end time from trace aggregation
            trace_duration_ms: Corrected duration from trace aggregation
        """
        if not spans:
            return []

        # Create a map of parent_id -> list of spans
        spans_map: Dict[Optional[str], List[Any]] = {}
        for span in spans:
            parent_id = span.parent_span_id
            if parent_id not in spans_map:
                spans_map[parent_id] = []
            spans_map[parent_id].append(span)

        # Extract step_types list from workflow root span for index-based matching
        step_types_list: List[str] = []
        root_spans = spans_map.get(None, [])
        for root_span in root_spans:
            span_kind = root_span.attributes.get("openinference.span.kind", "")
            if span_kind == "CHAIN":
                step_types = root_span.attributes.get("agno.workflow.step_types", [])
                if step_types:
                    step_types_list = list(step_types)
                    break  # Use first workflow root span's step_types

        # Recursive function to build tree for a span
        # step_index is used to track position within direct children of root (workflow steps)
        def build_node(span: Any, is_root: bool = False, step_index: Optional[int] = None) -> TraceNode:
            span_id = span.span_id
            children_spans = spans_map.get(span_id, [])

            # Sort children spans by start time
            if children_spans:
                children_spans.sort(key=lambda s: s.start_time)

            # Recursively build spans
            # For root span's direct children (workflow steps), pass the index
            children_nodes: Optional[List[TraceNode]] = None
            if is_root and step_types_list:
                children_nodes = []
                for idx, child in enumerate(children_spans):
                    children_nodes.append(build_node(child, step_index=idx))
            elif children_spans:
                children_nodes = [build_node(child) for child in children_spans]

            # For root span, create custom metadata with token totals
            if is_root:
                # Build simplified metadata for root with token totals
                root_metadata: Dict[str, Any] = {}
                if total_input_tokens > 0:
                    root_metadata["total_input_tokens"] = total_input_tokens
                if total_output_tokens > 0:
                    root_metadata["total_output_tokens"] = total_output_tokens

                # Use trace-level timing if available
                start_time = trace_start_time if trace_start_time else span.start_time
                end_time = trace_end_time if trace_end_time else span.end_time
                duration_ms = trace_duration_ms if trace_duration_ms is not None else span.duration_ms

                # Derive the correct span type (AGENT, TEAM, WORKFLOW, etc.)
                span_type = _derive_span_type(span)
                span_kind = span.attributes.get("openinference.span.kind", "UNKNOWN")

                # Add workflow-specific metadata for CHAIN/WORKFLOW spans
                if span_kind == "CHAIN":
                    if workflow_description := span.attributes.get("agno.workflow.description"):
                        root_metadata["description"] = workflow_description
                    if steps_count := span.attributes.get("agno.workflow.steps_count"):
                        root_metadata["steps_count"] = steps_count
                    if steps := span.attributes.get("agno.workflow.steps"):
                        root_metadata["steps"] = steps
                    if step_types := span.attributes.get("agno.workflow.step_types"):
                        root_metadata["step_types"] = step_types

                # Use datetime objects directly (Pydantic will auto-serialize to ISO 8601)
                # Skip input/output/error for root span (already at top level of TraceDetail)

                return TraceNode(
                    id=span.span_id,
                    name=span.name,
                    type=span_type,
                    duration=format_duration_ms(duration_ms),
                    start_time=start_time,
                    end_time=end_time,
                    status=span.status_code,
                    input=None,  # Skip for root span (already at TraceDetail level)
                    output=None,  # Skip for root span (already at TraceDetail level)
                    error=None,  # Skip for root span (already at TraceDetail level)
                    spans=children_nodes if children_nodes else None,
                    metadata=root_metadata if root_metadata else None,
                    extra_data=None,
                )
            else:
                # Create node from span
                node = TraceNode.from_span(span, spans=children_nodes)

                # For workflow step spans (direct children of root), assign step_type by index
                if step_index is not None and step_types_list and step_index < len(step_types_list):
                    node.step_type = step_types_list[step_index]

                return node

        # Sort root spans by start time
        root_spans.sort(key=lambda s: s.start_time)

        # Build tree starting from roots
        return [build_node(root, is_root=True) for root in root_spans]
