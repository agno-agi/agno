import json
import os
import string
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    from apify_client import ApifyClient
except ImportError:
    raise ImportError("`apify-client` not installed. Please install using `pip install apify-client`")


class ApifyTools(Toolkit):
    def __init__(self, actors: Optional[Union[str, List[str]]] = None, apify_api_token: Optional[str] = None):
        """Initialize ApifyTools with specific Actors.

        Args:
            actors (Optional[Union[str, List[str]]]): Single Actor ID as string or list of Actor IDs to register as individual tools
            apify_api_token (Optional[str]): Apify API token (defaults to APIFY_API_TOKEN env variable)

        Examples:
            Configuration Instructions:
            1. Install required dependencies:
            pip install agno apify-client

            2. Set the APIFY_API_TOKEN environment variable:
            Add a .env file with APIFY_API_TOKEN=your_apify_api_key

            Import necessary components:

            from agno.agent import Agent
            from agno.tools.apify import ApifyTools

            # Create an agent with ApifyTools
            agent = Agent(
                tools=[
                    ApifyTools(actors=["apify/rag-web-browser"])
                ],
                markdown=True
            )

            # Ask the agent to process web content
            agent.print_response("Summarize the content from https://docs.agno.com/introduction", markdown=True)

            # Using multiple actors with the agent
            agent = Agent(
                tools=[
                    ApifyTools(actors=[
                        "apify/rag-web-browser",
                        "compass/crawler-google-places"
                    ])
                ],
                show_tool_calls=True
            )
            agent.print_response(
                '''
                I'm traveling to Tokyo next month.
                1. Research the best time to visit and major attractions
                2. Find one good rated sushi restaurant near Shinjuku
                Compile a comprehensive travel guide with this information.
                ''',
                markdown=True
            )
        """
        # Get API token from args or environment
        self.apify_api_token = apify_api_token or os.getenv("APIFY_API_TOKEN")
        if not self.apify_api_token:
            raise ValueError("APIFY_API_TOKEN environment variable or apify_api_token parameter must be set")

        self.client = create_apify_client(self.apify_api_token)

        tools: List[Any] = []
        if actors:
            actor_list = [actors] if isinstance(actors, str) else actors
            for actor_id in actor_list:
                tools.append(actor_id)

        super().__init__(name="ApifyTools", tools=[], auto_register=False)

        for actor_id in tools:
            self.register_actor(actor_id)

    def register_actor(self, actor_id: str) -> None:
        """Register an Apify Actor as a function in the toolkit.

        Args:
            actor_id (str): ID of the Apify Actor to register (e.g., 'apify/web-scraper')
        """
        try:
            # Get actor metadata
            build = get_actor_latest_build(self.client, actor_id)
            tool_name = actor_id_to_tool_name(actor_id)

            # Get actor description
            actor_description = build.get("actorDefinition", {}).get("description", "")
            if len(actor_description) > MAX_DESCRIPTION_LEN:
                actor_description = actor_description[:MAX_DESCRIPTION_LEN] + "...(TRUNCATED, TOO LONG)"

            # Get input schema
            actor_input = build.get("actorDefinition", {}).get("input")
            if not actor_input:
                raise ValueError(f"Input schema not found in the Actor build for Actor: {actor_id}")

            properties, required = prune_actor_input_schema(actor_input)

            # Create a wrapper function that calls the Actor
            def actor_function(**kwargs) -> str:
                """Actor function wrapper."""
                try:
                    # Params are nested under 'kwargs' key
                    if len(kwargs) == 1 and "kwargs" in kwargs:
                        kwargs = kwargs["kwargs"]

                    log_info(f"Running Apify Actor {actor_id} with parameters: {kwargs}")

                    # Run the Actor directly with the client
                    details = self.client.actor(actor_id=actor_id).call(run_input=kwargs)
                    if details is None:
                        error_msg = (
                            f"Actor: {actor_id} was not started properly and details about the run were not returned"
                        )
                        raise ValueError(error_msg)

                    run_id = details.get("id")
                    if run_id is None:
                        error_msg = f"Run ID not found in the run details for Actor: {actor_id}"
                        raise ValueError(error_msg)

                    # Get the results
                    run = self.client.run(run_id=run_id)
                    results = run.dataset().list_items(clean=True).items

                    return json.dumps(results)

                except Exception as e:
                    error_msg = f"Error running Apify Actor {actor_id}: {str(e)}"
                    logger.error(error_msg)
                    return json.dumps([{"error": error_msg}])

            docstring = f"{actor_description}\n\nArgs:\n"

            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "No description available")
                required_marker = "(required)" if param_name in required else "(optional)"
                docstring += f"    {param_name} ({param_type}): {required_marker} {param_desc}\n"

            docstring += """
Returns:
    str: JSON string containing the Actor's output dataset
"""

            # Update function metadata
            actor_function.__name__ = tool_name
            actor_function.__doc__ = docstring

            # Register the function with the toolkit
            self.register(actor_function)
            # Fix params schema
            self.functions[tool_name].parameters = props_to_json_schema(properties, required)
            log_info(f"Registered Apify Actor '{actor_id}' as function '{tool_name}'")

        except Exception as e:
            logger.error(f"Failed to register Apify Actor '{actor_id}': {str(e)}")


# Constants
MAX_DESCRIPTION_LEN = 350
REQUESTS_TIMEOUT_SECS = 300
APIFY_API_ENDPOINT_GET_DEFAULT_BUILD = "https://api.apify.com/v2/acts/{actor_id}/builds/default"


