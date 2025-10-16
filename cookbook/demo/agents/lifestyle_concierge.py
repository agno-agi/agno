"""
Lifestyle Concierge - Comprehensive AI assistant for finance, shopping, and travel
"""

from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.guardrails import PIIDetectionGuardrail, PromptInjectionGuardrail
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

# ============================================================================
# Database Configuration
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url, id="lifestyle_concierge_db")

# ============================================================================
# Structured Output Schemas (Multi-Domain)
# ============================================================================


class FinancialAdvice(BaseModel):
    """Structured financial advice output"""

    summary: str = Field(description="Brief summary of financial advice")
    recommendations: list[str] = Field(
        description="Specific actionable recommendations"
    )
    risk_level: str = Field(description="Risk assessment: low, medium, high")
    investment_allocation: Optional[dict[str, float]] = Field(
        default=None, description="Suggested portfolio allocation percentages"
    )
    next_steps: list[str] = Field(description="Immediate next steps to take")


class Product(BaseModel):
    """Individual product recommendation"""

    name: str = Field(description="Product name")
    description: str = Field(description="Product description and key features")
    why_recommended: str = Field(
        description="Why this product is recommended for the user"
    )
    price_range: Optional[str] = Field(
        default=None, description="Estimated price range"
    )


class ProductRecommendation(BaseModel):
    """Structured product recommendations"""

    products: list[Product] = Field(
        description="List of recommended products with details"
    )
    personalization_notes: str = Field(
        description="How recommendations were personalized"
    )
    alternative_categories: list[str] = Field(
        description="Alternative product categories to consider"
    )
    budget_tips: list[str] = Field(description="Tips for staying within budget")


class Activity(BaseModel):
    """Individual travel activity recommendation"""

    day: str = Field(description="Day number or date")
    activity_name: str = Field(description="Name of the activity")
    description: str = Field(description="Activity description and details")
    duration: str = Field(description="Estimated duration")
    cost_estimate: Optional[str] = Field(default=None, description="Estimated cost")


class CostBreakdown(BaseModel):
    """Cost breakdown by category"""

    category: str = Field(
        description="Cost category (e.g., flights, accommodation, food, activities)"
    )
    estimated_amount: str = Field(description="Estimated cost for this category")


class TravelItinerary(BaseModel):
    """Structured travel itinerary and planning"""

    destination: str = Field(description="Travel destination")
    duration: str = Field(description="Trip duration")
    budget_estimate: str = Field(description="Total estimated budget")
    best_time_to_visit: str = Field(
        description="Best time to visit based on weather and events"
    )
    flight_options: list[str] = Field(description="Flight recommendations and tips")
    accommodation_options: list[str] = Field(
        description="Hotel/lodging recommendations"
    )
    activities: list[Activity] = Field(description="Recommended activities by day")
    restaurants: list[str] = Field(description="Restaurant and dining recommendations")
    local_tips: list[str] = Field(
        description="Local tips, cultural notes, and practical advice"
    )
    packing_list: list[str] = Field(description="Essential items to pack")
    estimated_costs: list[CostBreakdown] = Field(
        description="Detailed cost breakdown by category"
    )


# ============================================================================
# State Management Tools
# ============================================================================
# These tools allow the agent to manage persistent session state


def add_to_shopping_cart(
    session_state, item_name: str, price: float, quantity: int = 1
) -> str:
    """
    Add an item to the shopping cart.

    Args:
        item_name: Name of the item to add
        price: Price of the item
        quantity: Quantity to add (default: 1)

    Returns:
        Confirmation message with cart update
    """
    # Initialize cart if needed
    if "shopping_cart" not in session_state:
        session_state["shopping_cart"] = []

    # Add item to cart
    cart_item = {
        "item_name": item_name,
        "price": price,
        "quantity": quantity,
        "subtotal": price * quantity,
    }
    session_state["shopping_cart"].append(cart_item)

    # Calculate totals
    total_items = sum(item["quantity"] for item in session_state["shopping_cart"])
    total_cost = sum(item["subtotal"] for item in session_state["shopping_cart"])

    return f"Added {quantity}x {item_name} (${price:.2f} each) to cart.\nCart now has {total_items} items totaling ${total_cost:.2f}"


def view_shopping_cart(session_state) -> str:
    """
    View current shopping cart contents.

    Returns:
        Formatted cart contents with totals
    """
    if "shopping_cart" not in session_state:
        return "🛒 Your shopping cart is empty."

    cart = session_state["shopping_cart"]
    if not cart:
        return "🛒 Your shopping cart is empty."

    # Format cart contents
    cart_display = "🛒 **Shopping Cart**\n\n"
    for idx, item in enumerate(cart, 1):
        cart_display += f"{idx}. {item['item_name']}\n"
        cart_display += f"   ${item['price']:.2f} x {item['quantity']} = ${item['subtotal']:.2f}\n\n"

    total_cost = sum(item["subtotal"] for item in cart)
    total_items = sum(item["quantity"] for item in cart)

    cart_display += f"**Total**: {total_items} items, ${total_cost:.2f}"

    return cart_display


def clear_shopping_cart(session_state) -> str:
    """
    Clear all items from the shopping cart.

    Returns:
        Confirmation message
    """
    session_state["shopping_cart"] = []
    return "Shopping cart cleared successfully."


