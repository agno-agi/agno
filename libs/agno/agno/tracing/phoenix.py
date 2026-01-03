"""
Phoenix Project Routing for Agno

This module provides thread-safe project routing for Arize Phoenix, allowing
different agents to send traces to different Phoenix projects.

Usage:
    from agno.tracing.phoenix import setup_phoenix, using_project

    # Set up Phoenix with project routing
    setup_phoenix(default_project="default")

    # Route traces to specific projects
    with using_project("my-project"):
        await agent.arun("query")  # Traces go to "my-project"
"""

import os
from contextlib import contextmanager
from typing import Generator, Optional

from agno.utils.log import logger

try:
    from openinference.instrumentation.agno import AgnoInstrumentor
    from opentelemetry import trace as trace_api
    from opentelemetry.context import Context, attach, detach, get_current, get_value, set_value
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    PHOENIX_AVAILABLE = True
except ImportError:
    PHOENIX_AVAILABLE = False

# Resource attribute for project name in Phoenix
PROJECT_NAME_ATTR = "openinference.project.name"

# Context key for storing the target project
_PHOENIX_PROJECT_KEY = "phoenix.project.name"


class _ProjectRoutingSpanProcessor(SpanProcessor):
    """
    A SpanProcessor that captures the target Phoenix project from context
    when a span starts, and modifies the span's resource before export. This is a patching approach to modify the span's resource before export.

    This is thread-safe because:
    1. It uses OpenTelemetry's Context (which uses contextvars internally)
    2. Each span captures its project at start time
    3. The project is stored in span attributes (per-span, not global)

    The patching: We store the target project in a span attribute when the span
    starts, then read it back and modify the resource when the span ends.
    """

    # Internal attribute to store the target project on each span
    _PROJECT_ATTR = "_phoenix_target_project"

    def __init__(self, default_project: str = "default"):
        self._default_project = default_project

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        """Called when a span starts. Capture the current project from context."""
        # Get the target project from the current context
        ctx = parent_context or get_current()
        project_value = get_value(_PHOENIX_PROJECT_KEY, ctx)

        # Ensure project is a string
        if project_value is None or not isinstance(project_value, str):
            project = self._default_project
        else:
            project = project_value

        # Store the project in a span attribute so we can read it later
        # This is safe because each span has its own attributes
        span.set_attribute(self._PROJECT_ATTR, project)

    def on_end(self, span: ReadableSpan) -> None:
        """Called when a span ends. Modify the resource to set the project."""
        # Get the target project from the span's attributes
        attrs = span.attributes or {}
        project = attrs.get(self._PROJECT_ATTR, self._default_project)

        # Create new resource with the correct project name
        new_attributes = dict(span.resource.attributes)
        new_attributes[PROJECT_NAME_ATTR] = project

        new_resource = Resource(
            attributes=new_attributes,
            schema_url=span.resource.schema_url,
        )

        # Modify the span's resource
        # This is safe because on_end is called after the span is finished
        # but before it's exported
        span._resource = new_resource  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


@contextmanager
def using_project(project_name: str) -> Generator[None, None, None]:
    """
    Context manager to route all traces to a specific Phoenix project.

    This is THREAD-SAFE and works with concurrent execution.

    Args:
        project_name: The Phoenix project to route traces to

    Usage:
        with using_project("my-project"):
            await agent.arun("query")  # All traces go to "my-project"

    Works with asyncio.gather:
        async def run_agent(agent, project, query):
            with using_project(project):
                return await agent.arun(query)

        await asyncio.gather(
            run_agent(agent1, "project-a", "query1"),
            run_agent(agent2, "project-b", "query2"),
        )
    """
    if not PHOENIX_AVAILABLE:
        logger.warning(
            "Phoenix tracing not available. Install with: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno"
        )
        yield
        return

    # Set the project in the OpenTelemetry context
    ctx = set_value(_PHOENIX_PROJECT_KEY, project_name)
    token = attach(ctx)
    try:
        yield
    finally:
        detach(token)


def setup_phoenix(
    default_project: str = "default",
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    batch: bool = True,
) -> Optional["TracerProvider"]:
    """
    Set up Phoenix tracing with project routing support.

    Args:
        default_project: Default project for traces without explicit routing
        endpoint: Phoenix OTLP endpoint. If not provided, uses PHOENIX_COLLECTOR_ENDPOINT
                  env var or defaults to Phoenix Cloud.
        api_key: Phoenix API key. If not provided, uses PHOENIX_API_KEY env var.
        batch: Use BatchSpanProcessor (recommended for production)

    Returns:
        Configured TracerProvider, or None if Phoenix is not available

    Environment Variables:
        PHOENIX_API_KEY: API key for Phoenix authentication
        PHOENIX_COLLECTOR_ENDPOINT: Phoenix collector endpoint URL

    Example:
        from agno.tracing.phoenix import setup_phoenix, using_project

        # Basic setup
        setup_phoenix(default_project="my-app")

        # With explicit configuration
        setup_phoenix(
            default_project="my-app",
            endpoint="https://app.phoenix.arize.com/v1/traces",
            api_key="your-api-key",
        )
    """
    if not PHOENIX_AVAILABLE:
        logger.warning(
            "Phoenix tracing not available. Install with: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno"
        )
        return None

    # Get configuration from environment if not provided
    api_key = api_key or os.getenv("PHOENIX_API_KEY", "")
    if not api_key:
        raise ValueError(
            "Phoenix API key required. Set PHOENIX_API_KEY environment variable "
            "or pass api_key parameter."
        )

    # Determine endpoint
    if endpoint is None:
        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "https://app.phoenix.arize.com")
        # Ensure endpoint has /v1/traces suffix for HTTP
        if not endpoint.endswith("/v1/traces"):
            endpoint = endpoint.rstrip("/") + "/v1/traces"

    headers = {"authorization": f"Bearer {api_key}"}

    # Create tracer provider with default resource
    tracer_provider = TracerProvider(resource=Resource({PROJECT_NAME_ATTR: default_project}))

    # Add our custom project routing processor FIRST
    # This captures the project context when spans start
    tracer_provider.add_span_processor(_ProjectRoutingSpanProcessor(default_project=default_project))

    # Add the exporter processor
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    if batch:
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Set as global tracer provider
    trace_api.set_tracer_provider(tracer_provider)

    # Instrument Agno
    AgnoInstrumentor().instrument(tracer_provider=tracer_provider)

    logger.info(f"Phoenix tracing enabled with project routing. Default project: {default_project}")

    return tracer_provider