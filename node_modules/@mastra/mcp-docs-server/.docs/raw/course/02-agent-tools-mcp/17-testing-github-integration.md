# Testing the GitHub Integration

Let's test the GitHub integration:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. Try asking your agent to perform GitHub-related tasks, such as:
   - "Check the recent activity on my repository"
   - "Summarize the open pull requests"
   - "What are the latest commits on the main branch?"
   - "Are there any issues that need my attention?"

If everything is set up correctly, your agent should be able to use the GitHub tools to provide this information.

Testing your GitHub integration helps ensure that your agent can properly access and use the GitHub tools. When you ask your agent about GitHub-related information, it should recognize the need to use the appropriate GitHub tool and make the necessary API calls to retrieve the requested information.