def save_travel_preferences(
    session_state, destination: str, budget: float, interests: str
) -> str:
    """
    Save travel preferences for future trip planning.

    Args:
        destination: Desired travel destination
        budget: Budget for the trip
        interests: User interests (e.g., "food, culture, tech")

    Returns:
        Confirmation message
    """
    session_state["travel_preferences"] = {
        "destination": destination,
        "budget": budget,
        "interests": interests.split(","),
    }

    return f"Saved travel preferences:\n- Destination: {destination}\n- Budget: ${budget:.2f}\n- Interests: {interests}"


def view_travel_preferences(session_state) -> str:
    """
    View saved travel preferences.

    Returns:
        Formatted travel preferences
    """
    if "travel_preferences" not in session_state:
        return (
            "No travel preferences saved yet. Use save_travel_preferences to set them."
        )

    prefs = session_state["travel_preferences"]

    # Check if preferences are empty or missing required fields
    if not prefs or not all(
        key in prefs for key in ["destination", "budget", "interests"]
    ):
        return (
            "No travel preferences saved yet. Use save_travel_preferences to set them."
        )

    # Handle interests as either list or string
    if isinstance(prefs["interests"], list):
        interests = ", ".join(prefs["interests"])
    else:
        interests = prefs["interests"]

    return f"✈️  **Saved Travel Preferences**\n\n- Destination: {prefs['destination']}\n- Budget: ${prefs['budget']:.2f}\n- Interests: {interests}"


# ============================================================================
# Lifestyle Concierge Agent
# ============================================================================

lifestyle_concierge = Agent(
    id="lifestyle-concierge",
    name="Lifestyle Concierge",
    session_id="lifestyle_concierge_session",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),  # Web search for financial info, products, travel, general info
        # STATE MANAGEMENT: Tools to manage shopping cart and travel preferences
        add_to_shopping_cart,
        view_shopping_cart,
        clear_shopping_cart,
        save_travel_preferences,
        view_travel_preferences,
    ],
    db=db,
    # AGENT STATE: Persistent session state stored in database
    session_state={
        "shopping_cart": [],
        "travel_preferences": {},
    },
    add_session_state_to_context=True,  # Make state available in prompts
    description=dedent("""\
        Your comprehensive AI personal assistant that helps with finance, shopping, and travel.

        I can help you:
        • 💰 FINANCE: Research financial topics, provide investment education and advice
        • 🛍️  SHOPPING: Find products, compare prices, recommend purchases
        • ✈️  TRAVEL: Plan trips, create itineraries, find deals

        I remember your preferences, past conversations, and adapt to your needs
        across all domains. Your privacy is protected with built-in guardrails.\
    """),
    instructions=[
        "You are a versatile AI assistant helping with finance, shopping, and travel",
        "",
        "FINANCIAL ASSISTANCE:",
        "- Use DuckDuckGo to search for financial information, market trends, and investment topics",
        "- Provide educational investment advice based on user's risk tolerance and goals",
        "- Remember past financial discussions and portfolio preferences",
        "- Explain financial concepts in simple, accessible language",
        "- Include specific, actionable next steps for financial decisions",
        "- Always remind users this is educational advice, not professional financial guidance",
        "",
        "SHOPPING ASSISTANCE:",
        "- Search for products using DuckDuckGo based on user requirements",
        "- Use shopping cart tools to manage items (add_to_shopping_cart, view_shopping_cart, clear_shopping_cart)",
        "- IMPORTANT: Shopping cart state persists across sessions - items are saved until explicitly cleared",
        "- Learn and remember user's style preferences, brand choices, and past purchases",
        "- Ask clarifying questions about budget, quality needs, and use cases",
        "- Provide personalized recommendations with clear reasoning",
        "- Compare products across multiple dimensions (price, quality, features)",
        "- When adding items to cart, extract accurate price information",
        "",
        "TRAVEL PLANNING:",
        "- Create comprehensive travel itineraries with day-by-day activities",
        "- Use save_travel_preferences to remember destinations, budgets, and interests",
        "- Use view_travel_preferences to recall saved travel plans",
        "- Travel preferences persist across sessions for future reference",
        "- Search for flights, accommodations, attractions, and restaurants",
        "- Consider seasonal factors, local events, and user preferences",
        "- Provide realistic budget breakdowns with money-saving tips",
        "",
        "STATE MANAGEMENT:",
        "- Shopping cart and travel preferences are stored in session_state",
        "- This state persists in the database across multiple conversations",
        "- Always check existing state before creating new entries",
        "- Inform users about their existing cart items or saved preferences when relevant",
        "",
        "GENERAL GUIDELINES:",
        "- Determine which domain (finance/shopping/travel) the user needs help with",
        "- Use appropriate structured output format for each domain",
        "- Maintain context and memory across all domains",
        "- Be proactive in asking clarifying questions",
        "- Always prioritize user privacy and security",
    ],
    # GUARDRAILS: Security and privacy protection
    pre_hooks=[
        PIIDetectionGuardrail(),  # Catch sensitive personal information
        PromptInjectionGuardrail(),  # Prevent prompt injection attacks
    ],
    # MEMORY: Remember user preferences and past conversations
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=5,  # Remember last 5 interactions
    add_datetime_to_context=True,
    # Note: output_schema can be dynamically set based on domain
    # For demo purposes, it will intelligently structure responses
    markdown=True,
)
