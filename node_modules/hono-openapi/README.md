# 📜 Hono OpenAPI

[![npm version](https://img.shields.io/npm/v/hono-openapi.svg)](https://npmjs.org/package/hono-openapi "View this project on NPM")
[![npm downloads](https://img.shields.io/npm/dm/hono-openapi)](https://www.npmjs.com/package/hono-openapi)
[![license](https://img.shields.io/npm/l/hono-openapi)](LICENSE)

This can automatically generate the OpenAPI specification for the Hono API using your validation schema, which can be used to generate client libraries, documentation, and more.

Supported Validation Libraries:

- [x] [Zod](https://zod.dev/)
- [x] [Valibot](https://valibot.dev/)
- [x] [ArkType](https://arktype.io/)
- [x] [TypeBox](https://github.com/sinclairzx81/typebox)
- [x] [Effect](https://effect.website/docs/schema/introduction/)

> [!Note]
> This package is still in development and your feedback is highly appreciated. If you have any suggestions or issues, please let us know by creating an issue on GitHub.

## Usage

### Installation

You can install the package using favorite package manager.

#### For Zod

```bash
pnpm add hono-openapi @hono/zod-validator zod zod-openapi
```

#### For Valibot

```bash
pnpm add hono-openapi @hono/valibot-validator valibot @valibot/to-json-schema
```

#### For ArkType

```bash
pnpm add hono-openapi @hono/arktype-validator arktype
```

#### For TypeBox

```bash
pnpm add hono-openapi @hono/typebox-validator @sinclair/typebox
```

#### For Effect

```bash
pnpm add hono-openapi @hono/effect-validator effect
```

> [!IMPORTANT]
>
> Requires `effect@^3.10.0`.
> Also, use the `Schema` class from the `effect` package, as `@effect/schema` is not supported.

### Basic Usage

#### Setting up your application

First, define your schemas, here is an example using Zod:

```ts
import z from "zod";

// For extending the Zod schema with OpenAPI properties
import "zod-openapi/extend";

const querySchema = z
  .object({
    name: z.string().optional().openapi({ example: "Steven" }),
  })
  .openapi({ ref: "Query" });

const responseSchema = z.string().openapi({ example: "Hello Steven!" });
```

Extending the Zod schema with OpenAPI properties is optional, but it will help you generate the OpenAPI specification. You can learn more about it here - [https://github.com/samchungy/zod-openapi](https://github.com/samchungy/zod-openapi).

> [!Tip]
> The `querySchema` schema will be registered as "#/components/schemas/Query" refs in the OpenAPI document. If you want to register the schema as referenced components, use .openapi() method.

Next, create your route -

```ts
import { Hono } from "hono";
import { describeRoute } from "hono-openapi";
import { resolver, validator as zValidator } from "hono-openapi/zod";

const app = new Hono();

app.get(
  "/",
  describeRoute({
    description: "Say hello to the user",
    responses: {
      200: {
        description: "Successful greeting response",
        content: {
          "text/plain": {
            schema: resolver(responseSchema),
          },
        },
      },
    },
  }),
  zValidator("query", querySchema),
  (c) => {
    const query = c.req.valid("query");
    return c.text(`Hello ${query?.name ?? "Hono"}!`);
  }
);
```

You might be wondering why are we importing `validator` from `hono-openapi/zod` instead of `@hono/zod-validator` and as `zValidator`? This is because `hono-openapi` provides a wrapper around the `@hono/zod-validator` to make it easier to use. The idea is if you are already using `@hono/zod-validator` to validate your schemas, you can easily switch to `hono-openapi` without changing much of your code.

Finally, generate the OpenAPI specification -

```ts
app.get(
  "/openapi",
  openAPISpecs(app, {
    documentation: {
      info: {
        title: "Hono",
        version: "1.0.0",
        description: "API for greeting users",
      },
      servers: [
        {
          url: "http://localhost:3000",
          description: "Local server",
        },
      ],
    },
  })
);
```

Now, you can access the OpenAPI specification by visiting `http://localhost:3000/openapi`, and you can use this specification to generate client libraries, documentation, and more. Some tools that I used to generate documentation are -

- [Swagger UI](https://github.com/honojs/middleware/tree/main/packages/swagger-ui)
- [Scalar](https://www.npmjs.com/package/@scalar/hono-api-reference)

##### Scalar Example

```ts
app.get(
  "/docs",
  Scalar({
    theme: "saturn",
    url: "/openapi",
  })
);
```

And that's it! You have successfully generated the OpenAPI specification for your Hono API.

### Advanced Usage

#### Adding Security Definitions

You can add security definitions to your OpenAPI specification by using the `security` property in the `openAPISpecs` function.

```ts
app.get(
  "/openapi",
  openAPISpecs(appRouter, {
    documentation: {
      info: {
        title: "Rhinobase Cloud",
        version: "1.0.0",
        description: "API Documentation",
      },
      components: {
        securitySchemes: {
          bearerAuth: {
            type: "http",
            scheme: "bearer",
            bearerFormat: "JWT",
          },
        },
      },
      security: [
        {
          bearerAuth: [],
        },
      ],
      servers: [
        {
          url: "http://localhost:3004",
          description: "Local server",
        },
      ],
    },
  })
);
```

#### Conditionaly Hiding Routes

You can conditionally hide routes from the OpenAPI specification by using the `hide` property in the `describeRoute` function.

```ts
app.get(
  "/",
  describeRoute({
    // ...
    hide: process.env.NODE_ENV === "production",
  }),
  (c) => {
    return c.text("Private Route");
  }
);
```

#### Validating Responses

> [!Warning]
> Experimental

You can validate the responses using the `validateResponse` property in the `describeRoute` function. This will validate the response against the schema and return an error if the response is invalid.

```ts
app.get(
  "/",
  describeRoute({
    // ...
    validateResponse: true,
  }),
  (c) => {
    return c.json({ message: "This response will be validated" });
  }
);
```

#### Persisting OpenAPI Spec to a file

You can save the spec to a file for cache or any other external use.

```ts
import fs from 'node:fs';
import { openAPISpecs, generateSpecs } from 'hono-openapi';

const options = {/* ... */};
const app = new Hono()
  .get(
    "/openapi",
    openAPISpecs(app, options),
  );

generateSpecs(app, options)
  .then(spec => {
    const pathToSpec = "openapi.json"
    fs.writeFileSync(pathToSpec, JSON.stringify(spec, null, 2));
  })
```

## Contributing

We would love to have more contributors involved!

To get started, please read our [Contributing Guide](https://github.com/rhinobase/hono-openapi/blob/main/CONTRIBUTING.md).

## Credits

- The idea for this project was inspired by [ElysiaJS](https://elysiajs.com/) and their amazing work on generating [OpenAPI](https://elysiajs.com/recipe/openapi.html) specifications.
- This project would not have been possible without the work of [Sam Chung](https://github.com/samchungy) and his [Zod OpenAPI](https://github.com/samchungy/zod-openapi) package.
