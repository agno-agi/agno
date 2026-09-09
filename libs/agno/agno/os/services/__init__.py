"""Shared service layer for AgentOS surfaces.

One implementation of the session-read and run-lifecycle operations, imported by
both the REST routers and the MCP tools (``from agno.os.services import sessions``
/ ``runs``) so the two interfaces cannot drift. Service functions take domain
arguments plus resolved identity and return domain objects / schema objects -- no
HTTP and no MCP types.
"""
