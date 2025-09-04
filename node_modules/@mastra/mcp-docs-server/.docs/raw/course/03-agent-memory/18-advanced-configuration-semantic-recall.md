# Advanced Configuration of Semantic Recall

We can configure semantic recall in more detail by setting options for the `semanticRecall` option:

```typescript
const memory = new Memory({
  storage: new LibSQLStore({
    url: "file:../../memory.db", // relative path from the `.mastra/output` directory
  }),
  vector: new LibSQLVector({
    connectionUrl: "file:../../vector.db", // relative path from the `.mastra/output` directory
  }),
  embedder: openai.embedding("text-embedding-3-small"),
  options: {
    semanticRecall: {
      topK: 3,
      messageRange: {
        before: 2,
        after: 1,
      },
    },
  },
});
```

The `topK` parameter controls how many semantically similar messages are retrieved. A higher value will retrieve more messages, which can be helpful for complex topics but may also include less relevant information. The default value is `2`.

The `messageRange` parameter controls how much context is included with each match. This is important because the matching message alone might not provide enough context to understand the conversation. Including messages before and after the match helps the agent understand the context of the matched message.
