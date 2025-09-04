# Testing Working Memory

Let's test our agent's working memory capabilities:

1. Update your agent code with the configuration above
2. Restart your development server with `npm run dev`
3. Open the playground at http://localhost:4111/
4. Select your "MemoryAgent"
5. Have a conversation that reveals personal information:
   - "Hi, my name is Jordan"
   - "I live in Toronto, Canada"
   - "I prefer casual communication"
   - "I'm interested in artificial intelligence and music production"
   - "What do you know about me so far?"

Your agent should be able to recall all this information from its working memory, even if the conversation has moved on to other topics.

6. Continue the conversation with new topics, then ask again:
   - "Let's talk about the latest AI developments"
   - (Have a conversation about AI)
   - "What was my name again and where do I live?"

The agent should still remember this information because it's stored in working memory, not just in the conversation history.

This test demonstrates how working memory allows your agent to maintain persistent information about the user across different topics and conversation turns. Unlike conversation history, which only includes recent messages, working memory provides a structured way to store and retrieve important information about the user regardless of when it was mentioned.
