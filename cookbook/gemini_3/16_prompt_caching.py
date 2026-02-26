"""
16. Prompt Caching
==================
Cache large documents or system prompts to save tokens on repeated queries.
Upload a file, create a cache with a TTL, then query without re-sending
the full context each time.

Run:
    python cookbook/gemini_3/16_prompt_caching.py

Note: Requires google-genai package.
"""

from pathlib import Path
from time import sleep

import requests
from google import genai
from google.genai.types import UploadFileConfig

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Download and upload the source document
# ---------------------------------------------------------------------------
client = genai.Client()

# Download a large text file (Apollo 11 transcript)
txt_url = "https://storage.googleapis.com/generativeai-downloads/data/a11.txt"
txt_path = WORKSPACE / "a11.txt"

if not txt_path.exists():
    print("Downloading transcript...")
    with txt_path.open("wb") as f:
        resp = requests.get(txt_url, stream=True)
        for chunk in resp.iter_content(chunk_size=32768):
            f.write(chunk)

# Upload to Google (get-or-create pattern)
remote_name = "files/a11"
txt_file = None
try:
    txt_file = client.files.get(name=remote_name)
    print(f"File already uploaded: {txt_file.uri}")
except Exception:
    pass

if not txt_file:
    print("Uploading file...")
    txt_file = client.files.upload(
        file=txt_path,
        config=UploadFileConfig(name=remote_name),
    )
    while txt_file and txt_file.state and txt_file.state.name == "PROCESSING":
        print("Processing...")
        sleep(2)
        txt_file = client.files.get(name=remote_name)
    print(f"Upload complete: {txt_file.uri}")

# ---------------------------------------------------------------------------
# Create cache
# ---------------------------------------------------------------------------
print("\nCreating cache (5 min TTL)...")
cache = client.caches.create(
    model="gemini-3-flash-preview",
    config={
        "system_instruction": "You are an expert at analyzing transcripts.",
        "contents": [txt_file],
        "ttl": "300s",
    },
)
print(f"Cache created: {cache.name}")

# ---------------------------------------------------------------------------
# Create Agent with cached content
# ---------------------------------------------------------------------------
cache_agent = Agent(
    name="Transcript Analyst",
    model=Gemini(id="gemini-3-flash-preview", cached_content=cache.name),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Query 1: The full transcript is in the cache, no need to re-send
    run_output = cache_agent.run(
        "Find a lighthearted moment from this transcript"
    )
    print(f"\nResponse:\n{run_output.content}")
    print(f"\nMetrics: {run_output.metrics}")

    # Query 2: Same cache, different question -- token savings
    run_output = cache_agent.run(
        "What was the most tense moment during the mission?"
    )
    print(f"\nResponse:\n{run_output.content}")
    print(f"\nMetrics: {run_output.metrics}")
