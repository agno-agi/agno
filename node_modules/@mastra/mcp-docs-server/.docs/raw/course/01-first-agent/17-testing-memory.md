# Testing Your Agent with Memory

Let's test our agent's memory capabilities in the playground:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. Start a conversation with your agent by asking about transactions
4. Then, ask a follow-up question that references the previous conversation, like:
   - "What was that largest transaction again?"
   - "Can you categorize those Amazon purchases we talked about?"
   - "How does my spending this month compare to what you showed me earlier?"

Your agent should now be able to remember previous conversations and provide more contextual responses.

With memory enabled, your agent can now maintain context across multiple interactions, creating a more natural and helpful user experience. This is especially important for financial assistants, where users may want to refer back to previous information or build on earlier conversations.
