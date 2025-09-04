# @ai-sdk/provider-utils

## 3.0.3

### Patch Changes

- 034e229: fix(provider/utils): fix FlexibleSchema type inference with zod/v3
- f25040d: fix(provider-utils): fix tools type inference

## 3.0.2

### Patch Changes

- 38ac190: feat(ai): preliminary tool results

## 3.0.1

### Patch Changes

- 90d212f: feat (ai): add experimental tool call context

## 3.0.0

### Major Changes

- 5d142ab: remove deprecated `CoreToolCall` and `CoreToolResult` types
- d5f588f: AI SDK 5
- e025824: refactoring (ai): restructure provider-defined tools
- 40acf9b: feat (ui): introduce ChatStore and ChatTransport
- 957b739: chore (provider-utils): rename TestServerCall.requestBody to requestBodyJson
- ea7a7c9: feat (ui): UI message metadata
- 41fa418: chore (provider-utils): return IdGenerator interface
- 71f938d: feat (ai): add output schema for tools

### Patch Changes

- a571d6e: chore(provider-utils): move ToolResultContent to provider-utils
- e7fcc86: feat (ai): introduce dynamic tools
- 45c1ea2: refactoring: introduce FlexibleSchema
- 060370c: feat(provider-utils): add TestServerCall#requestCredentials
- 0571b98: chore (provider-utils): update eventsource-parser to 3.0.3
- 4fef487: feat: support for zod v4 for schema validation

  All these methods now accept both a zod v4 and zod v3 schemas for validation:

  - `generateObject()`
  - `streamObject()`
  - `generateText()`
  - `experimental_useObject()` from `@ai-sdk/react`
  - `streamUI()` from `@ai-sdk/rsc`

- 0c0c0b3: refactor (provider-utils): move `customAlphabet()` method from `nanoid` into codebase
- 8ba77a7: chore (provider-utils): use eventsource-parser library
- a166433: feat: add transcription with experimental_transcribe
- 9f95b35: refactor (provider-utils): copy relevant code from `secure-json-parse` into codebase
- 66962ed: fix(packages): export node10 compatible types
- 05d2819: feat: allow zod 4.x as peer dependency
- ac34802: Add clear object function to StructuredObject
- 63d791d: chore (utils): remove unused test helpers
- 87b828f: fix(provider-utils): fix SSE parser bug (CRLF)
- bfdca8d: feat (ai): add InferToolInput and InferToolOutput helpers
- 0ff02bb: chore(provider-utils): move over jsonSchema
- 39a4fab: fix (provider-utils): detect failed fetch in browser environments
- 57edfcb: Adds support for async zod validators
- faf8446: chore (provider-utils): switch to standard-schema
- d1a034f: feature: using Zod 4 for internal stuff
- 88a8ee5: fix (ai): support abort during retry waits
- 205077b: fix: improve Zod compatibility
- 28a5ed5: refactoring: move tools helper into provider-utils
- dd5fd43: feat (ai): support dynamic tools in Chat onToolCall
- 383cbfa: feat (ai): add isAborted to onFinish callback for ui message streams
- Updated dependencies [742b7be]
- Updated dependencies [7cddb72]
- Updated dependencies [ccce59b]
- Updated dependencies [e2b9e4b]
- Updated dependencies [95857aa]
- Updated dependencies [6f6bb89]
- Updated dependencies [dc714f3]
- Updated dependencies [b5da06a]
- Updated dependencies [d1a1aa1]
- Updated dependencies [63f9e9b]
- Updated dependencies [d5f588f]
- Updated dependencies [b6b43c7]
- Updated dependencies [48d257a]
- Updated dependencies [0d2c085]
- Updated dependencies [9222aeb]
- Updated dependencies [e2aceaf]
- Updated dependencies [411e483]
- Updated dependencies [7b3ae3f]
- Updated dependencies [a166433]
- Updated dependencies [26735b5]
- Updated dependencies [443d8ec]
- Updated dependencies [a8c8bd5]
- Updated dependencies [abf9a79]
- Updated dependencies [14c9410]
- Updated dependencies [e86be6f]
- Updated dependencies [9bf7291]
- Updated dependencies [2e13791]
- Updated dependencies [0d06df6]
- Updated dependencies [472524a]
- Updated dependencies [dd3ff01]
- Updated dependencies [d9c98f4]
- Updated dependencies [9301f86]
- Updated dependencies [0a87932]
- Updated dependencies [c4a2fec]
- Updated dependencies [79457bd]
- Updated dependencies [a3f768e]
- Updated dependencies [7435eb5]
- Updated dependencies [8aa9e20]
- Updated dependencies [4617fab]
- Updated dependencies [0054544]
- Updated dependencies [cb68df0]
- Updated dependencies [ad80501]
- Updated dependencies [68ecf2f]
- Updated dependencies [9e9c809]
- Updated dependencies [32831c6]
- Updated dependencies [6dc848c]
- Updated dependencies [6b98118]
- Updated dependencies [d0f9495]
- Updated dependencies [3f2f00c]
- Updated dependencies [7979f7f]
- Updated dependencies [44f4aba]
- Updated dependencies [9bd5ab5]
- Updated dependencies [7ea4132]
- Updated dependencies [5c56081]
- Updated dependencies [fd65bc6]
- Updated dependencies [023ba40]
- Updated dependencies [26535e0]
- Updated dependencies [e030615]
- Updated dependencies [5e57fae]
- Updated dependencies [393138b]
- Updated dependencies [c57e248]
- Updated dependencies [3795467]
- Updated dependencies [7182d14]
- Updated dependencies [c1e6647]
- Updated dependencies [1766ede]
- Updated dependencies [811dff3]
- Updated dependencies [f10304b]
- Updated dependencies [33f4a6a]
- Updated dependencies [27deb4d]
- Updated dependencies [c4df419]
  - @ai-sdk/provider@2.0.0

