from agno.agent import Agent
from agno.tools.x import XTools

"""
To set up an X developer account and obtain the necessary keys, follow these steps:

1. **Create an X Developer Account:**
   - Go to the X Developer website: https://developer.x.com/
   - Sign in with your X account or create a new one if you don't have an account.
   - Apply for a developer account by providing the required information about your intended use of the X API.

2. **Create a Project and App:**
   - Once your developer account is approved, log in to the X Developer portal.
   - Navigate to the "Projects & Apps" section and create a new project.
   - Within the project, create a new app. This app will be used to generate the necessary API keys and tokens.
   - You'll get a client id and client secret, but you can ignore them.

3. **Generate API Keys, Tokens, and Client Credentials:**
   - After creating the app, navigate to the "Keys and tokens" tab.
   - Generate the following keys, tokens, and client credentials:
     - **API Key (Consumer Key)**
     - **API Secret Key (Consumer Secret)**
     - **Bearer Token**
     - **Access Token**
     - **Access Token Secret**

4. **Set Environment Variables:**
   - Export the generated keys, tokens, and client credentials as environment variables in your system or provide them as arguments to the `XTools` constructor.
     - `X_CONSUMER_KEY`
     - `X_CONSUMER_SECRET`
     - `X_ACCESS_TOKEN`
     - `X_ACCESS_TOKEN_SECRET`
     - `X_BEARER_TOKEN`
"""


# Initialize the x toolkit
x_tools = XTools()

# Create an agent with the X toolkit
agent = Agent(
    instructions=[
        "Use your tools to interact with X (Twitter) as the authorized user @AgnoAgi",
        "When asked to create a post, generate appropriate content based on the request",
        "Do not actually post content unless explicitly instructed to do so",
        "Provide informative responses about the user's timeline and posts",
        "Respect X's usage policies and rate limits",
    ],
    tools=[x_tools],
)

# Example usage: Get your details
agent.print_response(
    "Can you return my x profile with my home timeline?", markdown=True
)

# # Example usage: Get information about a user
# agent.print_response(
#     "Can you retrieve information about this user https://x.com/AgnoAgi ",
#     markdown=True,
# )

# # Example usage: Reply To a Post
# agent.print_response(
#     "Can you reply to this [post ID] post as a general message as to how great this project is: https://x.com/AgnoAgi",
#     markdown=True,
# )

# # Example usage: Send a direct message
# agent.print_response(
#     "Send direct message to the user @AgnoAgi telling them I want to learn more about them and a link to their community.",
#     markdown=True,
# )

# # Example usage: Create a new post
# agent.print_response("Create & post content about how 2025 is the year of the AI agent", markdown=True)
