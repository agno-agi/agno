# zod-from-json-schema

[![CI](https://github.com/glideapps/zod-from-json-schema/actions/workflows/ci.yml/badge.svg)](https://github.com/glideapps/zod-from-json-schema/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://glideapps.github.io/zod-from-json-schema/badges/coverage.json)](https://github.com/glideapps/zod-from-json-schema/actions/workflows/ci.yml)
[![npm version](https://img.shields.io/npm/v/zod-from-json-schema.svg)](https://www.npmjs.com/package/zod-from-json-schema)

A library that creates [Zod](https://github.com/colinhacks/zod) types from [JSON Schema](https://json-schema.org/) at runtime.  This is in contrast to [json-schema-to-zod](https://www.npmjs.com/package/json-schema-to-zod), which generates JavaScript source code.

## Installation

```bash
npm install zod-from-json-schema
```

## Zod 3 vs 4

Zod 4 is available both as the package version 4, but also as part of the version 3 packages.  We support both, as well as Zod 3.  Here's which version of this package to use:

|Zod|zod-from-json-schema|
|---|--------------------|
| v4 proper  | latest    |
| v4 via 3.x | ^0.4.2    |
| v3 | ^0.0.5            |

Note that the older package for Zod 3 supports a smaller subset of JSON schema than the latest.  New features will only be added to the latest.

## Usage

This package supports both ESM and CommonJS formats.

### ESM (ES Modules)

```typescript
import { convertJsonSchemaToZod } from 'zod-from-json-schema';

// Define a JSON Schema with advanced features
const jsonSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  type: "object",
  properties: {
    name: { type: "string", minLength: 2, maxLength: 50 },
    age: { type: "integer", minimum: 0, maximum: 120 },
    email: { type: "string", pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$" },
    tags: {
      type: "array",
      items: { type: "string" },
      uniqueItems: true,
      minItems: 1,
      maxItems: 10,
      contains: { enum: ["user", "admin", "guest"] }
    },
    coordinates: {
      type: "array",
      prefixItems: [
        { type: "number", minimum: -90, maximum: 90 },   // latitude
        { type: "number", minimum: -180, maximum: 180 }  // longitude
      ],
      items: false  // No additional items allowed
    },
    score: { type: "number", multipleOf: 0.5, minimum: 0, maximum: 100 }
  },
  required: ["name", "email"],
  additionalProperties: false,
  minProperties: 2,
  maxProperties: 10
};

// Convert JSON Schema to Zod schema
const zodSchema = convertJsonSchemaToZod(jsonSchema);

// Use the Zod schema to validate data
try {
  const validData = zodSchema.parse({
    name: "John Doe",
    email: "john@example.com",
    age: 30,
    tags: ["user", "premium", "admin"],  // Contains required "admin" role
    coordinates: [37.7749, -122.4194],   // San Francisco lat/lng
    score: 87.5  // Multiple of 0.5
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
  $schema: "https://json-schema.org/draft/2020-12/schema",
  type: "object",
  properties: {
    name: { type: "string", minLength: 2, maxLength: 50 },
    age: { type: "integer", minimum: 0, maximum: 120 },
    hobbies: {
      type: "array",
      items: { type: "string" },
      minItems: 1,
      maxItems: 5
    }
  },
  required: ["name"],
  additionalProperties: false,
  minProperties: 1
};

// Convert JSON Schema to Zod schema
const zodSchema = convertJsonSchemaToZod(jsonSchema);

// Use the Zod schema to validate data
try {
  const validData = zodSchema.parse({
    name: "John Doe",
    age: 30,
    hobbies: ["reading", "coding", "gaming"]
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

This library provides comprehensive support for JSON Schema Draft 2020-12 features with **100% code coverage** and extensive test validation against the official JSON Schema Test Suite.

### Basic Types
- `string` - Basic string validation
- `number` - Numeric values (including integers)
- `integer` - Integer-only numeric values
- `boolean` - Boolean true/false values
- `null` - Null values
- `object` - Object validation with property definitions
- `array` - Array validation with item constraints

### String Validations
- `minLength` - Minimum string length (Unicode grapheme-aware)
- `maxLength` - Maximum string length (Unicode grapheme-aware)
- `pattern` - Regular expression pattern matching

**Unicode Support**: String length validation correctly counts Unicode grapheme clusters (user-perceived characters) rather than UTF-16 code units, ensuring proper validation of emoji and international text.

### Number Validations
- `minimum` - Minimum numeric value
- `maximum` - Maximum numeric value
- `exclusiveMinimum` - Exclusive minimum (greater than)
- `exclusiveMaximum` - Exclusive maximum (less than)
- `multipleOf` - Multiple validation with floating-point precision handling

### Array Validations
- `items` - Item schema validation (supports schemas, boolean values, and arrays)
- `prefixItems` - Tuple-style positional item validation (Draft 2020-12)
- `minItems` - Minimum array length
- `maxItems` - Maximum array length
- `uniqueItems` - Ensures all array items are unique
- `contains` - Validates that array contains items matching a schema
- `minContains` - Minimum number of items matching the contains schema
- `maxContains` - Maximum number of items matching the contains schema

**Advanced Array Features**:
- Boolean `items` schemas (`items: false` = empty arrays only, `items: true` = any items allowed)
- Complex tuple validation with `prefixItems` and additional items control
- Sophisticated contains validation with count constraints

### Object Validations
- `properties` - Property schema definitions
- `required` - Required property validation (supports special JavaScript property names)
- `additionalProperties` - Controls whether additional properties are allowed
- `minProperties` - Minimum number of object properties
- `maxProperties` - Maximum number of object properties

**Special Property Support**: Correctly handles JavaScript reserved property names like `constructor`, `toString`, and `__proto__`.

### Schema Composition
- `const` - Literal value constraints
- `enum` - Enumerated value validation
- `anyOf` - Union type validation (basic cases)
- `allOf` - Intersection validation (basic cases)
- `oneOf` - Exclusive union validation (exactly one schema must match)
- `not` - Negation validation

### Additional Features
- `title` - Schema titles (carried over to Zod schemas)
- `description` - Schema descriptions (carried over to Zod schemas)
- Boolean schemas (`true` = allow anything, `false` = allow nothing)
- Implicit type detection from constraints
- Comprehensive error messages

## Currently Unsupported Features

The following JSON Schema features are **not yet implemented**:

### References and Definitions
- `$ref` - JSON Pointer references (basic Zod v4 support exists but complex cases fail)
- `$defs` / `definitions` - Schema definitions for reuse
- Remote references (`$id` resolution)
- `$dynamicRef` / `$dynamicAnchor` - Dynamic references

### Advanced Object Validation
- `patternProperties` - Property validation based on regex patterns
- `additionalProperties` - Fine-grained control over additional properties (basic support exists)
- `dependentSchemas` - Schema dependencies based on property presence
- `dependentRequired` - Required properties based on other property presence
- `propertyNames` - Validation of property names themselves
- `unevaluatedProperties` - Properties not covered by schema evaluation

### Advanced Array Validation
- `unevaluatedItems` - Items not covered by schema evaluation
- Complex `prefixItems` scenarios with additional item control

### Conditional Schemas
- `if` / `then` / `else` - Conditional schema application

### Meta-Schema Features
- Custom vocabularies and meta-schema validation
- Annotation collection and processing

## Standards Compliance

- **JSON Schema Draft 2020-12** - Partial support for core features of the latest JSON Schema standard
- **Official Test Suite** - Passes the majority of tests from the official JSON Schema Test Suite ([246 tests currently skipped](./failing-tests-skip-list.json) for unsupported features)

## License

MIT
