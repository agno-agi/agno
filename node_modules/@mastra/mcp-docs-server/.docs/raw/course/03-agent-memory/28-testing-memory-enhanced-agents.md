# Testing Your Memory-Enhanced Agents

Let's test both of our memory-enhanced agents:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at `http://localhost:4111/`

## Testing the Memory Master Agent

1. Select your `MemoryMasterAgent`
2. Have a comprehensive conversation that tests all memory features:
   - Share personal information: "Hi, I'm Taylor. I live in Boston and work as a software engineer."
   - Discuss a project: "I'm working on a web application with a deadline next month."
   - Switch topics: "Let's talk about my vacation plans for the summer."
   - Return to the previous topic: "Remind me, what was the deadline for my web application?"
   - Ask about personal information: "What do you know about me so far?"

## Testing the Learning Assistant

1. Select your `Learning Assistant`
2. Have a conversation about learning programming:
   - "I want to learn Python programming. I'm a complete beginner."
   - "My learning style is visual - I learn best with diagrams and examples."
   - "Can you explain variables and data types in Python?"
   - "Now I'd like to learn about functions."
   - "Let's switch topics. I'm also interested in learning web development."
   - "I have some experience with HTML and CSS already."
   - "Can you go back to Python? I forgot how functions work."

Your agents should demonstrate all the memory capabilities we've explored:

- Remembering recent conversation context
- Recalling relevant information from older messages
- Maintaining persistent user information in working memory
- Using this information to provide personalized and contextual responses

These tests help verify that your memory-enhanced agents are working as expected and can effectively use all three memory features. Pay attention to how the agents handle context switches, recall information from earlier in the conversation, and maintain persistent information about the user or task.