## 3.0.0-beta.10

### Patch Changes

- 88a8ee5: fix (ai): support abort during retry waits

## 3.0.0-beta.9

### Patch Changes

- Updated dependencies [27deb4d]
  - @ai-sdk/provider@2.0.0-beta.2

## 3.0.0-beta.8

### Patch Changes

- dd5fd43: feat (ai): support dynamic tools in Chat onToolCall

## 3.0.0-beta.7

### Patch Changes

- e7fcc86: feat (ai): introduce dynamic tools

## 3.0.0-beta.6

### Patch Changes

- ac34802: Add clear object function to StructuredObject

## 3.0.0-beta.5

### Patch Changes

- 57edfcb: Adds support for async zod validators
- 383cbfa: feat (ai): add isAborted to onFinish callback for ui message streams

## 3.0.0-beta.4

### Patch Changes

- 205077b: fix: improve Zod compatibility

## 3.0.0-beta.3

### Patch Changes

- 05d2819: feat: allow zod 4.x as peer dependency

## 3.0.0-beta.2

### Patch Changes

- 0571b98: chore (provider-utils): update eventsource-parser to 3.0.3
- 39a4fab: fix (provider-utils): detect failed fetch in browser environments
- d1a034f: feature: using Zod 4 for internal stuff

## 3.0.0-beta.1

### Major Changes

- e025824: refactoring (ai): restructure provider-defined tools
- 71f938d: feat (ai): add output schema for tools

### Patch Changes

- 45c1ea2: refactoring: introduce FlexibleSchema
- bfdca8d: feat (ai): add InferToolInput and InferToolOutput helpers
- 28a5ed5: refactoring: move tools helper into provider-utils
- Updated dependencies [742b7be]
- Updated dependencies [7cddb72]
- Updated dependencies [ccce59b]
- Updated dependencies [e2b9e4b]
- Updated dependencies [0d06df6]
- Updated dependencies [472524a]
- Updated dependencies [dd3ff01]
- Updated dependencies [7435eb5]
- Updated dependencies [cb68df0]
- Updated dependencies [44f4aba]
- Updated dependencies [023ba40]
- Updated dependencies [5e57fae]
  - @ai-sdk/provider@2.0.0-beta.1

