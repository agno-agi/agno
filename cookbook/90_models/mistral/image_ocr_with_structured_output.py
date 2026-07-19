"""
Mistral Image Ocr With Structured Output
========================================

Cookbook example for `mistral/image_ocr_with_structured_output.py`.
"""

from typing import List

from agno.agent import Agent
from agno.media import Image
from agno.models.mistral.mistral import MistralChat
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


class GroceryItem(BaseModel):
    item_name: str
    price: float


class GroceryListElements(BaseModel):
    bill_number: str
    items: List[GroceryItem]
    total_price: float


agent = Agent(
    model=MistralChat(id="pixtral-12b-2409"),
    instructions=[
        "Extract the text elements described by the user from the picture",
    ],
    output_schema=GroceryListElements,
    markdown=True,
)

agent.print_response(
    "From this restaurant bill, extract the bill number, item names and associated prices, and total price and return it as a string in a Json object",
    images=[Image(url="https://i.imghippo.com/files/kgXi81726851246.jpg")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
