"""
Steps to get Reddit credentials:

1. Create/Login to Reddit account
   - Go to https://www.reddit.com

2. Create a Reddit App
   - Go to https://www.reddit.com/prefs/apps
   - Click "Create App" or "Create Another App" button
   - Fill in required details:
     * Name: Your app name
     * App type: Select "script"
     * Description: Brief description
     * About url: Your website (can be http://localhost)
     * Redirect uri: http://localhost:8080
   - Click "Create app" button

3. Get credentials
   - client_id: Found under your app name (looks like a random string)
   - client_secret: Listed as "secret"
   - user_agent: Format as: "platform:app_id:version (by /u/username)"
   - username: Your Reddit username
   - password: Your Reddit account password

"""

from agno.agent import Agent
from agno.tools.reddit import RedditTools

agent = Agent(
    instructions=[
        "Use your tools to answer questions about Reddit content and statistics",
        "Respect Reddit's content policies and NSFW restrictions",
        "When analyzing subreddits, provide relevant statistics and trends",
    ],
    tools=[RedditTools()],
    show_tool_calls=True,
)

agent.print_response("What are the top 5 posts on r/SAAS this week ?", stream=True)
