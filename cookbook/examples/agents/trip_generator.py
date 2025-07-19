from agno.agent import Agent
from agno.models.google import Gemini

agent1: Agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    markdown=True
)

numberOfDays=5
country="Tanzania"
interests="Museums & Art"
travelStyle="Relaxed"
groupType="Family"
budget="Mid-range"

agent1.print_response(f"""
  Generate a {numberOfDays}-day travel itinerary for {country} based on the following user information:
  Budget: '{numberOfDays}'
  Interests: '{interests}'
  TravelStyle: '{travelStyle}'
  GroupType: '{groupType}'
  Return the itinerary and lowest estimated price in a clean, non-markdown JSON format with the following structure:
  {{
      "name": "A descriptive title for the trip",
      "description": "A brief description of the trip and its highlights not exceeding 100 words",
      "estimatedPrice": "Lowest average price for the trip in USD, e.g.$price",
      "duration": {numberOfDays},
      "budget": "{budget}",
      "travelStyle": "{travelStyle}",
      "country": "{country}",
      "interests": {interests},
      "groupType": "{groupType}",
      "bestTimeToVisit": [
        '🌸 Season (from month to month): reason to visit',
        '☀️ Season (from month to month): reason to visit',
        '🍁 Season (from month to month): reason to visit',
        '❄️ Season (from month to month): reason to visit'
      ],
      "weatherInfo": [
        '☀️ Season: temperature range in Celsius (temperature range in Fahrenheit)',
        '🌦️ Season: temperature range in Celsius (temperature range in Fahrenheit)',
        '🌧️ Season: temperature range in Celsius (temperature range in Fahrenheit)',
        '❄️ Season: temperature range in Celsius (temperature range in Fahrenheit)'
      ],
      "location": {{
        "city": "name of the city or region",
        "coordinates": [latitude, longitude],
        "openStreetMap": "link to open street map"
      }},
      "itinerary": [
          {{
            "day": 1,
            "location": "City/Region Name",
            "activities": [
              {{"time": "Morning", "description": "🏰 Visit the local historic castle and enjoy a scenic walk"}},
              {{"time": "Afternoon", "description": "🖼️ Explore a famous art museum with a guided tour"}},
              {{"time": "Evening", "description": "🍷 Dine at a rooftop restaurant with local wine"}}
            ]
          }},
          ...
      ]
  }}
""", stream=True)
