from textwrap import dedent
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.firecrawl import FirecrawlTools
from pydantic import BaseModel, Field


class ProductInfo(BaseModel):
    """Structured representation of an e-commerce product page."""

    model: str = Field(
        ..., description="Model name or identifier, e.g. 'iPhone 15 Pro Max'"
    )
    url: str = Field(..., description="Product URL")
    name: str = Field(..., description="Name/title of the product")
    price: Optional[float] = Field(
        None, description="Product price (numerical, if available)"
    )
    currency: Optional[str] = Field(
        None, description="Currency code such as USD, EUR, etc."
    )
    availability: Optional[str] = Field(
        None, description="Stock status, e.g. In stock / Out of stock"
    )
    description: Optional[str] = Field(
        None, description="Short description or bullet overview"
    )
    features: Optional[List[str]] = Field(None, description="Key feature list")
    processor: Optional[str] = Field(
        None, description="Chipset/processor used in the device"
    )
    display: Optional[str] = Field(
        None, description="Display type and resolution details"
    )
    camera: Optional[str] = Field(None, description="Primary camera specifications")
    battery: Optional[str] = Field(
        None, description="Battery capacity or claimed battery life"
    )
    storage_options: Optional[List[str]] = Field(
        None, description="Available storage configurations"
    )


agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[FirecrawlTools(scrape=False, crawl=True)],
    description="You are an e-commerce expert.",
    instructions=dedent("""
    You are an e-commerce expert. You have access to web crawling tools and you can use them to gather specifications, pricing, and notable feature descriptions. Gather all the necessary information about the iPhone models. Get the latest information
    """),
    response_model=ProductInfo,
    show_tool_calls=True,
)

agent.print_response("Get all the information about the new iPhone 15", stream=True)
