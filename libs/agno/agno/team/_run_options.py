"""Centralized run option resolution for team dispatch functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.filters import FilterExpr

if TYPE_CHECKING:
    from agno.run import RunContext
    from agno.team.team import Team


@dataclass(frozen=True)
class ResolvedRunOptions:
    """Immutable snapshot of resolved run options.

    All values are fully resolved (call-site > team default > fallback)
    at construction time, except metadata where team-level values take
    precedence on conflicting keys.
    """

    stream: bool
    stream_events: bool
    yield_run_output: bool
    add_history_to_context: bool
    add_dependencies_to_context: bool
    add_session_state_to_context: bool
    dependencies: Optional[Dict[str, Any]]
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
    metadata: Optional[Dict[str, Any]]
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]]

    def apply_to_context(
        self,
        run_context: "RunContext",
        *,
        dependencies_provided: bool = False,
        knowledge_filters_provided: bool = False,
        metadata_provided: bool = False,
    ) -> None:
        """Apply resolved options to run_context with precedence:
        explicit args > existing run_context > resolved defaults."""
        if dependencies_provided:
            run_context.dependencies = self.dependencies
        elif run_context.dependencies is None:
            run_context.dependencies = self.dependencies

        if knowledge_filters_provided:
            run_context.knowledge_filters = self.knowledge_filters
        elif run_context.knowledge_filters is None:
            run_context.knowledge_filters = self.knowledge_filters

        if metadata_provided:
            run_context.metadata = self.metadata
        elif run_context.metadata is None:
            run_context.metadata = self.metadata

        # Always set output_schema from resolved options.
        # Unlike other fields, output_schema must always be updated because the same run_context
        # may be reused across workflow steps with different teams, each with their own output_schema.
        run_context.output_schema = self.output_schema


def resolve_run_options(
    team: Team,
    *,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    yield_run_output: Optional[bool] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
) -> ResolvedRunOptions:
    """Resolve all run options from call-site values and team defaults.

    Reads from ``team`` but does not mutate it.
    """
    from agno.team._utils import _get_effective_filters
    from agno.utils.merge_dict import merge_dictionaries

    # stream: call-site > team.stream > False
    resolved_stream: bool
    if stream is not None:
        resolved_stream = stream
    elif team.stream is not None:
        resolved_stream = team.stream
    else:
        resolved_stream = False

    # stream_events: forced False when not streaming;
    # otherwise call-site > team.stream_events > False
    resolved_stream_events: bool
    if resolved_stream is False:
        resolved_stream_events = False
    elif stream_events is not None:
        resolved_stream_events = stream_events
    elif team.stream_events is not None:
        resolved_stream_events = team.stream_events
    else:
        resolved_stream_events = False

    # yield_run_output: call-site > False
    resolved_yield = yield_run_output if yield_run_output is not None else False

    # Context flags: call-site > team.<field>
    resolved_add_history = add_history_to_context if add_history_to_context is not None else team.add_history_to_context
    resolved_add_deps = (
        add_dependencies_to_context if add_dependencies_to_context is not None else team.add_dependencies_to_context
    )
    resolved_add_state = (
        add_session_state_to_context if add_session_state_to_context is not None else team.add_session_state_to_context
    )

    # dependencies: call-site > team.dependencies
    # Defensive copy to prevent dependency resolution from mutating team defaults
    if dependencies is not None:
        resolved_deps = dependencies.copy()
    elif team.dependencies is not None:
        resolved_deps = team.dependencies.copy()
    else:
        resolved_deps = None

    # knowledge_filters: delegate to existing _get_effective_filters()
    resolved_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    if team.knowledge_filters or knowledge_filters:
        resolved_filters = _get_effective_filters(team, knowledge_filters=knowledge_filters)

    # metadata: merge call-site + team.metadata (team values take precedence)
    resolved_metadata: Optional[Dict[str, Any]] = None
    if metadata is not None and team.metadata is not None:
        resolved_metadata = metadata.copy()
        merge_dictionaries(resolved_metadata, team.metadata)
    elif metadata is not None:
        resolved_metadata = metadata.copy()
    elif team.metadata is not None:
        resolved_metadata = team.metadata.copy()

    # output_schema: call-site > team.output_schema
    resolved_output_schema = output_schema if output_schema is not None else team.output_schema

    return ResolvedRunOptions(
        stream=resolved_stream,
        stream_events=resolved_stream_events,
        yield_run_output=resolved_yield,
        add_history_to_context=resolved_add_history,
        add_dependencies_to_context=resolved_add_deps,
        add_session_state_to_context=resolved_add_state,
        dependencies=resolved_deps,
        knowledge_filters=resolved_filters,
        metadata=resolved_metadata,
        output_schema=resolved_output_schema,
    )