## 3.0.0-alpha.15

### Patch Changes

- 8ba77a7: chore (provider-utils): use eventsource-parser library
- Updated dependencies [48d257a]
  - @ai-sdk/provider@2.0.0-alpha.15

## 3.0.0-alpha.14

### Patch Changes

- Updated dependencies [b5da06a]
- Updated dependencies [63f9e9b]
- Updated dependencies [2e13791]
  - @ai-sdk/provider@2.0.0-alpha.14

## 3.0.0-alpha.13

### Patch Changes

- Updated dependencies [68ecf2f]
  - @ai-sdk/provider@2.0.0-alpha.13

## 3.0.0-alpha.12

### Patch Changes

- Updated dependencies [e2aceaf]
  - @ai-sdk/provider@2.0.0-alpha.12

## 3.0.0-alpha.11

### Patch Changes

- Updated dependencies [c1e6647]
  - @ai-sdk/provider@2.0.0-alpha.11

## 3.0.0-alpha.10

### Patch Changes

- Updated dependencies [c4df419]
  - @ai-sdk/provider@2.0.0-alpha.10

## 3.0.0-alpha.9

### Patch Changes

- Updated dependencies [811dff3]
  - @ai-sdk/provider@2.0.0-alpha.9

## 3.0.0-alpha.8

### Patch Changes

- 4fef487: feat: support for zod v4 for schema validation

  All these methods now accept both a zod v4 and zod v3 schemas for validation:

  - `generateObject()`
  - `streamObject()`
  - `generateText()`
  - `experimental_useObject()` from `@ai-sdk/react`
  - `streamUI()` from `@ai-sdk/rsc`

- Updated dependencies [9222aeb]
  - @ai-sdk/provider@2.0.0-alpha.8

## 3.0.0-alpha.7

### Patch Changes

- Updated dependencies [5c56081]
  - @ai-sdk/provider@2.0.0-alpha.7

## 3.0.0-alpha.6

### Patch Changes

- Updated dependencies [0d2c085]
  - @ai-sdk/provider@2.0.0-alpha.6

## 3.0.0-alpha.4

### Patch Changes

- Updated dependencies [dc714f3]
  - @ai-sdk/provider@2.0.0-alpha.4

## 3.0.0-alpha.3

### Patch Changes

- Updated dependencies [6b98118]
  - @ai-sdk/provider@2.0.0-alpha.3

## 3.0.0-alpha.2

### Patch Changes

- Updated dependencies [26535e0]
  - @ai-sdk/provider@2.0.0-alpha.2

## 3.0.0-alpha.1

### Patch Changes

- Updated dependencies [3f2f00c]
  - @ai-sdk/provider@2.0.0-alpha.1

## 3.0.0-canary.19

### Patch Changes

- faf8446: chore (provider-utils): switch to standard-schema

## 3.0.0-canary.18

### Major Changes

- 40acf9b: feat (ui): introduce ChatStore and ChatTransport

## 3.0.0-canary.17

### Major Changes

- ea7a7c9: feat (ui): UI message metadata

## 3.0.0-canary.16

### Patch Changes

- 87b828f: fix(provider-utils): fix SSE parser bug (CRLF)

## 3.0.0-canary.15

### Major Changes

- 41fa418: chore (provider-utils): return IdGenerator interface

### Patch Changes

- a571d6e: chore(provider-utils): move ToolResultContent to provider-utils
- Updated dependencies [a8c8bd5]
- Updated dependencies [7979f7f]
  - @ai-sdk/provider@2.0.0-canary.14

## 3.0.0-canary.14

### Major Changes

- 957b739: chore (provider-utils): rename TestServerCall.requestBody to requestBodyJson

