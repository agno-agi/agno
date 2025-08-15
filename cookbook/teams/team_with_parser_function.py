from typing import List, Any, Dict  # noqa
import random
import os
import json
import re

from agno.agent import Agent, RunResponse
from agno.models.openrouter import OpenRouter
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team import Team
from pydantic import BaseModel, Field
from rich.pretty import pprint


# Give a few flexible options for the JSON response.
DEFAULT_RESPONSE_PATTERNS = [
    # JSON code fence inside <response>
    r"<response[^>]*>\s*```\s*(?:json|JSON|Json)\s*(.*?)\s*```\s*</response>",
    # Bare JSON object/array inside <response>
    r"<response[^>]*>\s*(\{[\s\S]*?\})\s*</response>",
    r"<response[^>]*>\s*(\[[\s\S]*?\])\s*</response>",
    # Fallback: any <response> content (we will extract inner JSON later)
    r"<response[^>]*>\s*([\s\S]*?)\s*</response>",
    # Code fence with json (outside of response) as a last resort
    r"```\s*(?:json|JSON|Json)\s*(.*?)\s*```",
]


class NationalParkAdventure(BaseModel):
    park_name: str = Field(..., description="Name of the national park")
    best_season: str = Field(
        ...,
        description="Optimal time of year to visit this park (e.g., 'Late spring to early fall')",
    )
    signature_attractions: List[str] = Field(
        ...,
        description="Must-see landmarks, viewpoints, or natural features in the park",
    )
    recommended_trails: List[str] = Field(
        ...,
        description="Top hiking trails with difficulty levels (e.g., 'Angel's Landing - Strenuous')",
    )
    wildlife_encounters: List[str] = Field(
        ..., description="Animals visitors are likely to spot, with viewing tips"
    )
    photography_spots: List[str] = Field(
        ...,
        description="Best locations for capturing stunning photos, including sunrise/sunset spots",
    )
    camping_options: List[str] = Field(
        ..., description="Available camping areas, from primitive to RV-friendly sites"
    )
    safety_warnings: List[str] = Field(
        ..., description="Important safety considerations specific to this park"
    )
    hidden_gems: List[str] = Field(
        ..., description="Lesser-known spots or experiences that most visitors miss"
    )
    difficulty_rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="Overall park difficulty for average visitor (1=easy, 5=very challenging)",
    )
    estimated_days: int = Field(
        ...,
        ge=1,
        le=14,
        description="Recommended number of days to properly explore the park",
    )
    special_permits_needed: List[str] = Field(
        default=[],
        description="Any special permits or reservations required for certain activities",
    )


def parse_chain_of_thought_to_json(text: str) -> Dict[str, Any]:
    print(text)

    def _sanitize(s: str) -> str:
        # Remove BOM and zero-width / non-breaking spaces that can break json.loads
        invisible_chars = [
            "\ufeff",  # BOM
            "\u200b",  # zero-width space
            "\u200c",  # zero-width non-joiner
            "\u200d",  # zero-width joiner
            "\u2060",  # word joiner
            "\xa0",  # non-breaking space
        ]
        for ch in invisible_chars:
            s = s.replace(ch, "")
        return s.strip()

    for pattern in DEFAULT_RESPONSE_PATTERNS:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            candidate = _sanitize(match.group(1))
            # If the model explicitly returned JSON null
            if candidate == "null":
                return None, reasoning  # type: ignore[return-value]
            # Quick guard: only attempt json if plausible start
            if not candidate.startswith("{") and not candidate.startswith("["):
                # Attempt to extract the first JSON object/array within the candidate
                inner = re.search(r"(\{[\s\S]*\})", candidate)
                if not inner:
                    inner = re.search(r"(\[[\s\S]*\])", candidate)
                if inner:
                    candidate = _sanitize(inner.group(1))
                else:
                    continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as e:
                # Try next pattern instead of failing immediately
                continue
    raise ValueError("No valid JSON found")


def parser_function_chain_of_thought(
    text: str, allow_none: bool = False
) -> NationalParkAdventure:

    none_clause = (
        "\n- If there is no valid result, return a literal JSON null inside <response> (i.e., null)"
        if allow_none
        else ""
    )

    fast_json_parser.instructions += f"""

You must analyze the given input and respond using a specific format with two sections:

1. **Think**: Use <think></think> tags to work through your reasoning step by step
2. **Response**: Use <response></response> tags to provide valid JSON that matches the required schema

**Output Format:**
<think>
[Your step-by-step analysis and reasoning here]
</think>
<response>
[Valid JSON object that conforms to the schema below]
</response>

**Required JSON Schema:**
{NationalParkAdventure.model_json_schema()}

**Critical Requirements:**
- The JSON in <response> tags must be valid and parseable
- The JSON must conform exactly to the provided schema
- Include all required fields from the schema
- Use appropriate data types (strings, numbers, booleans, arrays, objects)
{none_clause}

"""
    response = fast_json_parser.run(text)
    json_response = parse_chain_of_thought_to_json(response.content)
    # Allow explicit null to represent no result
    if allow_none and json_response is None:
        return None
    return NationalParkAdventure(**json_response)


OR_GPT_OSS_120B = OpenRouter(
    id="openai/gpt-oss-120b",
    api_key=os.environ["OPENROUTER_API_KEY"],
    request_params={
        "extra_body": {
            "provider": {"order": ["cerebras", "groq"], "allow_fallbacks": True}
        }
    },
    max_tokens=10000,
)

itinerary_planner = Agent(
    name="Itinerary Planner",
    model=OR_GPT_OSS_120B,
    description="You help people plan amazing national park adventures and provide detailed park guides.",
)

weather_expert = Agent(
    name="Weather Expert",
    model=OR_GPT_OSS_120B,
    description="You are a weather expert and can provide detailed weather information for a given location.",
)

fast_json_parser = Agent(
    name="Fast JSON Parser",
    model=OR_GPT_OSS_120B,
    description="You are a fast JSON parser and can parse JSON strings into a structured output.",
    instructions="You are an expert at converting data into JSON.",
)

national_park_expert = Team(
    model=OR_GPT_OSS_120B,
    members=[itinerary_planner, weather_expert],
    parser_function=parser_function_chain_of_thought,
)


# Get the response in a variable
national_parks = [
    "Yellowstone National Park",
    "Yosemite National Park",
    "Grand Canyon National Park",
    "Zion National Park",
    "Grand Teton National Park",
    "Rocky Mountain National Park",
    "Acadia National Park",
    "Mount Rainier National Park",
    "Great Smoky Mountains National Park",
    "Rocky National Park",
]
# Get the response in a variable
run: RunResponse = national_park_expert.run(
    f"What is the best season to visit {national_parks[random.randint(0, len(national_parks) - 1)]}? Please provide a detailed one week itinerary for a visit to the park."
)
pprint(run.content)

# Stream the response
# run_events: Iterator[RunResponseEvent] = national_park_expert.run(f"What is the best season to visit {national_parks[random.randint(0, len(national_parks) - 1)]}? Please provide a detailed one week itinerary for a visit to the park.", stream=True)
# for event in run_events:
#     pprint(event)
