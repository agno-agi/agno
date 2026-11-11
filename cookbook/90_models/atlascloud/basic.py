"""Run one Atlas Cloud request using a model class or the provider string."""

import argparse
import asyncio

from agno.agent import Agent
from agno.models.atlascloud import AtlasCloud

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--async", dest="async_mode", action="store_true")
    parser.add_argument("--model-string", action="store_true")
    args = parser.parse_args()

    agent = Agent(
        model="atlascloud:deepseek-ai/deepseek-v3.2"
        if args.model_string
        else AtlasCloud(max_tokens=128),
        markdown=True,
    )
    prompt = "In one sentence, explain what an AI agent is."
    if args.async_mode:
        asyncio.run(agent.aprint_response(prompt))
    else:
        agent.print_response(prompt)