### Patch Changes

- Updated dependencies [9bd5ab5]
  - @ai-sdk/provider@2.0.0-canary.13

## 3.0.0-canary.13

### Patch Changes

- 0ff02bb: chore(provider-utils): move over jsonSchema
- Updated dependencies [7b3ae3f]
  - @ai-sdk/provider@2.0.0-canary.12

## 3.0.0-canary.12

### Patch Changes

- Updated dependencies [9bf7291]
- Updated dependencies [4617fab]
- Updated dependencies [e030615]
  - @ai-sdk/provider@2.0.0-canary.11

## 3.0.0-canary.11

### Patch Changes

- 66962ed: fix(packages): export node10 compatible types
- Updated dependencies [9301f86]
- Updated dependencies [a3f768e]
  - @ai-sdk/provider@2.0.0-canary.10

## 3.0.0-canary.10

### Patch Changes

- Updated dependencies [e86be6f]
  - @ai-sdk/provider@2.0.0-canary.9

## 3.0.0-canary.9

### Patch Changes

- Updated dependencies [95857aa]
- Updated dependencies [7ea4132]
  - @ai-sdk/provider@2.0.0-canary.8

## 3.0.0-canary.8

### Major Changes

- 5d142ab: remove deprecated `CoreToolCall` and `CoreToolResult` types

### Patch Changes

- Updated dependencies [b6b43c7]
- Updated dependencies [8aa9e20]
- Updated dependencies [3795467]
  - @ai-sdk/provider@2.0.0-canary.7

## 3.0.0-canary.7

### Patch Changes

- Updated dependencies [26735b5]
- Updated dependencies [443d8ec]
- Updated dependencies [14c9410]
- Updated dependencies [d9c98f4]
- Updated dependencies [c4a2fec]
- Updated dependencies [0054544]
- Updated dependencies [9e9c809]
- Updated dependencies [32831c6]
- Updated dependencies [d0f9495]
- Updated dependencies [fd65bc6]
- Updated dependencies [393138b]
- Updated dependencies [7182d14]
  - @ai-sdk/provider@2.0.0-canary.6

## 3.0.0-canary.6

### Patch Changes

- Updated dependencies [411e483]
- Updated dependencies [79457bd]
- Updated dependencies [ad80501]
- Updated dependencies [1766ede]
- Updated dependencies [f10304b]
  - @ai-sdk/provider@2.0.0-canary.5

## 3.0.0-canary.5

### Patch Changes

- Updated dependencies [6f6bb89]
  - @ai-sdk/provider@2.0.0-canary.4

## 3.0.0-canary.4

### Patch Changes

- Updated dependencies [d1a1aa1]
  - @ai-sdk/provider@2.0.0-canary.3

## 3.0.0-canary.3

### Patch Changes

- a166433: feat: add transcription with experimental_transcribe
- 9f95b35: refactor (provider-utils): copy relevant code from `secure-json-parse` into codebase
- Updated dependencies [a166433]
- Updated dependencies [abf9a79]
- Updated dependencies [0a87932]
- Updated dependencies [6dc848c]
  - @ai-sdk/provider@2.0.0-canary.2

## 3.0.0-canary.2

### Patch Changes

- Updated dependencies [c57e248]
- Updated dependencies [33f4a6a]
  - @ai-sdk/provider@2.0.0-canary.1

## 3.0.0-canary.1

### Patch Changes

- 060370c: feat(provider-utils): add TestServerCall#requestCredentials
- 0c0c0b3: refactor (provider-utils): move `customAlphabet()` method from `nanoid` into codebase
- 63d791d: chore (utils): remove unused test helpers

## 3.0.0-canary.0

### Major Changes

- d5f588f: AI SDK 5

### Patch Changes

- Updated dependencies [d5f588f]
  - @ai-sdk/provider@2.0.0-canary.0

## 2.2.3

### Patch Changes

