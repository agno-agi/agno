"""
iFLYTEK Spark Basic
===================

The minimal Spark agent, run four ways: sync, sync + streaming, async, and
async + streaming. Start here to confirm your `SPARK_API_KEY` works.

Get an API Password:
    Sign in to the iFLYTEK console (https://console.xfyun.cn), create a Spark
    application, then copy the HTTP-service API Password
    (`http服务接口认证信息` -> `APIPassword`) and export it:

        export SPARK_API_KEY=***
"""

import asyncio

from agno.agent import Agent
from agno.models.spark import Spark

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Spark(id="4.0Ultra"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story."))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story.", stream=True))
