import asyncio
import json

import httpx
from agno.agent import Agent
from agno.tools import tool


class DemoTools:
    @tool(description="Get the top hackernews stories")
    @staticmethod
    async def get_top_hackernews_stories(agent: Agent):
        num_stories = (
            agent.dependencies.get("num_stories", 5) if agent.dependencies else 5
        )

        # Fetch top story IDs
        response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        story_ids = response.json()

        # Get story details
        for story_id in story_ids[:num_stories]:
            async with httpx.AsyncClient() as client:
                story_response = await client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
            story = story_response.json()
            if "text" in story:
                story.pop("text", None)
            return json.dumps(story)

    @tool(
        description="Get the current weather for a city using the MetaWeather public API"
    )
    @staticmethod
    async def get_current_weather(agent: Agent):
        city = (
            agent.dependencies.get("city", "San Francisco")
            if agent.dependencies
            else "San Francisco"
        )

        async with httpx.AsyncClient() as client:
            # Geocode city to get latitude and longitude
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "en", "format": "json"},
            )
            geo_data = geo_resp.json()
            if not geo_data.get("results"):
                return json.dumps({"error": f"City '{city}' not found."})
            location = geo_data["results"][0]
            lat, lon = location["latitude"], location["longitude"]

            # Get current weather
            weather_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": True,
                    "timezone": "auto",
                },
            )
            weather_data = weather_resp.json()
            current_weather = weather_data.get("current_weather")
            if not current_weather:
                return json.dumps({"error": f"No weather data found for '{city}'."})

            result = {
                "city": city,
                "weather_state": f"{current_weather['weathercode']}",  # Open-Meteo uses weather codes
                "temp_celsius": current_weather["temperature"],
                "humidity": None,  # Open-Meteo current_weather does not provide humidity
                "date": current_weather["time"],
            }
            return json.dumps(result)


agent = Agent(
    name="HackerNewsAgent",
    dependencies={
        "num_stories": 2,
    },
    tools=[DemoTools.get_top_hackernews_stories],
)
asyncio.run(agent.aprint_response("What are the top hackernews stories?"))


agent = Agent(
    name="WeatherAgent",
    dependencies={
        "city": "San Francisco",
    },
    tools=[DemoTools().get_current_weather],
)
asyncio.run(agent.aprint_response("What is the weather like?"))
