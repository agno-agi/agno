---
title: Mastra Client Vectors API
description: Learn how to work with vector embeddings for semantic search and similarity matching in Mastra using the client-js SDK.
---

# Vectors API

The Vectors API provides methods to work with vector embeddings for semantic search and similarity matching in Mastra.

## Working with Vectors

Get an instance of a vector store:

```typescript
const vector = mastraClient.getVector("vector-name");
```

## Vector Methods

### Get Vector Index Details

Retrieve information about a specific vector index:

```typescript
const details = await vector.details("index-name");
```

### Create Vector Index

Create a new vector index:

```typescript
const result = await vector.createIndex({
  indexName: "new-index",
  dimension: 128,
  metric: "cosine", // 'cosine', 'euclidean', or 'dotproduct'
});
```

### Upsert Vectors

Add or update vectors in an index:

```typescript
const ids = await vector.upsert({
  indexName: "my-index",
  vectors: [
    [0.1, 0.2, 0.3], // First vector
    [0.4, 0.5, 0.6], // Second vector
  ],
  metadata: [{ label: "first" }, { label: "second" }],
  ids: ["id1", "id2"], // Optional: Custom IDs
});
```

### Query Vectors

Search for similar vectors:

```typescript
const results = await vector.query({
  indexName: "my-index",
  queryVector: [0.1, 0.2, 0.3],
  topK: 10,
  filter: { label: "first" }, // Optional: Metadata filter
  includeVector: true, // Optional: Include vectors in results
});
```

### Get All Indexes

List all available indexes:

```typescript
const indexes = await vector.getIndexes();
```

### Delete Index

Delete a vector index:

```typescript
const result = await vector.delete("index-name");
```
