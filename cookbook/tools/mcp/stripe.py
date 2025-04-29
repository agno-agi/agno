"""💵 Stripe MCP Agent - Manage Your Stripe Operations

This example demonstrates how to create an Agno agent that interacts with the Stripe API via the Model Context Protocol (MCP). This agent can create and manage Stripe objects like customers, products, prices, and payment links using natural language commands.


Setup:
2. Install Python dependencies:
   ```bash
   pip install agno mcp-sdk
   ```
3. Set Environment Variable: export STRIPE_SECRET_KEY=***.

Stripe MCP Docs: https://github.com/stripe/agent-toolkit
"""

import asyncio
import os
from textwrap import dedent

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.utils.log import log_error, log_exception, log_info


async def run_agent(message: str) -> None:
    """
    Sets up the Stripe MCP server and initialize the Agno agent
    """
    # Verify Stripe API Key is available
    stripe_api_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_api_key:
        log_error("STRIPE_SECRET_KEY environment variable not set.")
        return

    enabled_tools = "paymentLinks.create,products.create,prices.create,customers.create,customers.read"

    # handle different Operating Systems
    npx_command = "npx.cmd" if os.name == "nt" else "npx"

    try:
        # Initialize MCP toolkit with Stripe server
        async with MCPTools(
            command=f"{npx_command} -y @stripe/mcp --tools={enabled_tools} --api-key={stripe_api_key}"
        ) as mcp_toolkit:
            agent = Agent(
                name="StripeAgent",
                instructions=dedent("""\
                    You are an AI assistant specialized in managing Stripe operations.
                    You interact with the Stripe API using the available tools.

                    - Understand user requests to create or list Stripe objects (customers, products, prices, payment links).
                    - Clearly state the results of your actions, including IDs of created objects or lists retrieved.
                    - Ask for clarification if a request is ambiguous.
                    - Use markdown formatting, especially for links or code snippets.
                    - Execute the necessary steps sequentially if a request involves multiple actions (e.g., create product, then price, then link).
                """),
                tools=[mcp_toolkit],
                markdown=True,
                show_tool_calls=True,
            )

            # Run the agent with the provided task
            log_info(f"Running agent with assignment: '{message}'")
            await agent.aprint_response(message, stream=True)

    except FileNotFoundError:
        error_msg = f"Error: '{npx_command}' command not found. Please ensure Node.js and npm/npx are installed and in your system's PATH."
        log_error(error_msg)
    except Exception as e:
        log_exception(f"An unexpected error occurred during agent execution: {e}")


if __name__ == "__main__":
    task = "Create a new Stripe product named 'iPhone'. Then create a price of $999.99 USD for it. Finally, create a payment link for that price."
    asyncio.run(run_agent(task))


# Example prompts:
"""
Customer Management:
- "Create a customer. Name: ACME Corp, Email: billing@acme.example.com"
- "List my customers."
- "Find customer by email 'jane.doe@example.com'" # Note: Requires 'customers.retrieve' or search capability

Product and Price Management:
- "Create a new product called 'Basic Plan'."
- "Create a recurring monthly price of $10 USD for product 'Basic Plan'."
- "Create a product 'Ebook Download' and a one-time price of $19.95 USD."
- "List all products." # Note: Requires 'products.list' capability
- "List all prices." # Note: Requires 'prices.list' capability

Payment Links:
- "Create a payment link for the $10 USD monthly 'Basic Plan' price."
- "Generate a payment link for the '$19.95 Ebook Download'."

Combined Tasks:
- "Create a product 'Pro Service', add a price $150 USD (one-time), and give me the payment link."
- "Register a new customer 'support@example.com' named 'Support Team'."
"""
