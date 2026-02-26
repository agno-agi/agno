"""
Prompt Caching - Save Tokens on Repeated Queries
==================================================
Cache large documents server-side so repeated queries skip the full token cost.

Key concepts:
- genai.Client().caches.create: Creates a server-side cache with TTL
- cached_content: Links the cache to your Gemini model
- TTL: Time-to-live for the cache (e.g., "300s" = 5 minutes)
- Token savings: Subsequent queries skip the cached content's token cost

Example prompts to try:
- "Find a lighthearted moment from this transcript"
- "What was the most tense moment during the mission?"
- "Summarize the key decisions made"
"""

from pathlib import Path
from time import sleep

import requests
from agno.agent import Agent
from agno.models.google import Gemini
from google import genai
from google.genai.types import UploadFileConfig

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Download and upload the source document
# ---------------------------------------------------------------------------
client = genai.Client()

# Download a large text file (Apollo 11 transcript, ~100K tokens)
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
        # Cache expires after 5 minutes, set higher for production
        "ttl": "300s",
    },
)
print(f"Cache created: {cache.name}")

# ---------------------------------------------------------------------------
# Create Agent with cached content
# ---------------------------------------------------------------------------
cache_agent = Agent(
    name="Transcript Analyst",
    # cached_content links the agent to the pre-loaded cache
    model=Gemini(id="gemini-3-flash-preview", cached_content=cache.name),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Query 1: The full transcript is in the cache, no need to re-send
    run_output = cache_agent.run("Find a lighthearted moment from this transcript")
    print(f"\nResponse:\n{run_output.content}")
    print(f"\nMetrics: {run_output.metrics}")

    # Query 2: Same cache, different question, shows token savings
    run_output = cache_agent.run("What was the most tense moment during the mission?")
    print(f"\nResponse:\n{run_output.content}")
    print(f"\nMetrics: {run_output.metrics}")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Prompt caching economics:

- First query: Full token cost (upload + prompt + response)
- Subsequent queries: Only prompt + response tokens (cached content is free)
- For a 100K-token document queried 10 times:
  Without caching: 10 * 100K = 1M input tokens
  With caching: 100K + 10 * (prompt only) = ~110K input tokens

TTL guidelines:
- "300s" (5 min): Development and testing
- "3600s" (1 hour): Interactive sessions
- "86400s" (24 hours): Production batch jobs

Cache limitations:
- Minimum cached content: ~32K tokens
- Maximum TTL varies by model
- Cache is per-model, switching models requires a new cache
"""
