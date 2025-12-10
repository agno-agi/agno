"""
Example for AgentOS with Shopify tools.

Prerequisites:
- Set the following environment variables:
    - SHOPIFY_SHOP_NAME -> Your Shopify shop name, e.g. "my-store" from my-store.myshopify.com
    - SHOPIFY_ACCESS_TOKEN -> Your Shopify access token

You can get your Shopify access token from your Shopify Admin > Settings > Apps and sales channels > Develop apps

Required scopes:
- read_orders (for order and sales data)
- read_products (for product information)
- read_customers (for customer insights)
- read_analytics (for analytics data)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import AgentOSConfig, ChatConfig
from agno.tools.shopify import ShopifyTools

# Setup the database
db = PostgresDb(id="basic-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

sales_agent = Agent(
    name="Sales Analyst",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    tools=[ShopifyTools()],
    instructions=[
        "You are a sales analyst for an e-commerce store using Shopify.",
        "Help the user understand their sales performance, product trends, and customer behavior.",
        "When analyzing data:",
        "1. Start by getting the relevant data using the available tools",
        "2. Summarize key insights in a clear, actionable format",
        "3. Highlight notable patterns or concerns",
        "4. Suggest next steps when appropriate",
        "Always present numbers clearly and use comparisons to add context.",
        "If you need to get information about the store, like currency, call the `get_shop_info` tool.",
    ],
    markdown=True,
    add_datetime_to_context=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for Shopify agent",
    agents=[sales_agent],
    config=AgentOSConfig(
        chat=ChatConfig(
            quick_prompts={
                "sales_agent": [
                    "What are my top 5 selling products in the last 30 days? Show me quantity sold and revenue for each.",
                    "Which products are frequently bought together? I want to create product bundles for my store.",
                    "How are my sales trending compared to last month? Are we up or down in terms of revenue and order count?",
                ],
            },
        ),
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="shopify_demo:app", reload=True)
