"""
Agno Tracing Module

This module provides OpenTelemetry-based tracing capabilities for Agno agents.
It uses the openinference-instrumentation-agno package for automatic instrumentation
and provides a custom DatabaseSpanExporter to store traces in the Agno database.

Phoenix Integration:
    For Arize Phoenix with project routing support:

    from agno.tracing.phoenix import setup_phoenix, using_project

    # Set up Phoenix
    setup_phoenix(default_project="my-app")

    # Route traces to specific projects
    with using_project("project-a"):
        await agent.arun("query")
"""

from agno.tracing.exporter import DatabaseSpanExporter
from agno.tracing.phoenix import setup_phoenix, using_project
from agno.tracing.setup import setup_tracing

__all__ = [
    "DatabaseSpanExporter",
    "setup_tracing",
    # Phoenix integration
    "setup_phoenix",
    "using_project",
]
