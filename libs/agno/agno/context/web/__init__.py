from agno.context.web.exa import ExaBackend
from agno.context.web.exa_mcp import ExaMCPBackend
from agno.context.web.parallel import ParallelBackend
from agno.context.web.parallel_mcp import ParallelMCPBackend
from agno.context.web.provider import DEFAULT_WEB_INSTRUCTIONS, WebContextProvider

__all__ = [
    "DEFAULT_WEB_INSTRUCTIONS",
    "ExaBackend",
    "ExaMCPBackend",
    "ParallelBackend",
    "ParallelMCPBackend",
    "WebContextProvider",
]
