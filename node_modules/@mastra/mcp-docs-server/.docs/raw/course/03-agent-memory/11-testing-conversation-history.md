# Testing Conversation History

Let's update our agent and test the conversation history capabilities:

1. Update your agent code with the configuration above
2. Restart your development server with `npm run dev`
3. Open the playground at http://localhost:4111/
4. Select your "MemoryAgent"
5. Try having a longer conversation with multiple turns:
   - "Let me tell you about my vacation plans"
   - "I'm planning to visit Japan next month"
   - "I'll be staying in Tokyo for a week"
   - "Then I'll visit Kyoto for three days"
   - "What were my vacation plans again?"

Your agent should be able to recall the details of your vacation plans because it maintains the conversation history.

This test demonstrates how conversation history allows your agent to maintain context throughout a multi-turn conversation. The agent can recall information from previous messages without requiring the user to repeat themselves.

Try extending the conversation even further to see how well your agent maintains context over a longer interaction. You can also experiment with different values for the `lastMessages` option to see how it affects your agent's ability to recall information from earlier in the conversation.
