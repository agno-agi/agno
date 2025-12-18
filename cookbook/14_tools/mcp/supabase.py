"""🔑 Supabase MCP Agent - Showcase Supabase MCP Capabilities

This example demonstrates how to use the Supabase MCP server to create create projects, database schemas, edge functions, and more.

Setup:
1. Install Python dependencies:

```bash
pip install agno mcp
```

2. Create a Supabase Access Token: https://supabase.com/dashboard/account/tokens and set it as the SUPABASE_ACCESS_TOKEN environment variable.
"""

import asyncio
import os
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from agno.tools.reasoning import ReasoningTools
from agno.utils.log import log_error, log_exception, log_info


async def run_agent(task: str) -> None:
    token = os.getenv("SUPABASE_ACCESS_TOKEN")
    if not token:
        log_error("SUPABASE_ACCESS_TOKEN environment variable not set.")
        return

    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"

    try:
        async with MCPTools(
            f"{npx_cmd} -y @supabase/mcp-server-supabase@latest --access-token={token}"
        ) as mcp:
            instructions = dedent(f"""
                You are an expert Supabase MCP architect. Given the project description:
                {task}

                Automatically perform the following steps :
                1. Plan the entire database schema based on the project description.
                2. Call `list_organizations` and select the first organization in the response.
                3. Use `get_cost(type='project')` to estimate project creation cost and mention the cost in your response.
                4. Create a new Supabase project with `create_project`, passing the confirmed cost ID.
                5. Poll project status with `get_project` until the status is `ACTIVE_HEALTHY`.
                6. Analyze the project requirements and propose a complete, normalized SQL schema (tables,  columns, data types, indexes, constraints, triggers, and functions) as DDL statements.
                7. Apply the schema using `apply_migration`, naming the migration `initial_schema`.
                8. Validate the deployed schema via `list_tables` and `list_extensions`.
                8. Deploy a simple health-check edge function with `deploy_edge_function`.
                9. Retrieve and print the project URL (`get_project_url`) and anon key (`get_anon_key`).
            """)
            agent = Agent(
                model=OpenAIChat(id="o4-mini"),
                instructions=instructions,
                tools=[mcp, ReasoningTools(add_instructions=True)],
                markdown=True,
            )

            log_info(f"Running Supabase project agent for: {task}")
            await agent.aprint_response(
                input=task,
                stream=True,
                show_full_reasoning=True,
            )
    except Exception as e:
        log_exception(f"Unexpected error: {e}")


if __name__ == "__main__":
    demo_description = (
        "Develop a cloud-based SaaS platform with AI-powered task suggestions, calendar syncing, predictive prioritization, "
        "team collaboration, and project analytics."
    )
    asyncio.run(run_agent(demo_description))


# Example prompts to try:
"""
A SaaS tool that helps businesses automate document processing using AI. Users can upload invoices, contracts, or PDFs and get structured data, smart summaries, and red flag alerts for compliance or anomalies. Ideal for legal teams, accountants, and enterprise back offices.

An AI-enhanced SaaS platform for streamlining the recruitment process. Features include automated candidate screening using NLP, AI interview scheduling, bias detection in job descriptions, and pipeline analytics. Designed for fast-growing startups and mid-sized HR teams.

An internal SaaS tool for HR departments to monitor employee wellbeing. Combines weekly mood check-ins, anonymous feedback, and AI-driven burnout detection models. Integrates with Slack and HR systems to support a healthier workplace culture.
"""
