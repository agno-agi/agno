# Installing Memory

First, we need to install the Mastra memory package to add memory capabilities to our agent. We also install a storage adapter to persist the memory data. We will use the `libsql` storage adapter. Run the following command in your terminal:

```bash
npm install @mastra/memory @mastra/libsql
```

The `@mastra/memory` package provides a simple yet powerful memory system for your Mastra agents. It allows your agent to remember previous conversations and maintain context across multiple interactions.

The `@mastra/libsql` package is one of many storage adapters that persists the memory data to an `SQLite` database.

These packages are separate from the core Mastra package to keep the framework modular and allow you to only include the features you need in your project.