- 28be004: chore (provider-utils): add error method to TestStreamController

## 2.2.2

### Patch Changes

- b01120e: chore (provider-utils): update unified test server

## 2.2.1

### Patch Changes

- f10f0fa: fix (provider-utils): improve event source stream parsing performance

## 2.2.0

### Minor Changes

- 5bc638d: AI SDK 4.2

### Patch Changes

- Updated dependencies [5bc638d]
  - @ai-sdk/provider@1.1.0

## 2.1.15

### Patch Changes

- d0c4659: feat (provider-utils): parseProviderOptions function

## 2.1.14

### Patch Changes

- Updated dependencies [0bd5bc6]
  - @ai-sdk/provider@1.0.12

## 2.1.13

### Patch Changes

- Updated dependencies [2e1101a]
  - @ai-sdk/provider@1.0.11

## 2.1.12

### Patch Changes

- 1531959: feat (provider-utils): add readable-stream to unified test server

## 2.1.11

### Patch Changes

- Updated dependencies [e1d3d42]
  - @ai-sdk/provider@1.0.10

## 2.1.10

### Patch Changes

- Updated dependencies [ddf9740]
  - @ai-sdk/provider@1.0.9

## 2.1.9

### Patch Changes

- Updated dependencies [2761f06]
  - @ai-sdk/provider@1.0.8

## 2.1.8

### Patch Changes

- 2e898b4: chore (ai): move mockId test helper into provider utils

## 2.1.7

### Patch Changes

- 3ff4ef8: feat (provider-utils): export removeUndefinedEntries for working with e.g. headers

## 2.1.6

### Patch Changes

- Updated dependencies [d89c3b9]
  - @ai-sdk/provider@1.0.7

## 2.1.5

### Patch Changes

- 3a602ca: chore (core): rename CoreTool to Tool

## 2.1.4

### Patch Changes

- 066206e: feat (provider-utils): move delay to provider-utils from ai

## 2.1.3

### Patch Changes

- 39e5c1f: feat (provider-utils): add getFromApi and response handlers for binary responses and status-code errors

## 2.1.2

### Patch Changes

- ed012d2: feat (provider): add metadata extraction mechanism to openai-compatible providers
- Updated dependencies [3a58a2e]
  - @ai-sdk/provider@1.0.6

## 2.1.1

### Patch Changes

- e7a9ec9: feat (provider-utils): include raw value in json parse results
- Updated dependencies [0a699f1]
  - @ai-sdk/provider@1.0.5

## 2.1.0

### Minor Changes

- 62ba5ad: release: AI SDK 4.1

## 2.0.8

### Patch Changes

- 00114c5: feat: expose IDGenerator and createIdGenerator

## 2.0.7

### Patch Changes

- 90fb95a: chore (provider-utils): switch to unified test server
- e6dfef4: feat (provider/fireworks): Support add'l image models.
- 6636db6: feat (provider-utils): add unified test server

## 2.0.6

### Patch Changes

- 19a2ce7: feat (provider/fireworks): Add image model support.
- 6337688: feat: change image generation errors to warnings
- Updated dependencies [19a2ce7]
- Updated dependencies [6337688]
  - @ai-sdk/provider@1.0.4

## 2.0.5

### Patch Changes

- 5ed5e45: chore (config): Use ts-library.json tsconfig for no-UI libs.
- Updated dependencies [5ed5e45]
  - @ai-sdk/provider@1.0.3

## 2.0.4

### Patch Changes

- Updated dependencies [09a9cab]
  - @ai-sdk/provider@1.0.2

## 2.0.3

### Patch Changes

- 0984f0b: feat (provider-utils): Add resolvable type and utility routine.

## 2.0.2

### Patch Changes

- Updated dependencies [b446ae5]
  - @ai-sdk/provider@1.0.1

## 2.0.1

### Patch Changes

- c3ab5de: fix (provider-utils): downgrade nanoid and secure-json-parse (ESM compatibility)

## 2.0.0