# Utility functions
def props_to_json_schema(input_dict, required_fields=None):
    schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": required_fields or []}

    def infer_array_item_type(prop):
        type_map = {
            "string": "string",
            "int": "number",
            "float": "number",
            "dict": "object",
            "list": "array",
            "bool": "boolean",
            "none": "null",
        }
        if prop.get("items", {}).get("type"):
            return prop["items"]["type"]
        if "prefill" in prop and prop["prefill"] and len(prop["prefill"]) > 0:
            return type_map.get(type(prop["prefill"][0]).__name__.lower(), "string")
        if "default" in prop and prop["default"] and len(prop["default"]) > 0:
            return type_map.get(type(prop["default"][0]).__name__.lower(), "string")
        return "string"  # Fallback for arrays like searchStringsArray

    for key, value in input_dict.items():
        prop_schema: Dict[str, Any] = {}
        prop_type = value.get("type")

        if "enum" in value:
            prop_schema["enum"] = value["enum"]

        if "default" in value:
            prop_schema["default"] = value["default"]
        elif "prefill" in value:
            prop_schema["default"] = value["prefill"]

        if "description" in value:
            prop_schema["description"] = value["description"]

        # Handle Apify special types first
        if prop_type == "object" and value.get("editor") == "proxy":
            prop_schema["type"] = "object"
            prop_schema["properties"] = {
                "useApifyProxy": {
                    "title": "Use Apify Proxy",
                    "type": "boolean",
                    "description": "Whether to use Apify Proxy - ALWAYS SET TO TRUE.",
                    "default": True,
                    "examples": [True],
                }
            }
            prop_schema["required"] = ["useApifyProxy"]
            if "default" in value:
                prop_schema["default"] = value["default"]

        elif prop_type == "array" and value.get("editor") == "requestListSources":
            prop_schema["type"] = "array"
            prop_schema["items"] = {
                "type": "object",
                "title": "Request list source",
                "description": "Request list source",
                "properties": {
                    "url": {"title": "URL", "type": "string", "description": "URL of the request list source"}
                },
            }

        elif prop_type == "array":
            prop_schema["type"] = "array"
            prop_schema["items"] = {
                "type": infer_array_item_type(value),
                "title": value.get("title", "Item"),
                "description": "Item",
            }

        elif prop_type == "object":
            prop_schema["type"] = "object"
            if "default" in value:
                prop_schema["default"] = value["default"]
                prop_schema["properties"] = {}
                for k, v in value.get("properties", value["default"]).items():
                    prop_type = v["type"] if isinstance(v, dict) else type(v).__name__.lower()
                    if prop_type == "bool":
                        prop_type = "boolean"
                    prop_schema["properties"][k] = {"type": prop_type}

        else:
            prop_schema["type"] = prop_type

        schema["properties"][key] = prop_schema

    return schema


def create_apify_client(token: str) -> ApifyClient:
    """Create an Apify client instance with a custom user-agent.

    Args:
        token (str): API token

    Returns:
        ApifyClient: Apify client instance

    Raises:
        ValueError: If the API token is not provided
    """
    if not token:
        raise ValueError("API token is required to create an Apify client.")

    client = ApifyClient(token)
    if http_client := getattr(client.http_client, "httpx_client", None):
        http_client.headers["user-agent"] += "; Origin/agno"
    return client


def actor_id_to_tool_name(actor_id: str) -> str:
    """Turn actor_id into a valid tool name.

    Args:
        actor_id (str): Actor ID from Apify store

    Returns:
        str: A valid tool name
    """
    valid_chars = string.ascii_letters + string.digits + "_-"
    return "apify_actor_" + "".join(char if char in valid_chars else "_" for char in actor_id)


def get_actor_latest_build(apify_client: ApifyClient, actor_id: str) -> Dict[str, Any]:
    """Get the latest build of an Actor from the default build tag.

    Args:
        apify_client (ApifyClient): An instance of the ApifyClient class
        actor_id (str): Actor name from Apify store to run

    Returns:
        Dict[str, Any]: The latest build of the Actor

    Raises:
        ValueError: If the Actor is not found or the build data is not found
        TypeError: If the build is not a dictionary
    """
    if not (actor := apify_client.actor(actor_id).get()):
        raise ValueError(f"Actor {actor_id} not found.")

    if not (actor_obj_id := actor.get("id")):
        raise ValueError(f"Failed to get the Actor object ID for {actor_id}.")

    url = APIFY_API_ENDPOINT_GET_DEFAULT_BUILD.format(actor_id=actor_obj_id)
    response = requests.request("GET", url, timeout=REQUESTS_TIMEOUT_SECS)

    build = response.json()
    if not isinstance(build, dict):
        raise TypeError(f"Failed to get the latest build of the Actor {actor_id}.")

    if (data := build.get("data")) is None:
        raise ValueError(f"Failed to get the latest build data of the Actor {actor_id}.")

    return data


def prune_actor_input_schema(input_schema: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Get the input schema from the Actor build and trim descriptions.

    Args:
        input_schema (Dict[str, Any]): The input schema from the Actor build

    Returns:
        Tuple[Dict[str, Any], List[str]]: A tuple containing the pruned properties and required fields
    """
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    properties_out: Dict[str, Any] = {}
    for item, meta in properties.items():
        properties_out[item] = {}
        if desc := meta.get("description"):
            properties_out[item]["description"] = (
                desc[:MAX_DESCRIPTION_LEN] + "..." if len(desc) > MAX_DESCRIPTION_LEN else desc
            )
        for key_name in ("type", "default", "prefill", "enum"):
            if value := meta.get(key_name):
                properties_out[item][key_name] = value

    return properties_out, required
