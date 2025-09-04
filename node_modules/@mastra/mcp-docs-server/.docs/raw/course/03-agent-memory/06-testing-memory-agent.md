# Testing Your Memory Agent

Let's test our basic memory agent:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. Select your "MemoryAgent" from the list of agents
4. Try having a conversation that tests basic memory capabilities:
   - "My name is Alex"
   - "What's my name?"
   - "I live in Seattle"
   - "Where do I live?"
   - "I prefer dark mode in my apps"
   - "What are my UI preferences?"

You should notice that your agent can remember information across these interactions. This is because the Mastra playground automatically handles the necessary resource and thread IDs for memory to work properly.

In the next step, we'll explore how to configure conversation history and understand how memory threads work.