### Major Changes

- b469a7e: chore: remove isXXXError methods
- b1da952: chore (provider-utils): remove convertStreamToArray
- 8426f55: chore (ai):increase id generator default size from 7 to 16.
- db46ce5: chore (provider-utils): remove isParseableJson export

### Patch Changes

- dce4158: chore (dependencies): update eventsource-parser to 3.0.0
- dce4158: chore (dependencies): update nanoid to 5.0.8
- Updated dependencies [b469a7e]
- Updated dependencies [c0ddc24]
  - @ai-sdk/provider@1.0.0

## 2.0.0-canary.3

### Major Changes

- 8426f55: chore (ai):increase id generator default size from 7 to 16.

## 2.0.0-canary.2

### Patch Changes

- dce4158: chore (dependencies): update eventsource-parser to 3.0.0
- dce4158: chore (dependencies): update nanoid to 5.0.8

## 2.0.0-canary.1

### Major Changes

- b1da952: chore (provider-utils): remove convertStreamToArray

## 2.0.0-canary.0

### Major Changes

- b469a7e: chore: remove isXXXError methods
- db46ce5: chore (provider-utils): remove isParseableJson export

### Patch Changes

- Updated dependencies [b469a7e]
- Updated dependencies [c0ddc24]
  - @ai-sdk/provider@1.0.0-canary.0

## 1.0.22

### Patch Changes

- aa98cdb: chore: more flexible dependency versioning
- 7b937c5: feat (provider-utils): improve id generator robustness
- 811a317: feat (ai/core): multi-part tool results (incl. images)
- Updated dependencies [aa98cdb]
- Updated dependencies [1486128]
- Updated dependencies [7b937c5]
- Updated dependencies [3b1b69a]
- Updated dependencies [811a317]
  - @ai-sdk/provider@0.0.26

## 1.0.21

### Patch Changes

- Updated dependencies [b9b0d7b]
  - @ai-sdk/provider@0.0.25

## 1.0.20

### Patch Changes

- Updated dependencies [d595d0d]
  - @ai-sdk/provider@0.0.24

## 1.0.19

### Patch Changes

- 273f696: fix (ai/provider-utils): expose size argument in generateId

## 1.0.18

### Patch Changes

- 03313cd: feat (ai): expose response id, response model, response timestamp in telemetry and api
- Updated dependencies [03313cd]
- Updated dependencies [3be7c1c]
  - @ai-sdk/provider@0.0.23

## 1.0.17

### Patch Changes

- Updated dependencies [26515cb]
  - @ai-sdk/provider@0.0.22

## 1.0.16

### Patch Changes

- 09f895f: feat (ai/core): no-schema output for generateObject / streamObject

## 1.0.15

### Patch Changes

- d67fa9c: feat (provider/amazon-bedrock): add support for session tokens

## 1.0.14

### Patch Changes

- Updated dependencies [f2c025e]
  - @ai-sdk/provider@0.0.21

## 1.0.13

### Patch Changes

- Updated dependencies [6ac355e]
  - @ai-sdk/provider@0.0.20

## 1.0.12

### Patch Changes

- dd712ac: fix: use FetchFunction type to prevent self-reference

## 1.0.11

### Patch Changes

- Updated dependencies [dd4a0f5]
  - @ai-sdk/provider@0.0.19

## 1.0.10

### Patch Changes

- 4bd27a9: chore (ai/provider): refactor type validation
- 845754b: fix (ai/provider): fix atob/btoa execution on cloudflare edge workers
- Updated dependencies [4bd27a9]
  - @ai-sdk/provider@0.0.18

## 1.0.9

### Patch Changes

- Updated dependencies [029af4c]
  - @ai-sdk/provider@0.0.17

## 1.0.8

### Patch Changes

- Updated dependencies [d58517b]
  - @ai-sdk/provider@0.0.16

## 1.0.7

### Patch Changes

- Updated dependencies [96aed25]
  - @ai-sdk/provider@0.0.15

