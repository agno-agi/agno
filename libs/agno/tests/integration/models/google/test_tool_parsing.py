from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel

from agno.models.google.gemini import Gemini
from agno.models.message import Message
from agno.tools.function import Function


def test_no_parameters_tool_parsing():
    def get_the_weather_in_tokyo() -> str:
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    tools = [{"type": "function", "function": Function.from_callable(get_the_weather_in_tokyo).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What is the weather in Tokyo?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_basic_parameters_tool_parsing():
    def get_weather(city: str, country: str = "Japan") -> str:
        """
        Get the weather for a city

        Args:
            city: The city to get the weather for
            country: The country the city is in
        """
        return f"It is currently 70 degrees and cloudy in {city}, {country}"

    tools = [{"type": "function", "function": Function.from_callable(get_weather).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What is the weather in Kyoto?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_optional_parameters_tool_parsing():
    def get_forecast(city: str, days: Optional[int] = None) -> str:
        """
        Get the weather forecast for a city

        Args:
            city: The city to get the forecast for
            days: The number of days for the forecast (default: 3)
        """
        days_count = days or 3
        return f"{days_count}-day forecast for {city}: Sunny with a chance of rain"

    tools = [{"type": "function", "function": Function.from_callable(get_forecast).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What's the 5-day forecast for New York?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_union_type_parameters_tool_parsing():
    def generate_weather_string(
        degrees: Union[int, float], city: str = "New York", condition: Optional[str] = None
    ) -> str:
        """
        Generate a weather string for any city

        Args:
            degrees: The temperature in degrees
            city: The city to get the weather for
            condition: The weather condition (e.g., cloudy, sunny, rainy)
        """
        weather_condition = condition if condition else "cloudy"
        return f"It is currently {degrees} degrees and {weather_condition} in {city}"

    tools = [{"type": "function", "function": Function.from_callable(generate_weather_string).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What's the weather like in Chicago at 75.5 degrees?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_python312_union_syntax_tool_parsing():
    def get_weather_data(temperature: int | float, location: str = "San Francisco", unit: str | None = None) -> str:
        """
        Get weather data for a location

        Args:
            temperature: The temperature value
            location: The location to get weather for
            unit: The temperature unit (celsius, fahrenheit, or kelvin)
        """
        unit = unit or "celsius"
        return f"The temperature in {location} is {temperature}°{unit[0].upper()}"

    tools = [{"type": "function", "function": Function.from_callable(get_weather_data).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What's the weather like in Chicago at 75.5 degrees?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_pydantic_model_parameters_tool_parsing():
    class City(BaseModel):
        name: str
        country: str
        population: Optional[int] = None

    def get_weather_for_city(city: City) -> str:
        """
        Get the weather for a city

        Args:
            city: The city to get the weather for
        """
        population_info = f" (pop: {city.population})" if city.population else ""
        return f"It is currently 70 degrees and cloudy in {city.name}, {city.country}{population_info}"

    tools = [{"type": "function", "function": Function.from_callable(get_weather_for_city).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What is the weather in Paris, France?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_complex_nested_parameters_tool_parsing():
    def travel_recommendation(
        destination: str, preferences: Dict[str, Any], budget_range: List[float], include_weather: bool = True
    ) -> str:
        """
        Get travel recommendations for a destination

        Args:
            destination: The destination to get recommendations for
            preferences: Dictionary of preferences like {'food': ['Italian', 'Japanese'], 'activities': ['hiking', 'museums']}
            budget_range: Min and max budget [min, max]
            include_weather: Whether to include weather information
        """
        return f"Here are your personalized recommendations for {destination}"

    tools = [{"type": "function", "function": Function.from_callable(travel_recommendation).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(
                role="user",
                content="I'm planning a trip to Barcelona. I like Spanish food and beach activities. My budget is between $1000 and $2000.",
            ),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_multiple_functions_tool_parsing():
    def get_weather(city: str) -> str:
        """Get the weather for a city"""
        return f"It is sunny in {city}"

    def get_time(timezone: str) -> str:
        """Get the current time for a timezone"""
        return f"The current time in {timezone} is 12:00 PM"

    tools = [
        {"type": "function", "function": Function.from_callable(get_weather).to_dict()},
        {"type": "function", "function": Function.from_callable(get_time).to_dict()},
    ]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="What's the weather in London and what time is it there?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_list_with_generics_tool_parsing():
    def get_city_weather_forecast(cities: List[str], days: int = 3) -> str:
        """
        Get weather forecast for multiple cities

        Args:
            cities: List of city names
            days: Number of days for forecast
        """
        return f"{days}-day forecast for {', '.join(cities)}: Variable conditions expected"

    tools = [{"type": "function", "function": Function.from_callable(get_city_weather_forecast).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(
                role="user", content="What's the weather forecast for New York, London, and Tokyo for the next 5 days?"
            ),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_tuple_with_fixed_types_tool_parsing():
    def get_temperature_range(location: str, date: str) -> str:
        """
        Get the temperature range for a location on a specific date

        Args:
            location: City or region name
            date: Date in YYYY-MM-DD format
        """
        return f"Temperature range for {location} on {date}: 65.0-85.0°F, Mostly sunny"

    tools = [{"type": "function", "function": Function.from_callable(get_temperature_range).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent."),
            Message(role="user", content="What's the temperature range in Miami for 2024-04-07?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_sequence_with_optional_values_tool_parsing():
    def get_historical_temperatures(
        city: str, dates: Sequence[str], include_humidity: Optional[List[bool]] = None
    ) -> str:
        """
        Get historical temperature data for a city on multiple dates

        Args:
            city: The city name
            dates: Sequence of dates in YYYY-MM-DD format
            include_humidity: Optional list of booleans indicating whether to include humidity for each date
        """
        return f"Historical temperature data for {city} on {len(dates)} dates"

    tools = [{"type": "function", "function": Function.from_callable(get_historical_temperatures).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(
                role="user",
                content="What were the temperatures in Chicago on June 15-17, 2023? Include humidity information.",
            ),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_optional_sequence_tool_parsing():
    def get_weather_alerts(region: str, severity: str = "all", affected_cities: Optional[List[str]] = None) -> str:
        """
        Get weather alerts for a region

        Args:
            region: Geographic region
            severity: Alert severity level (low, medium, high, or all)
            affected_cities: Optional list of cities to filter alerts for
        """
        cities_info = f" for cities: {', '.join(affected_cities)}" if affected_cities else ""
        return f"{severity} weather alerts for {region}{cities_info}"

    tools = [{"type": "function", "function": Function.from_callable(get_weather_alerts).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(role="user", content="Are there any high severity weather alerts in the Northeast region?"),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_mixed_sequence_types_tool_parsing():
    def get_trip_weather(
        destinations: List[str],
        travel_dates: Tuple[str, str],  # (start_date, end_date)
        optional_locations: Optional[Sequence[str]] = None,
    ) -> str:
        """
        Get weather for a multi-destination trip

        Args:
            destinations: List of primary destinations
            travel_dates: Tuple of (start_date, end_date) in YYYY-MM-DD format
            optional_locations: Optional sequence of secondary locations to visit
        """
        start, end = travel_dates
        optional = f" and {len(optional_locations)} optional locations" if optional_locations else ""
        return f"Weather forecast for {len(destinations)} destinations{optional} from {start} to {end}"

    tools = [{"type": "function", "function": Function.from_callable(get_trip_weather).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are an agent"),
            Message(
                role="user",
                content="I'm planning a trip to Paris and Rome from July 10 to July 20, 2024. I might also visit Florence and Venice. What's the weather outlook?",
            ),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0


def test_nested_pydantic_model_with_dict_tool_parsing():
    class Accommodation(BaseModel):
        hotel_name: str
        room_type: str
        amenities: List[str]
        price_per_night: float

    class Location(BaseModel):
        city: str
        country: str
        coordinates: Optional[Tuple[float, float]] = None

    class TravelPlan(BaseModel):
        location: Location
        accommodation: Accommodation
        duration_days: int
        travelers: int
        preferences: Dict[str, List[str]]
        budget: Optional[float] = None

    def plan_vacation(travel_plan: TravelPlan) -> str:
        """
        Create a vacation plan based on the provided details

        Args:
            travel_plan: The travel plan details including location, accommodation, and preferences
        """
        city = travel_plan.location.city
        country = travel_plan.location.country
        hotel = travel_plan.accommodation.hotel_name
        room = travel_plan.accommodation.room_type
        days = travel_plan.duration_days
        travelers = travel_plan.travelers

        food_prefs = ", ".join(travel_plan.preferences.get("food", []))
        activity_prefs = ", ".join(travel_plan.preferences.get("activities", []))

        budget_info = f" with a budget of ${travel_plan.budget}" if travel_plan.budget else ""

        return (
            f"Vacation plan for {travelers} travelers to {city}, {country} for {days} days{budget_info}. "
            f"Staying at {hotel} in a {room} room. "
            f"Food preferences: {food_prefs}. Activity preferences: {activity_prefs}."
        )

    tools = [{"type": "function", "function": Function.from_callable(plan_vacation).to_dict()}]
    model = Gemini()
    model.set_tools(tools)
    response = model.invoke(
        [
            Message(role="system", content="You are a travel agent assistant"),
            Message(
                role="user",
                content="I want to plan a trip to Paris, France for me and my partner for 7 days. We'd like to stay at The Grand Hotel in a deluxe room. We enjoy French cuisine and wine tastings, and want to visit museums and take walking tours. Our budget is $5000.",
            ),
        ]
    )
    assert response.function_calls is not None
    assert len(response.function_calls) > 0
