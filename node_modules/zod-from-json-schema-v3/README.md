# zod-from-json-schema

[![CI](https://github.com/glideapps/zod-from-json-schema/actions/workflows/ci.yml/badge.svg)](https://github.com/glideapps/zod-from-json-schema/actions/workflows/ci.yml)
[![npm version](https://img.shields.io/npm/v/zod-from-json-schema.svg)](https://www.npmjs.com/package/zod-from-json-schema)

A library that creates [Zod](https://github.com/colinhacks/zod) types from [JSON Schema](https://json-schema.org/) at runtime.  This is in contrast to [json-schema-to-zod](https://www.npmjs.com/package/json-schema-to-zod), which generates JavaScript source code.

## Installation

```bash
npm install zod-from-json-schema
```

## Usage

This package supports both ESM and CommonJS formats.

### ESM (ES Modules)

```typescript
import { convertJsonSchemaToZod } from 'zod-from-json-schema';

// Define a JSON Schema
const jsonSchema = {
  $schema: "http://json-schema.org/draft-07/schema#",
  type: "object",
  properties: {
    name: { type: "string", minLength: 2, maxLength: 50 },
    age: { type: "integer", minimum: 0, maximum: 120 },
    email: { type: "string", pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$" },
    tags: {
      type: "array",
      items: { type: "string" },
      uniqueItems: true,
      minItems: 1
    }
  },
  required: ["name", "email"],
  additionalProperties: false
};

// Convert JSON Schema to Zod schema
const zodSchema = convertJsonSchemaToZod(jsonSchema);

// Use the Zod schema to validate data
try {
  const validData = zodSchema.parse({
    name: "John Doe",
    email: "john@example.com",
    age: 30,
    tags: ["user", "premium"]
  });
  console.log("Valid data:", validData);
} catch (error) {
  console.error("Validation error:", error);
}
```

### CommonJS

```javascript
const { convertJsonSchemaToZod } = require('zod-from-json-schema');

// Define a JSON Schema
const jsonSchema = {
  $schema: "http://json-schema.org/draft-07/schema#",
  type: "object",
  properties: {
    name: { type: "string", minLength: 2, maxLength: 50 },
    age: { type: "integer", minimum: 0, maximum: 120 }
  },
  required: ["name"],
  additionalProperties: false
};

// Convert JSON Schema to Zod schema
const zodSchema = convertJsonSchemaToZod(jsonSchema);

// Use the Zod schema to validate data
try {
  const validData = zodSchema.parse({
    name: "John Doe",
    age: 30
  });
  console.log("Valid data:", validData);
} catch (error) {
  console.error("Validation error:", error);
}
```

## API Reference

### `convertJsonSchemaToZod(schema)`

Converts a JSON Schema object to a complete Zod schema.

- **Parameters**:
  - `schema` (Object): A JSON Schema object
- **Returns**: 
  - A Zod schema that validates according to the JSON Schema

### `jsonSchemaObjectToZodRawShape(schema)`

Extracts the object properties from a JSON Schema object into a Zod raw shape. This is useful when you want to combine the properties with other Zod object configurations.

- **Parameters**:
  - `schema` (Object): A JSON Schema object that should have a `properties` field
- **Returns**: 
  - A `ZodRawShape` object that can be used with `z.object()`

**Example**:

```typescript
import { jsonSchemaObjectToZodRawShape } from 'zod-from-json-schema';
import { z } from 'zod';

const jsonSchema = {
  properties: {
    name: { type: "string" },
    age: { type: "integer" }
  },
  required: ["name"]
};

// Get just the property definitions
const rawShape = jsonSchemaObjectToZodRawShape(jsonSchema);

// Add custom handling
const customSchema = z.object({
  ...rawShape,
  // Add additional fields not in the JSON Schema
  createdAt: z.date().default(() => new Date())
}).refine(data => data.age > 18, {
  message: "Age must be over 18 to continue"
});
```

## Supported JSON Schema Features

This library supports the following JSON Schema features:

### Basic Types
- `string`
- `number`
- `integer`
- `boolean`
- `null`
- `object` (with properties and required fields)
- `array`

### String Validations
- `minLength`
- `maxLength`
- `pattern` (regular expressions)

### Number Validations
- `minimum`
- `maximum`
- `exclusiveMinimum`
- `exclusiveMaximum`
- `multipleOf`

### Array Validations
- `minItems`
- `maxItems`
- `uniqueItems`

### Object Validations
- `required` (required properties)
- `additionalProperties` (controls passthrough behavior)

### Schema Composition
- `const` (literal values)
- `enum` (enumerated values)
- `anyOf` (union)
- `allOf` (intersection)
- `oneOf` (union)

### Additional
- `description` (carried over to Zod schemas)

## License

MIT
