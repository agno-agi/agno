"""
Image Search demo — AgentOS entrypoint.

  /ui                                  — single-file HTML UI
  /knowledge/content                   — gallery list  (native)
  /knowledge/search                    — vector search (native)
  /workflows/image-ingest/runs         — reindex      (native)

Run:
    fastapi dev cookbook/data_labeling/image_search/run.py --port 7777

Then open http://localhost:7777/ui.
"""

import os

from agno.os import AgentOS
from db import get_knowledge
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from settings import PUBLIC_DIR
from workflows.ingest import ingest_workflow

# ---------------------------------------------------------------------------
# FastAPI base app — CORS + the explicit /ui route.
#
# StaticFiles(html=True) doesn't work cleanly because AgentOS's
# TrailingSlashMiddleware strips the slash that StaticFiles relies on for
# index-resolution. Returning FileResponse from an explicit route is the
# simplest path and avoids the redirect loop.
# ---------------------------------------------------------------------------
base_app = FastAPI(title="Image Search")
base_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@base_app.get("/ui", include_in_schema=False)
def serve_ui() -> FileResponse:
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"))


# ---------------------------------------------------------------------------
# AgentOS — pulls in Knowledge (gallery + search) and the ingest workflow.
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="image_search",
    name="Image Search",
    knowledge=[get_knowledge()],
    workflows=[ingest_workflow],
    base_app=base_app,
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
