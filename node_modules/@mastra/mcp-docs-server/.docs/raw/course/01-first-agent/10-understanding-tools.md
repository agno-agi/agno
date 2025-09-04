# Understanding Tools in Mastra

Tools in Mastra are functions that your agent can call to perform specific tasks. They extend your agent's capabilities by giving it access to external data sources, APIs, and functionality beyond what's available in the language model itself.

Each tool has:

- A unique ID that the agent uses to reference it
- A clear description of what it does, which helps the agent understand when to use it
- Input and output schemas that define the expected parameters and return values
- An execute function that performs the actual work

Tools are a powerful way to enhance your agent's abilities. They allow your agent to interact with the outside world, access specific data sources, and perform actions that would otherwise be impossible for a language model alone.

In the next step, we'll create a custom tool that fetches transaction data from a Google Sheet.
