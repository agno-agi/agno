<h1 align="center">
  <img alt="Standard Schema fire logo" loading="lazy" width="50" height="50" decoding="async" data-nimg="1" style="color:transparent" src="https://standardschema.dev/favicon.svg">
  </br>
  Standard Schema</h1>
<p align="center">
  A common interface for TypeScript validation libraries
  <br/>
  <a href="https://standardschema.dev">standardschema.dev</a>
</p>
<br/>

<!-- start -->

Standard Schema is a common interface designed to be implemented by JavaScript and TypeScript schema libraries.

The goal is to make it easier for ecosystem tools to accept user-defined type validators, without needing to write custom logic or adapters for each supported library. And since Standard Schema is a specification, they can do so with no additional runtime dependencies. Integrate once, validate anywhere.

## Who designed it?

The spec was designed by the creators of Zod, Valibot, and ArkType. Recent versions of these libraries already implement the spec (see the [full list of compatible libraries](#what-schema-libraries-implement-the-spec) below).

## The interface

The specification consists of a single TypeScript interface `StandardSchemaV1` to be implemented by any schema library wishing to be spec-compliant.

This interface can be found below in its entirety. Libraries wishing to implement the spec can copy/paste the code block below into their codebase. It's also available at `@standard-schema/spec` on [npm](https://www.npmjs.com/package/@standard-schema/spec) and [JSR](https://jsr.io/@standard-schema/spec). There will be zero changes without a major version bump.

```ts
/** The Standard Schema interface. */
export interface StandardSchemaV1<Input = unknown, Output = Input> {
  /** The Standard Schema properties. */
  readonly '~standard': StandardSchemaV1.Props<Input, Output>;
}

export declare namespace StandardSchemaV1 {
  /** The Standard Schema properties interface. */
  export interface Props<Input = unknown, Output = Input> {
    /** The version number of the standard. */
    readonly version: 1;
    /** The vendor name of the schema library. */
    readonly vendor: string;
    /** Validates unknown input values. */
    readonly validate: (
      value: unknown
    ) => Result<Output> | Promise<Result<Output>>;
    /** Inferred types associated with the schema. */
    readonly types?: Types<Input, Output> | undefined;
  }

  /** The result interface of the validate function. */
  export type Result<Output> = SuccessResult<Output> | FailureResult;

  /** The result interface if validation succeeds. */
  export interface SuccessResult<Output> {
    /** The typed output value. */
    readonly value: Output;
    /** The non-existent issues. */
    readonly issues?: undefined;
  }

  /** The result interface if validation fails. */
  export interface FailureResult {
    /** The issues of failed validation. */
    readonly issues: ReadonlyArray<Issue>;
  }

  /** The issue interface of the failure output. */
  export interface Issue {
    /** The error message of the issue. */
    readonly message: string;
    /** The path of the issue, if any. */
    readonly path?: ReadonlyArray<PropertyKey | PathSegment> | undefined;
  }

  /** The path segment interface of the issue. */
  export interface PathSegment {
    /** The key representing a path segment. */
    readonly key: PropertyKey;
  }

  /** The Standard Schema types interface. */
  export interface Types<Input = unknown, Output = Input> {
    /** The input type of the schema. */
    readonly input: Input;
    /** The output type of the schema. */
    readonly output: Output;
  }

  /** Infers the input type of a Standard Schema. */
  export type InferInput<Schema extends StandardSchemaV1> = NonNullable<
    Schema['~standard']['types']
  >['input'];

  /** Infers the output type of a Standard Schema. */
  export type InferOutput<Schema extends StandardSchemaV1> = NonNullable<
    Schema['~standard']['types']
  >['output'];
}
```

## Design goals

The specification meets a few primary design objectives:

- **Support runtime validation.** Given a Standard Schema compatible validator, you should be able to validate data with it (duh). Any validation errors should be presented in a standardized format.
- **Support static type inference.** For TypeScript libraries that do type inference, the specification provides a standard way for them to "advertise" their inferred type, so it can be extracted and used by external tools.
- **Minimal.** It should be easy for libraries to implement this spec in a few lines of code that call their existing functions/methods.
- **Avoid API conflicts.** The entire spec is tucked inside a single object property called `~standard`, which avoids potential naming conflicts with the API surface of existing libraries.
- **Do no harm to DX.** The `~standard` property is tilde-prefixed to [de-prioritize it in autocompletion](https://x.com/colinhacks/status/1816860780459073933). By contrast, an underscore-prefixed property would show up before properties/methods with alphanumeric names.

## What schema libraries implement the spec?

These are the libraries that have already implemented the Standard Schema interface. (If you maintain a library that implements the spec, [create a PR](https://github.com/standard-schema/standard-schema/compare) to add yourself!)

| Implementer | Version(s) | Docs                                                                       |
| ----------- | ---------- | -------------------------------------------------------------------------- |
| Zod         | 3.24.0+    | [zod.dev](https://zod.dev/)                                                |
| Valibot     | v1.0+      | [valibot.dev](https://valibot.dev/)                                        |
| ArkType     | v2.0+      | [arktype.io](https://arktype.io/)                                          |
| Arri Schema | v0.71.0+   | [github.com/modiimedia/arri](https://github.com/modiimedia/arri)           |
| TypeMap     | v0.8.0+    | [github.com/sinclairzx81/typemap](https://github.com/sinclairzx81/typemap) |

## What tools / frameworks accept spec-compliant schemas?

The following tools accept user-defined schemas conforming to the Standard Schema spec. (If you maintain a tool that supports Standard Schemas, [create a PR](https://github.com/standard-schema/standard-schema/compare) to add yourself!)

| Integrator                                              | Description                                                                                                                  | Link                                                                   |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| [tRPC](https://trpc.io)                                 | 🧙‍♀️ Move fast and break nothing. End-to-end typesafe APIs made easy                                                           | [PR](https://github.com/trpc/trpc/pull/6079)                           |
| [TanStack Form](https://github.com/TanStack/form)       | 🤖 Headless, performant, and type-safe form state management for TS/JS, React, Vue, Angular, Solid, and Lit                  | [PR](https://github.com/TanStack/form/issues/1015)                     |
| [TanStack Router](https://github.com/tanstack/router)   | A fully type-safe React router with built-in data fetching, stale-while revalidate caching and first-class search-param APIs | [PR](https://github.com/TanStack/router/pull/2602)                     |
| [Hono Middleware 🚧](https://hono.dev)                  | Fast, lightweight server, built on Web Standards                                                                             | [PR](https://github.com/honojs/middleware/pull/887)                    |
| [Qwik 🚧](https://github.com/QwikDev/qwik)              | Instant-loading web apps, without effort                                                                                     | [PR](https://github.com/QwikDev/qwik/pull/7281)                        |
| [UploadThing](https://github.com/pingdotgg/uploadthing) | File uploads for modern web devs                                                                                             | [Docs](https://docs.uploadthing.com/file-routes#input)                 |
| [T3 Env](https://github.com/t3-oss/t3-env)              | Framework agnostic validation for type-safe environment variables                                                            | [PR](https://github.com/t3-oss/t3-env/pull/299)                        |
| [OpenAuth](https://github.com/openauthjs/openauth)      | Universal, standards-based auth provider                                                                                     | [Docs](https://openauth.js.org/docs/#server)                           |
| [renoun](https://www.renoun.dev/)                       | The Documentation Toolkit for React                                                                                          | [Docs](https://www.renoun.dev/utilities/file-system#schema-validation) |
| [Formwerk](https://github.com/formwerkjs/formwerk)      | A Vue.js Framework for building high-quality, accessible, delightful forms.                                                  | [PR](https://github.com/formwerkjs/formwerk/pull/68)                   |
| [GQLoom](https://github.com/modevol-com/gqloom)         | Weave GraphQL schema and resolvers using Standard Schema                                                                     | [PR](https://github.com/modevol-com/gqloom/pull/7)                     |
| [Nuxt UI (v3)](https://github.com/nuxt/ui)              | A UI Library for modern web apps, powered by Vue & Tailwind CSS                                                              | [PR](https://github.com/nuxt/ui/pull/2303)                             |
| [oRPC](https://github.com/unnoq/orpc)                   | Typesafe APIs made simple 🪄                                                                                                 | [PR](https://github.com/unnoq/orpc/pull/50)                            |
| [Regle](https://github.com/victorgarciaesgi/regle)      | Type-safe model-based form validation library for Vue.js                                                                     | [PR](https://github.com/victorgarciaesgi/regle/pull/46)                |

## How can my schema library implement the spec?

Schemas libraries that want to support Standard Schema must implement the `StandardSchemaV1` interface. Start by copying the specification file above into your library. It consists of types only.

Then implement the spec by adding the `~standard` property to your validator objects/instances. We recommend using `extends` / `implements` to ensure static agreement with the interface. It doesn't matter whether your schema library returns plain objects, functions, or class instances. The only thing that matters is that the `~standard` property is defined somehow.

Here's a simple worked example of a string validator that implements the spec.

```ts
import type {StandardSchemaV1} from '@standard-schema/spec';

// Step 1: Define the schema interface
interface StringSchema extends StandardSchemaV1<string> {
  type: 'string';
  message: string;
}

// Step 2: Implement the schema interface
function string(message: string = 'Invalid type'): StringSchema {
  return {
    type: 'string',
    message,
    '~standard': {
      version: 1,
      vendor: 'valizod',
      validate(value) {
        return typeof value === 'string' ? {value} : {issues: [{message}]};
      },
    },
  };
}
```

We recommend defining the `~standard.validate()` function in terms of your library's existing validation functions/methods. Ideally implementing the spec only requires a handful of lines of code.

Avoid returning `Promise` from `~standard.validate()` unless absolutely necessary. Some third-party libraries may not support async validation.

## How do I accept Standard Schemas in my library?

Third-party libraries and frameworks can leverage the Standard Schema spec to accept user-defined schemas in a type-safe way.

To get started, copy and paste the specification file into your project. Alternatively (if you are okay with the extra dependency), you can install the `@standard-schema/spec` package from [npm](https://www.npmjs.com/package/@standard-schema/spec) or [JSR](https://jsr.io/@standard-schema/spec) as a dependency. _It is not recommended to install as a dev dependency, see the [associated FAQ](#can-i-add-it-as-a-dev-dependency) for details_.

```sh
npm install @standard-schema/spec       # npm
yarn add @standard-schema/spec          # yarn
pnpm add @standard-schema/spec          # pnpm
bun add @standard-schema/spec           # bun
deno add jsr:@standard-schema/spec      # deno
```

Here's is an simple example of a generic function that accepts an arbitrary spec-compliant validator and uses it to parse some data.

```ts
import type {StandardSchemaV1} from '@standard-schema/spec';

export async function standardValidate<T extends StandardSchemaV1>(
  schema: T,
  input: StandardSchemaV1.InferInput<T>
): Promise<StandardSchemaV1.InferOutput<T>> {
  let result = schema['~standard'].validate(input);
  if (result instanceof Promise) result = await result;

  // if the `issues` field exists, the validation failed
  if (result.issues) {
    throw new Error(JSON.stringify(result.issues, null, 2));
  }

  return result.value;
}
```

This concise function can accept inputs from any spec-compliant schema library.

```ts
import * as z from 'zod';
import * as v from 'valibot';
import {type} from 'arktype';

const zodResult = await standardValidate(z.string(), 'hello');
const valibotResult = await standardValidate(v.string(), 'hello');
const arktypeResult = await standardValidate(type('string'), 'hello');
```

## FAQ

These are the most frequently asked questions about Standard Schema. If your question is not listed, feel free to create an issue.

### Do I need to add `@standard-schema/spec` as a dependency?

No. The `@standard-schema/spec` package is completely optional. You can just copy and paste the types into your project. We guarantee no breaking changes without a major version bump.

If you don't mind additional dependencies, you can add `@standard-schema/spec` as a dependency and consume it with `import type`. The `@standard-schema/spec` package contains no runtime code and only exports types.

### Can I add it as a dev dependency?

Despite being types-only, you should _not_ install `@standard-schema/spec` as a dev dependency. By accepting Standard Schemas as part of your public API, the Standard Schema interface becomes a part of your library's public API. As such, it _must_ be available whenever/wherever your library gets installed, even in production installs. For this to happen, it must be installed as a regular dependency.

### Why did you prefix the `~standard` property with `~`?

The goal of prefixing the key with `~` is to both avoid conflicts with existing API surfaces and to de-prioritize these keys in auto-complete. The `~` character is one of the few ASCII characters that occurs after `A-Za-z0-9` lexicographically, so VS Code puts these suggestions at the bottom of the list.

![Screenshot showing the de-prioritization of the `~` prefix keys in VS Code.](https://github.com/standard-schema/standard-schema/assets/3084745/5dfc0219-7531-481e-9691-cff5bc471378)

### Why not use a symbol key?

In TypeScript, using a plain `Symbol` inline as a key always collapses to a simple `symbol` type. This would cause conflicts with other schema properties that use symbols.

```ts
const object = {
  [Symbol.for('~output')]: 'some data',
};
// { [k: symbol]: string }
```

Unique symbols can also be declared in a "nominal" way that won't collapse. In this case the symbol key is sorted alphabetically in autocomplete according to the symbol's variable name.

![Screenshot showing the prioritization of external symbols in VS Code](https://github.com/standard-schema/standard-schema/assets/3084745/82c47820-90c3-4163-a838-858b987a6bea)

Thus, these symbol keys don't get sorted to the bottom of the autocomplete list, unlike tilde-prefixed string keys.

### How to only allow synchronous validation?

The `~validate` function might return a synchronous value _or_ a `Promise`. If you only accept synchronous validation, you can simply throw an error if the returned value is an instance of `Promise`. Libraries are encouraged to preferentially use synchronous validation whenever possible.

```ts
import type {StandardSchemaV1} from '@standard-schema/spec';

function validateInput(schema: StandardSchemaV1, data: unknown) {
  const result = schema['~standard'].validate(data);
  if (result instanceof Promise) {
    throw new TypeError('Schema validation must be synchronous');
  }
  // ...
}
```
