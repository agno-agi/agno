from typing import Union

from fastapi import FastAPI

from agno.app.serve import serve_app


def serve_whatsapp_app(
    app: Union[str, FastAPI],
    *,
    host: str = "localhost",
    port: int = 7777,
    reload: bool = False,
    **kwargs,
):
    serve_app(app, host=host, port=port, reload=reload, **kwargs)
