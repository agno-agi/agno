# @mastra/schema-compat

## 0.11.2-alpha.3

### Patch Changes

- [#7350](https://github.com/mastra-ai/mastra/pull/7350) [`45e4d39`](https://github.com/mastra-ai/mastra/commit/45e4d391a2a09fc70c48e4d60f505586ada1ba0e) Thanks [@LekoArts](https://github.com/LekoArts)! - Try fixing the `Attempted import error: 'z'.'toJSONSchema' is not exported from 'zod'` error by tricking the compiler

## 0.11.2-alpha.2

### Patch Changes

- [#7343](https://github.com/mastra-ai/mastra/pull/7343) [`de3cbc6`](https://github.com/mastra-ai/mastra/commit/de3cbc61079211431bd30487982ea3653517278e) Thanks [@LekoArts](https://github.com/LekoArts)! - Update the `package.json` file to include additional fields like `repository`, `homepage` or `files`.

## 0.11.2-alpha.1

### Patch Changes

- [#5816](https://github.com/mastra-ai/mastra/pull/5816) [`ab48c97`](https://github.com/mastra-ai/mastra/commit/ab48c979098ea571faf998a55d3a00e7acd7a715) Thanks [@dane-ai-mastra](https://github.com/apps/dane-ai-mastra)! - dependencies updates:
  - Updated dependency [`zod-to-json-schema@^3.24.6` ↗︎](https://www.npmjs.com/package/zod-to-json-schema/v/3.24.6) (from `^3.24.5`, in `dependencies`)

## 0.11.2-alpha.0

### Patch Changes

- [#7121](https://github.com/mastra-ai/mastra/pull/7121) [`637f323`](https://github.com/mastra-ai/mastra/commit/637f32371d79a8f78c52c0d53411af0915fcec67) Thanks [@DanielSLew](https://github.com/DanielSLew)! - Fix issue with some compilers and calling zod v4's toJSONSchema function

## 0.11.1

### Patch Changes

- [`c6113ed`](https://github.com/mastra-ai/mastra/commit/c6113ed7f9df297e130d94436ceee310273d6430) Thanks [@wardpeet](https://github.com/wardpeet)! - Fix peerdpes for @mastra/core

## 0.11.0

### Minor Changes

- [#7032](https://github.com/mastra-ai/mastra/pull/7032) [`1191ce9`](https://github.com/mastra-ai/mastra/commit/1191ce946b40ed291e7877a349f8388e3cff7e5c) Thanks [@wardpeet](https://github.com/wardpeet)! - Bump zod peerdep to 3.25.0 to support both v3/v4

### Patch Changes

- [#7028](https://github.com/mastra-ai/mastra/pull/7028) [`da58ccc`](https://github.com/mastra-ai/mastra/commit/da58ccc1f2ac33da0cb97b00443fc6208b45bdec) Thanks [@wardpeet](https://github.com/wardpeet)! - Fix exportsmap

- [#6982](https://github.com/mastra-ai/mastra/pull/6982) [`94e9f54`](https://github.com/mastra-ai/mastra/commit/94e9f547d66ef7cd01d9075ab53b5ca9a1cae100) Thanks [@wardpeet](https://github.com/wardpeet)! - Fix AI peerdeps for NPM install

- [#6944](https://github.com/mastra-ai/mastra/pull/6944) [`a93f3ba`](https://github.com/mastra-ai/mastra/commit/a93f3ba05eef4cf17f876d61d29cf0841a9e70b7) Thanks [@wardpeet](https://github.com/wardpeet)! - Add support for zod v4

## 0.11.0-alpha.2

### Minor Changes

- [#7032](https://github.com/mastra-ai/mastra/pull/7032) [`1191ce9`](https://github.com/mastra-ai/mastra/commit/1191ce946b40ed291e7877a349f8388e3cff7e5c) Thanks [@wardpeet](https://github.com/wardpeet)! - Bump zod peerdep to 3.25.0 to support both v3/v4

## 0.10.6-alpha.1

### Patch Changes

- [#7028](https://github.com/mastra-ai/mastra/pull/7028) [`da58ccc`](https://github.com/mastra-ai/mastra/commit/da58ccc1f2ac33da0cb97b00443fc6208b45bdec) Thanks [@wardpeet](https://github.com/wardpeet)! - Fix exportsmap

## 0.10.6-alpha.0

### Patch Changes

- [#6982](https://github.com/mastra-ai/mastra/pull/6982) [`94e9f54`](https://github.com/mastra-ai/mastra/commit/94e9f547d66ef7cd01d9075ab53b5ca9a1cae100) Thanks [@wardpeet](https://github.com/wardpeet)! - Fix AI peerdeps for NPM install

- [#6944](https://github.com/mastra-ai/mastra/pull/6944) [`a93f3ba`](https://github.com/mastra-ai/mastra/commit/a93f3ba05eef4cf17f876d61d29cf0841a9e70b7) Thanks [@wardpeet](https://github.com/wardpeet)! - Add support for zod v4

## 0.10.7

### Patch Changes

- dd94a26: Dont rely on the full language model for schema compat
- 2fff911: Fix vnext working memory tool schema when model is incompatible with schema
- ae2eb63: Handle regex checks better, return description as a string rather than an object with pattern and flags.

## 0.10.7-alpha.1

### Patch Changes

- ae2eb63: Handle regex checks better, return description as a string rather than an object with pattern and flags.

## 0.10.7-alpha.0

### Patch Changes

- dd94a26: Dont rely on the full language model for schema compat
- 2fff911: Fix vnext working memory tool schema when model is incompatible with schema

## 0.10.6

### Patch Changes

- 4a406ec: fixes TypeScript declaration file imports to ensure proper ESM compatibility

## 0.10.6-alpha.0

### Patch Changes

- 4a406ec: fixes TypeScript declaration file imports to ensure proper ESM compatibility

## 0.10.5

### Patch Changes

- 4da943f: Fix Cannot read properties of undefined (reading 'typeName') in schema compat check

## 0.10.5-alpha.0

### Patch Changes

- 4da943f: Fix Cannot read properties of undefined (reading 'typeName') in schema compat check

## 0.10.4

### Patch Changes

- 0c85311: Fix Google models ZodNull tool schema handling

## 0.10.4-alpha.0

### Patch Changes

- 0c85311: Fix Google models ZodNull tool schema handling

## 0.10.3

### Patch Changes

- 98bbe5a: Claude cannot handle tuple schemas now.
- a853c43: Allow for object.passthrough in schema compat (aka MCP tool support).

## 0.10.3-alpha.1

### Patch Changes

- a853c43: Allow for object.passthrough in schema compat (aka MCP tool support).

## 0.10.3-alpha.0

### Patch Changes

- 98bbe5a: Claude cannot handle tuple schemas now.

## 0.10.2

### Patch Changes

- f6fd25f: Updates @mastra/schema-compat to allow all zod schemas. Uses @mastra/schema-compat to apply schema transformations to agent output schema.
- f9816ae: Create @mastra/schema-compat package to extract the schema compatibility layer to be used outside of mastra

## 0.10.2-alpha.3

### Patch Changes

- f6fd25f: Updates @mastra/schema-compat to allow all zod schemas. Uses @mastra/schema-compat to apply schema transformations to agent output schema.

## 0.10.2-alpha.2

### Patch Changes

- f9816ae: Create @mastra/schema-compat package to extract the schema compatibility layer to be used outside of mastra
