# Testing the Hacker News Integration

Let's test the Hacker News integration:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. Try asking your agent to perform Hacker News-related tasks, such as:
   - "What are the top stories on Hacker News today?"
   - "Find Hacker News discussions about AI agents"
   - "Summarize the comments on the top story"
   - "What's trending in tech on Hacker News?"

The first time you ask a Hacker News-related question, there might be a slight delay as the NPX command installs and starts the server. Subsequent queries should be faster.

Testing your Hacker News integration helps ensure that your agent can properly access and use the Hacker News tools. When you ask your agent about tech news or specific topics on Hacker News, it should recognize the need to use the appropriate Hacker News tool and make the necessary API calls to retrieve the requested information.
