"""Arcmira: YouTube Transcript Search.

API docs: https://arcmira.com/docs
Run this direct search without an LLM, or pass ArcmiraTools() to an Agent's tools.
"""

from agno.tools.arcmira import ArcmiraTools

if __name__ == "__main__":
    print(ArcmiraTools(limit=5).search_transcripts("open source AI"))
