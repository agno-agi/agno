"""
Google Maps Tools - Location and Business Information Agent

This example demonstrates various Google Maps API functionalities including business search,
directions, geocoding, address validation, and more. Shows how to use include_tools and
exclude_tools parameters for selective function access.

Prerequisites:
- Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
  You can obtain the API key from the Google Cloud Console:
  https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

- You also need to activate the Address Validation API for your project:
  https://console.developers.google.com/apis/api/addressvalidation.googleapis.com

"""

from agno.agent import Agent
from agno.tools.crawl4ai import Crawl4aiTools
from agno.tools.google_maps import GoogleMapTools

# Example 1: All functions available (default behavior)
agent_full = Agent(
    name="Full Maps API Agent",
    tools=[
        GoogleMapTools(),  # All functions enabled by default
        Crawl4aiTools(max_length=5000),
    ],
    description="You are a location and business information specialist with full Google Maps access.",
    instructions=[
        "Use any Google Maps function as needed for location-based queries",
        "Combine Maps data with website data when available",
        "Format responses clearly and provide relevant details",
        "Handle errors gracefully and provide meaningful feedback",
    ],
    markdown=True,
)

# Example 2: Include only specific functions
agent_search = Agent(
    name="Search-focused Maps Agent",
    tools=[
        GoogleMapTools(
            include_tools=[
                "search_places",
            ]
        ),
    ],
    description="You are a location search specialist focused only on finding places.",
    instructions=[
        "Focus on place searches and getting place details",
        "Use search_places for general queries",
        "Use find_place_from_text for specific place names",
        "Use get_nearby_places for proximity searches",
    ],
    markdown=True,
)

# Example 3: Exclude potentially expensive operations
agent_safe = Agent(
    name="Safe Maps API Agent",
    tools=[
        GoogleMapTools(
            exclude_tools=[
                "get_distance_matrix",  # Can be expensive with many origins/destinations
                "get_directions",  # Excludes detailed route calculations
            ]
        ),
        Crawl4aiTools(max_length=3000),
    ],
    description="You are a location specialist with restricted access to expensive operations.",
    instructions=[
        "Provide location information without detailed routing",
        "Use geocoding and place searches freely",
        "For directions, provide general guidance only",
    ],
    markdown=True,
)

# Using the full-featured agent for examples
agent = agent_full

# Example 1: Business Search
print("\n=== Business Search Example ===")
agent.print_response(
    "Find me highly rated Chinese restaurants in Phoenix, AZ with their contact details",
    stream=True,
)

# Example 2: Directions
print("\n=== Directions Example ===")
agent.print_response(
    """Get driving directions from 'Phoenix Sky Harbor Airport' to 'Desert Botanical Garden',
    avoiding highways if possible""",
    stream=True,
)

# Example 3: Address Validation and Geocoding
print("\n=== Address Validation and Geocoding Example ===")
agent.print_response(
    """Please validate and geocode this address:
    '1600 Amphitheatre Parkway, Mountain View, CA'""",
    stream=True,
)

# Example 4: Distance Matrix
print("\n=== Distance Matrix Example ===")
agent.print_response(
    """Calculate the travel time and distance between these locations in Phoenix:
    Origins: ['Phoenix Sky Harbor Airport', 'Downtown Phoenix']
    Destinations: ['Desert Botanical Garden', 'Phoenix Zoo']""",
    stream=True,
)

# Example 5: Nearby Places and Details
print("\n=== Nearby Places Example ===")
agent.print_response(
    """Find coffee shops near Arizona State University Tempe campus.
    Include ratings and opening hours if available.""",
    stream=True,
)

# Example 6: Reverse Geocoding and Timezone
print("\n=== Reverse Geocoding and Timezone Example ===")
agent.print_response(
    """Get the address and timezone information for these coordinates:
    Latitude: 33.4484, Longitude: -112.0740 (Phoenix)""",
    stream=True,
)

# Example 7: Multi-step Route Planning
print("\n=== Multi-step Route Planning Example ===")
agent.print_response(
    """Plan a route with multiple stops in Phoenix:
    Start: Phoenix Sky Harbor Airport
    Stops:
    1. Arizona Science Center
    2. Heard Museum
    3. Desert Botanical Garden
    End: Return to Airport
    Please include estimated travel times between each stop.""",
    stream=True,
)

# Example 8: Location Analysis
print("\n=== Location Analysis Example ===")
agent.print_response(
    """Analyze this location in Phoenix:
    Address: '2301 N Central Ave, Phoenix, AZ 85004'
    Please provide:
    1. Exact coordinates
    2. Nearby landmarks
    3. Elevation data
    4. Local timezone""",
    stream=True,
)

# Example 9: Business Hours and Accessibility
print("\n=== Business Hours and Accessibility Example ===")
agent.print_response(
    """Find museums in Phoenix that are:
    1. Open on Mondays
    2. Have wheelchair accessibility
    3. Within 5 miles of downtown
    Include their opening hours and contact information.""",
    stream=True,
)

# Example 10: Transit Options
print("\n=== Transit Options Example ===")
agent.print_response(
    """Compare different travel modes from 'Phoenix Convention Center' to 'Phoenix Art Museum':
    1. Driving
    2. Walking
    3. Transit (if available)
    Include estimated time and distance for each option.""",
    stream=True,
)
