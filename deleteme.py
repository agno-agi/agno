"""
DELETE BEFORE PUSHING

Example call using the MCP connector tool.
"""

import os

import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
response = client.beta.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1000,
    messages=[{"role": "user", "content": "What tools do you have available?"}],
    mcp_servers=[
        {
            "type": "url",
            "url": "http://localhost:8000/sse",
            "name": "example-mcp",
        }
    ],
    betas=["mcp-client-2025-04-04"],
)

import pdb

pdb.set_trace()
