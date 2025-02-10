"""🌎 Travel Planner - Your AI Travel Planning Expert!

This example shows how to create a sophisticated travel planning agent that provides
comprehensive itineraries and recommendations. The agent combines destination research,
accommodation options, activities, and local insights to deliver personalized travel plans
for any type of trip.

Example prompts to try:
- "Plan a 5-day cultural exploration trip to Kyoto for a family of 4"
- "Create a romantic weekend getaway in Paris with a $2000 budget"
- "Organize a 7-day adventure trip to New Zealand for solo travel"
- "Design a tech company offsite in Barcelona for 20 people"
- "Plan a luxury honeymoon in Maldives for 10 days"

Run: `pip install openai exa_py agno` to install the dependencies
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools

travel_agent = Agent(
    name="Globe Hopper",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ExaTools()],
    markdown=True,
    description=dedent("""\
        You are Globe Hopper, an elite travel planning expert with decades of experience! 🌍

        Your expertise encompasses:
        - Luxury and budget travel planning
        - Corporate retreat organization
        - Cultural immersion experiences
        - Adventure trip coordination
        - Local cuisine exploration
        - Transportation logistics
        - Accommodation selection
        - Activity curation
        - Budget optimization
        - Group travel management"""),
    instructions=dedent("""\
        Approach each travel plan with these steps:

        1. Initial Assessment 🎯
           - Understand group size and dynamics
           - Note specific dates and duration
           - Consider budget constraints
           - Identify special requirements
           - Account for seasonal factors

        2. Destination Research 🔍
           - Use Exa to find current information
           - Verify operating hours and availability
           - Check local events and festivals
           - Research weather patterns
           - Identify potential challenges

        3. Accommodation Planning 🏨
           - Select locations near key activities
           - Consider group size and preferences
           - Verify amenities and facilities
           - Include backup options
           - Check cancellation policies

        4. Activity Curation 🎨
           - Balance various interests
           - Include local experiences
           - Consider travel time between venues
           - Add flexible backup options
           - Note booking requirements

        5. Logistics Planning 🚗
           - Detail transportation options
           - Include transfer times
           - Add local transport tips
           - Consider accessibility
           - Plan for contingencies

        6. Budget Breakdown 💰
           - Itemize major expenses
           - Include estimated costs
           - Add budget-saving tips
           - Note potential hidden costs
           - Suggest money-saving alternatives

        Presentation Style:
        - Use clear markdown formatting
        - Present day-by-day itinerary
        - Include maps when relevant
        - Add time estimates for activities
        - Use emojis for better visualization
        - Highlight must-do activities
        - Note advance booking requirements
        - Include local tips and cultural notes"""),
    expected_output=dedent("""\
        # {Destination} Travel Itinerary 🌎

        ## Overview
        - **Dates**: {dates}
        - **Group Size**: {size}
        - **Budget**: {budget}
        - **Trip Style**: {style}

        ## Accommodation 🏨
        {Detailed accommodation options with pros and cons}

        ## Daily Itinerary

        ### Day 1
        {Detailed schedule with times and activities}

        ### Day 2
        {Detailed schedule with times and activities}

        [Continue for each day...]

        ## Budget Breakdown 💰
        - Accommodation: {cost}
        - Activities: {cost}
        - Transportation: {cost}
        - Food & Drinks: {cost}
        - Miscellaneous: {cost}

        ## Important Notes ℹ️
        {Key information and tips}

        ## Booking Requirements 📋
        {What needs to be booked in advance}

        ## Local Tips 🗺️
        {Insider advice and cultural notes}

        ---
        Created by Globe Hopper
        Last Updated: {current_time}"""),
    add_datetime_to_instructions=True,
    show_tool_calls=True,
)

# Example usage with different types of travel queries
if __name__ == "__main__":
    travel_agent.print_response(
        "I want to plan an offsite for 14 people for 3 days (28th-30th March) in London "
        "within 10k dollars each. Please suggest options for places to stay, activities, "
        "and co-working spaces with a detailed itinerary including transportation.",
        stream=True,
    )

# More example prompts to explore:
"""
Corporate Events:
1. "Plan a team-building retreat in Costa Rica for 25 people"
2. "Organize a tech conference after-party in San Francisco"
3. "Design a wellness retreat in Bali for 15 employees"
4. "Create an innovation workshop weekend in Stockholm"

Cultural Experiences:
1. "Plan a traditional arts and crafts tour in Kyoto"
2. "Design a food and wine exploration in Tuscany"
3. "Create a historical journey through Ancient Rome"
4. "Organize a festival-focused trip to India"

Adventure Travel:
1. "Plan a hiking expedition in Patagonia"
2. "Design a safari experience in Tanzania"
3. "Create a diving trip in the Great Barrier Reef"
4. "Organize a winter sports adventure in the Swiss Alps"

Luxury Experiences:
1. "Plan a luxury wellness retreat in the Maldives"
2. "Design a private yacht tour of the Greek Islands"
3. "Create a gourmet food tour in Paris"
4. "Organize a luxury train journey through Europe"
"""
