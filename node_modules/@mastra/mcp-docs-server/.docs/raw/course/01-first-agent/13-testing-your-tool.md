# Testing Your Tool

Let's test our tool and agent in the playground:

1. Make sure your development server is running with `npm run dev`
2. Open the playground at http://localhost:4111/
3. You can test the tool directly in the Tools tab to make sure it's working
4. Then, try asking your agent questions like:
   - "Can you show me my recent transactions?"
   - "How much did I spend on Amazon?"
   - "What was my largest transaction this month?"

Your agent should now be able to fetch the transaction data and answer questions about it. However, it doesn't yet have memory, so it won't remember previous conversations. We'll add that in the next step.

Testing your tool directly in the playground is a great way to verify that it's working correctly before integrating it with your agent. This helps you identify and fix any issues with the tool itself before troubleshooting potential issues with the agent's use of the tool.
