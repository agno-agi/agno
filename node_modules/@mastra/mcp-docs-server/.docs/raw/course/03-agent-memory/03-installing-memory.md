# Installing Memory

Let's start by installing the Mastra memory package:

```bash
npm install @mastra/memory @mastra/libsql
```

The `@mastra/memory` package provides all the functionality you need to add memory capabilities to your Mastra agents. It includes support for conversation history, semantic recall, and working memory.

The `@mastra/libsql` package is **one of many** storage adapters that complement the memory package. The purpose of a storage adapter is to provide a way to persist the memory data to a database or other storage system. The `@mastra/libsql` package provides a storage adapter for LibSQL, which is a fast, open-source fork of SQLite.

These packages are separate from the core Mastra package, allowing you to only include them when you need memory capabilities in your project. This modular approach helps keep your project dependencies lean when you don't need all features.
