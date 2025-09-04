# How Working Memory Works

Working memory is implemented as a block of Markdown text that the agent can update over time. The agent reads this information at the beginning of each conversation and can update it as new information becomes available.

When a user shares information that should be remembered long-term (like their name, location, or preferences), the agent can update the working memory to include this information. In subsequent conversations, the agent will have access to this information without the user having to repeat it.

The working memory is stored in a structured format, typically as Markdown, which makes it easy for the agent to read and update. This structure helps guide the agent on what information to track and how to organize it.

Unlike conversation history, which is a record of the actual messages exchanged, working memory is a distilled summary of the important information the agent has learned about the user or task. This makes it more efficient and focused than trying to extract this information from the raw conversation history.
