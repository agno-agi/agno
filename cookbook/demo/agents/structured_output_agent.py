"""E-commerce Product Recommender - AI agent that provides personalized product recommendations"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class Product(BaseModel):
    """Individual product recommendation"""
    name: str = Field(description="Product name")
    description: str = Field(description="Product description")
    why_recommended: str = Field(description="Why this product is recommended for the user")


class ProductRecommendation(BaseModel):
    """Structured product recommendation"""

    products: list[Product] = Field(
        description="List of recommended products with details"
    )
    personalization_notes: str = Field(
        description="How recommendations were personalized"
    )
    alternative_categories: list[str] = Field(
        description="Alternative product categories to consider"
    )
    trending_items: list[str] = Field(description="Currently trending related items")


ecommerce_recommender = Agent(
    id="ecommerce-product-recommender",
    name="E-commerce Product Recommender",
    session_id="ecommerce_recommender_session",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    db=db,
    description=dedent("""\
        Personalized shopping assistant that learns your preferences, remembers
        past purchases, tracks browsing history, and provides tailored product
        recommendations based on your unique style and needs.\
    """),
    instructions=[
        "Learn and remember user preferences, style, and past purchases",
        "Ask clarifying questions to understand needs and constraints",
        "Search for products matching user requirements",
        "Provide personalized recommendations with clear reasoning",
        "Consider budget, quality, brand preferences, and use cases",
        "Suggest complementary products and alternatives",
        "Alert about deals, discounts, and trending items",
        "Compare products across multiple dimensions",
        "Remember what user liked and disliked",
        "Adapt recommendations based on feedback",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    output_schema=ProductRecommendation,
    markdown=True,
)