## 1.0.6

### Patch Changes

- 9614584: fix (ai/core): use Symbol.for
- 0762a22: feat (ai/core): support zod transformers in generateObject & streamObject

## 1.0.5

### Patch Changes

- a8d1c9e9: feat (ai/core): parallel image download
- Updated dependencies [a8d1c9e9]
  - @ai-sdk/provider@0.0.14

## 1.0.4

### Patch Changes

- 4f88248f: feat (core): support json schema

## 1.0.3

### Patch Changes

- Updated dependencies [2b9da0f0]
- Updated dependencies [a5b58845]
- Updated dependencies [4aa8deb3]
- Updated dependencies [13b27ec6]
  - @ai-sdk/provider@0.0.13

## 1.0.2

### Patch Changes

- Updated dependencies [b7290943]
  - @ai-sdk/provider@0.0.12

## 1.0.1

### Patch Changes

- d481729f: fix (ai/provider-utils): generalize to Error (DomException not always available)

## 1.0.0

### Major Changes

- 5edc6110: feat (provider-utils): change getRequestHeader() test helper to return Record (breaking change)

### Patch Changes

- 5edc6110: feat (provider-utils): add combineHeaders helper
- Updated dependencies [5edc6110]
  - @ai-sdk/provider@0.0.11

## 0.0.16

### Patch Changes

- 02f6a088: feat (provider-utils): add convertArrayToAsyncIterable test helper

## 0.0.15

### Patch Changes

- 85712895: feat (@ai-sdk/provider-utils): add createJsonStreamResponseHandler
- 85712895: chore (@ai-sdk/provider-utils): move test helper to provider utils

## 0.0.14

### Patch Changes

- 7910ae84: feat (providers): support custom fetch implementations

## 0.0.13

### Patch Changes

- Updated dependencies [102ca22f]
  - @ai-sdk/provider@0.0.10

## 0.0.12

### Patch Changes

- 09295e2e: feat (@ai-sdk/provider-utils): add download helper
- 043a5de2: fix (provider-utils): rename to isParsableJson
- Updated dependencies [09295e2e]
  - @ai-sdk/provider@0.0.9

## 0.0.11

### Patch Changes

- Updated dependencies [f39c0dd2]
  - @ai-sdk/provider@0.0.8

## 0.0.10

### Patch Changes

- Updated dependencies [8e780288]
  - @ai-sdk/provider@0.0.7

## 0.0.9

### Patch Changes

- 6a50ac4: feat (provider-utils): add loadSetting and convertAsyncGeneratorToReadableStream helpers
- Updated dependencies [6a50ac4]
  - @ai-sdk/provider@0.0.6

## 0.0.8

### Patch Changes

- Updated dependencies [0f6bc4e]
  - @ai-sdk/provider@0.0.5

## 0.0.7

### Patch Changes

- Updated dependencies [325ca55]
  - @ai-sdk/provider@0.0.4

## 0.0.6

### Patch Changes

- 276f22b: fix (ai/provider): improve request error handling

## 0.0.5

### Patch Changes

- Updated dependencies [41d5736]
  - @ai-sdk/provider@0.0.3

## 0.0.4

### Patch Changes

- 56ef84a: ai/core: fix abort handling in transformation stream

## 0.0.3

### Patch Changes

- 25f3350: ai/core: add support for getting raw response headers.
- Updated dependencies [d6431ae]
- Updated dependencies [25f3350]
  - @ai-sdk/provider@0.0.2

## 0.0.2

### Patch Changes

- eb150a6: ai/core: remove scaling of setting values (breaking change). If you were using the temperature, frequency penalty, or presence penalty settings, you need to update the providers and adjust the setting values.
- Updated dependencies [eb150a6]
  - @ai-sdk/provider@0.0.1

## 0.0.1

### Patch Changes

- 7b8791d: Rename baseUrl to baseURL. Automatically remove trailing slashes.
