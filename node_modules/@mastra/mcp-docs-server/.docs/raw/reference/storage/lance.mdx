---
title: "LanceDB Storage"
description: Documentation for the LanceDB storage implementation in Mastra.
---

# LanceDB Storage

The LanceDB storage implementation provides a high-performance storage solution using the LanceDB database system, which excels at handling both traditional data storage and vector operations.

## Installation

```bash
npm install @mastra/lance
```

## Usage

### Basic Storage Usage

```typescript copy showLineNumbers
import { LanceStorage } from "@mastra/lance";

// Connect to a local database
const storage = await LanceStorage.create("my-storage", "/path/to/db");

// Connect to a LanceDB cloud database
const storage = await LanceStorage.create("my-storage", "db://host:port");

// Connect to a cloud database with custom options
const storage = await LanceStorage.create("my-storage", "s3://bucket/db", {
  storageOptions: { timeout: "60s" },
});
```

## Parameters

### LanceStorage.create()

<PropertiesTable
  content={[
    {
      name: "name",
      type: "string",
      description: "Name identifier for the storage instance",
      isOptional: false,
    },
    {
      name: "uri",
      type: "string",
      description:
        "URI to connect to the LanceDB database. Can be a local path, cloud DB URL, or S3 bucket URL",
      isOptional: false,
    },
    {
      name: "options",
      type: "ConnectionOptions",
      description:
        "Connection options for LanceDB, such as timeout settings, authentication, etc.",
      isOptional: true,
    },
  ]}
/>

## Additional Notes

### Schema Management

The LanceStorage implementation automatically handles schema creation and updates. It maps Mastra's schema types to Apache Arrow data types, which are used by LanceDB internally:

- `text`, `uuid` → Utf8
- `int`, `integer` → Int32
- `float` → Float32
- `jsonb`, `json` → Utf8 (serialized)
- `binary` → Binary

### Deployment Options

LanceDB storage can be configured for different deployment scenarios:

- **Local Development**: Use a local file path for development and testing
  ```
  /path/to/db
  ```
- **Cloud Deployment**: Connect to a hosted LanceDB instance
  ```
  db://host:port
  ```
- **S3 Storage**: Use Amazon S3 for scalable cloud storage
  ```
  s3://bucket/db
  ```

### Table Management

LanceStorage provides methods for managing tables:

- Create tables with custom schemas
- Drop tables
- Clear tables (delete all records)
- Load records by key
- Insert single and batch records
