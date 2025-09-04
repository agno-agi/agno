# Testing Semantic Recall

Let's test our agent's semantic recall capabilities:

1. Update your agent code with the configuration above
2. Restart your development server with `npm run dev`
3. Open the playground at http://localhost:4111/
4. Select your "MemoryAgent"
5. Have a conversation with multiple topics:
   - "Let's talk about my work project first"
   - "I'm working on a new website for a client"
   - "The deadline is in two weeks"
   - "Now let's switch topics. I'm also planning a vacation"
   - "I'll be visiting Japan next month"
   - "I'll be staying in Tokyo and Kyoto"
   - "Let's talk about something else. I'm learning to play guitar"
   - "I practice for 30 minutes every day"
   - "Can you remind me about my work project deadline?"

Your agent should be able to recall the project deadline information, even though it was mentioned several messages ago and the conversation has moved on to other topics.

This test demonstrates how semantic recall allows your agent to find and retrieve relevant information from earlier in the conversation, even when that information is no longer included in the recent conversation history.

Try asking about other topics you discussed earlier to see how well your agent can retrieve different pieces of information. You can also experiment with different values for the `topK` and `messageRange` parameters to see how they affect your agent's ability to recall information.
