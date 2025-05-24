"""Convenience helper to run CopilotKit backend via `uvicorn`.

Example:
```
from agno.app.copilotkit.app import CopilotKitApp
from agno.agent.builtins import EchoAgent

app = CopilotKitApp(agent=EchoAgent()).get_app()
serve_copilotkit_app(app, port=8888)
```
"""

from __future__ import annotations

from typing import Union

from fastapi import FastAPI

from agno.app.fastapi.serve import serve_fastapi_app


def serve_copilotkit_app(
    app: Union[str, FastAPI],
    *,
    host: str = "localhost",
    port: int = 7777,
    reload: bool = False,
    **kwargs,
):
    """Run the given FastAPI app with sensible defaults for CopilotKit."""
    serve_fastapi_app(app, host=host, port=port, reload=reload, **kwargs)
