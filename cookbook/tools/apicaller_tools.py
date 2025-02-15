from phi.agent import Agent
from phi.tools.apicaller import ApiCaller

"""
Use ApiCaller to generate functions from an OpenAPI spec and call APIs directly.

Prerequisites:
1. OpenAPI spec in JSON/YAML format (URL or local file path).
2. Swagger client for indirect API calls (optional):
    a. Set generate_swagger=True to auto-generate using generator3.swagger.io and save it to `swagger_clients` folder.
    b. Or, manually generate via editor.swagger.io and copy the swagger_client package to `swagger_clients` folder.
"""

# Petstore example
# Use any OpenAPI spec file
OPENAPI_SPEC = 'https://petstore3.swagger.io/api/v3/openapi.json'
# Generate swagger client and copy the client package to the current directory
CLIENT_PACKAGE = 'swagger_client'
agent = Agent(tools=[ApiCaller(CLIENT_PACKAGE, OPENAPI_SPEC,
                               generate_swagger=True,
                               configuration={'host': 'https://petstore3.swagger.io/api/v3'})],
              show_tool_calls=True)
agent.print_response("Get pet id 1", markdown=True)

# Spotify example

# # Use any OpenAPI spec file
# OPENAPI_SPEC = 'https://raw.githubusercontent.com/sonallux/spotify-web-api/refs/heads/main/official-spotify-open-api.yml'
# # Generate swagger client and copy the client package to the current directory
# CLIENT_PACKAGE = 'swagger_client'
# Sptofy access token
# ACCESS_TOKEN = 'ACCESS_TOKEN'
#swagger_caller = SwaggerCaller(CLIENT_PACKAGE, OPENAPI_SPEC, configuration={'access_token': ACCESS_TOKEN})

# agent = Agent(tools=[ApiCaller(CLIENT_PACKAGE, OPENAPI_SPEC,
#                                generate_swagger=True,
#                                configuration={'access_token': ACCESS_TOKEN}],
#               show_tool_calls=True, debug_mode=True)
# agent.print_response("make me a playlist with the first song from kind of blue. call it machine blues.", markdown=True)
