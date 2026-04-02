"""
Anthropic Pydantic Tool Input
==============================

Tests various pydantic model patterns as tool input parameters with Claude.
Covers: nested models, Optional fields, Union types, List of models, and
deeply nested models - all patterns that require additionalProperties: false
on nested object schemas for Anthropic's API.
"""

import asyncio
import json
from typing import List, Optional, Union

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools import tool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pattern 1: Nested pydantic models
# ---------------------------------------------------------------------------


class SearchFilters(BaseModel):
    category: str = Field(description="Category to search in")
    max_price: float = Field(description="Maximum price filter")
    in_stock: bool = Field(default=True, description="Only show in-stock items")


class SearchRequest(BaseModel):
    query: str = Field(description="The search query string")
    filters: SearchFilters = Field(description="Filters to apply to the search")


@tool
def search_products(request: SearchRequest) -> str:
    """Search for products using structured filters.

    Args:
        request: The search request with query and filters
    """
    return json.dumps(
        {
            "results": [
                {
                    "name": f"Result for '{request.query}'",
                    "category": request.filters.category,
                    "price": request.filters.max_price * 0.8,
                    "in_stock": request.filters.in_stock,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Pattern 2: Optional pydantic model fields
# ---------------------------------------------------------------------------


class Address(BaseModel):
    street: str = Field(description="Street address")
    city: str = Field(description="City name")
    zip_code: str = Field(description="ZIP or postal code")


class UserProfile(BaseModel):
    name: str = Field(description="Full name of the user")
    email: str = Field(description="Email address")
    address: Optional[Address] = Field(
        default=None, description="Mailing address, if known"
    )


@tool
def create_user(profile: UserProfile) -> str:
    """Create a new user profile.

    Args:
        profile: The user profile to create
    """
    result = {"name": profile.name, "email": profile.email}
    if profile.address:
        result["address"] = (
            f"{profile.address.street}, {profile.address.city} {profile.address.zip_code}"
        )
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Pattern 3: Union of pydantic models
# ---------------------------------------------------------------------------


class CreditCard(BaseModel):
    card_number: str = Field(description="Credit card number")
    expiry: str = Field(description="Expiry date in MM/YY format")


class BankTransfer(BaseModel):
    account_number: str = Field(description="Bank account number")
    routing_number: str = Field(description="Bank routing number")


class PaymentRequest(BaseModel):
    amount: float = Field(description="Payment amount in USD")
    method: Union[CreditCard, BankTransfer] = Field(
        description="Payment method details"
    )


@tool
def process_payment(payment: PaymentRequest) -> str:
    """Process a payment using the specified method.

    Args:
        payment: The payment request with amount and method
    """
    method_type = (
        "credit_card" if isinstance(payment.method, CreditCard) else "bank_transfer"
    )
    return json.dumps(
        {"status": "processed", "amount": payment.amount, "method": method_type}
    )


# ---------------------------------------------------------------------------
# Pattern 4: List of pydantic models
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    product_name: str = Field(description="Name of the product")
    quantity: int = Field(description="Number of items")
    unit_price: float = Field(description="Price per unit in USD")


class Order(BaseModel):
    customer_name: str = Field(description="Name of the customer")
    items: List[LineItem] = Field(description="List of items in the order")


@tool
def submit_order(order: Order) -> str:
    """Submit an order with multiple line items.

    Args:
        order: The order with customer info and line items
    """
    total = sum(item.quantity * item.unit_price for item in order.items)
    return json.dumps(
        {
            "customer": order.customer_name,
            "item_count": len(order.items),
            "total": total,
            "status": "submitted",
        }
    )


# ---------------------------------------------------------------------------
# Pattern 5: Deeply nested models (3+ levels)
# ---------------------------------------------------------------------------


class Coordinate(BaseModel):
    latitude: float = Field(description="Latitude coordinate")
    longitude: float = Field(description="Longitude coordinate")


class Location(BaseModel):
    name: str = Field(description="Location name")
    coordinates: Coordinate = Field(description="GPS coordinates")


class DeliveryRoute(BaseModel):
    origin: Location = Field(description="Starting location")
    destination: Location = Field(description="Ending location")
    priority: str = Field(
        default="normal", description="Delivery priority: normal or express"
    )


@tool
def plan_delivery(route: DeliveryRoute) -> str:
    """Plan a delivery route between two locations.

    Args:
        route: The delivery route with origin and destination
    """
    return json.dumps(
        {
            "from": route.origin.name,
            "to": route.destination.name,
            "priority": route.priority,
            "estimated_distance_km": abs(
                route.destination.coordinates.latitude
                - route.origin.coordinates.latitude
            )
            * 111,
        }
    )


# ---------------------------------------------------------------------------
# Run each pattern
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    patterns = [
        (
            "Pattern 1: Nested models",
            [search_products],
            "Search for wireless headphones under $50 in the electronics category",
        ),
        (
            "Pattern 2: Optional model fields",
            [create_user],
            "Create a user named John Doe with email john@example.com and address 123 Main St, Springfield, 62704",
        ),
        (
            "Pattern 3: Union of models",
            [process_payment],
            "Process a $99.99 payment using credit card number 4111-1111-1111-1111 expiring 12/27",
        ),
        (
            "Pattern 4: List of models",
            [submit_order],
            "Submit an order for Alice: 2x Widget at $9.99 each and 1x Gadget at $24.99",
        ),
        (
            "Pattern 5: Deeply nested models (3 levels)",
            [plan_delivery],
            "Plan an express delivery from Warehouse A at coordinates 40.7128, -74.0060 to Store B at 34.0522, -118.2437",
        ),
    ]

    for label, tools, prompt in patterns:
        print(f"\n{'=' * 60}")
        print(f" {label}")
        print(f"{'=' * 60}\n")

        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=tools,
            markdown=True,
        )

        # Sync
        agent.print_response(prompt)

        # Async
        asyncio.run(agent.aprint_response(prompt))
