"""
Business Contact Search Agent for finding and extracting business contact information.
This example demonstrates various Google Maps API functionalities including business search,
directions, geocoding, address validation, and more.

Prerequisites:
- Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
  You can obtain the API key from the Google Cloud Console:
  https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

- You also need to activate the Address Validation API for your .
  https://console.developers.google.com/apis/api/addressvalidation.googleapis.com

"""

from agno.agent import Agent
from agno.tools.crawl4ai import Crawl4aiTools
from agno.tools.google_maps import GoogleMapTools

agent = Agent(
    name="Maps API Demo Agent",
    tools=[
        GoogleMapTools(),  # For  on Google Maps
        Crawl4aiTools(max_length=5000),  # For scraping business websites
    ],
    description="You are a location and business information specialist that can help with various mapping and location-based queries.",
    instructions=[
        "When given a search query:",
        "1. Use appropriate Google Maps methods based on the query type",
        "2. For place searches, combine Maps data with website data when available",
        "3. Format responses clearly and provide relevant details based on the query",
        "4. Handle errors gracefully and provide meaningful feedback",
    ],
    markdown=True,
    show_tool_calls=True,
)

# Example 1: Business Search
print("\n=== Business Search Example ===")
agent.print_response(
    "Find me highly rated Indian restaurants in Phoenix, AZ with their contact details",
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
