# ai

## 4.3.19

### Patch Changes

- 849af1c: feat(ai): Record tool call errors on tool call spans recorded in `generateText` and `streamText`.

## 4.3.18

### Patch Changes

- 37d93f4: fix (ai): throw error for v2 models or string model ids

## 4.3.17

### Patch Changes

- a288694: Expose provider metadata as an attribute on exported OTEL spans

## 4.3.16

### Patch Changes

- ed0ebeb: Avoid JSON.strinfigy on UInt8Arrays for telemetry

## 4.3.15

### Patch Changes

- Updated dependencies [d87b9d1]
  - @ai-sdk/provider-utils@2.2.8
  - @ai-sdk/react@1.2.12
  - @ai-sdk/ui-utils@1.2.11

## 4.3.14

### Patch Changes

- a295521: feat(message-validator): include more details in error messages

## 4.3.13

### Patch Changes

- Updated dependencies [6c59ae7]
  - @ai-sdk/ui-utils@1.2.10
  - @ai-sdk/react@1.2.11

## 4.3.12

### Patch Changes

- 1ed3755: fix (ai): don't publish mcp-stdio TypeScript files
- 46cb332: chore (ai/mcp): add `assertCapability` method to experimental MCP client

## 4.3.11

### Patch Changes

- Updated dependencies [77b2097]
- Updated dependencies [62181ef]
  - @ai-sdk/react@1.2.10
  - @ai-sdk/ui-utils@1.2.9

## 4.3.10

### Patch Changes

- 0432959: feat (ai): add experimental prepareStep callback to generateText

## 4.3.9

### Patch Changes

- b69a253: fix(utils/detect-mimetype): add support for detecting id3 tags

## 4.3.8

### Patch Changes

- 6e8a73b: feat(providers/fal): add transcribe

## 4.3.7

### Patch Changes

- f4f3945: fix (ai/core): refactor `toResponseMessages` to filter out empty string/content

## 4.3.6

### Patch Changes

- beef951: feat: add speech with experimental_generateSpeech
- bd41167: fix(ai/core): properly handle custom separator in provider registry
- Updated dependencies [beef951]
  - @ai-sdk/provider@1.1.3
  - @ai-sdk/provider-utils@2.2.7
  - @ai-sdk/ui-utils@1.2.8
  - @ai-sdk/react@1.2.9

## 4.3.5

### Patch Changes

- 452bf12: fix (ai/mcp): better support for zero-argument MCP tools

## 4.3.4

### Patch Changes

- 013faa8: core (ai): change transcription model mimeType to mediaType
- Updated dependencies [013faa8]
  - @ai-sdk/provider@1.1.2
  - @ai-sdk/provider-utils@2.2.6
  - @ai-sdk/ui-utils@1.2.7
  - @ai-sdk/react@1.2.8

## 4.3.3

### Patch Changes

- 3e88f4d: fix (ai/mcp): prevent mutation of customEnv
- c21fa6d: feat: add transcription with experimental_transcribe
- Updated dependencies [c21fa6d]
  - @ai-sdk/provider-utils@2.2.5
  - @ai-sdk/provider@1.1.1
  - @ai-sdk/react@1.2.7
  - @ai-sdk/ui-utils@1.2.6

## 4.3.2

### Patch Changes

- 665a567: fix (core): improve error handling in streamText's consumeStream method

## 4.3.1

### Patch Changes

- 3d1bd38: feat(smooth-stream): chunking callbacks

## 4.3.0

### Minor Changes

- 772a2d7: feat (core): Add finishReason field to NoObjectGeneratedError

### Patch Changes

- Updated dependencies [2c19b9a]
  - @ai-sdk/provider-utils@2.2.4
  - @ai-sdk/react@1.2.6
  - @ai-sdk/ui-utils@1.2.5

## 4.2.11

### Patch Changes

- c45d100: fix (core): send buffered text in smooth stream when stream parts change

## 4.2.10

### Patch Changes

- Updated dependencies [a043b14]
- Updated dependencies [28be004]
  - @ai-sdk/react@1.2.5
  - @ai-sdk/provider-utils@2.2.3
  - @ai-sdk/ui-utils@1.2.4

## 4.2.9

### Patch Changes

- Updated dependencies [b01120e]
  - @ai-sdk/provider-utils@2.2.2
  - @ai-sdk/react@1.2.4
  - @ai-sdk/ui-utils@1.2.3

## 4.2.8

### Patch Changes

- 65243ce: fix (ui): introduce step start parts
- Updated dependencies [65243ce]
  - @ai-sdk/ui-utils@1.2.2
  - @ai-sdk/react@1.2.3

## 4.2.7

### Patch Changes

- e14c066: fix (ai/core): convert user ui messages with only parts (no content) to core messages

## 4.2.6

### Patch Changes

- 625591b: feat (ai/core): auto-complete for provider registry
- 6a1506f: feat (ai/core): custom separator support for provider registry
- ea3d998: chore (ai/core): move provider registry to stable

## 4.2.5

### Patch Changes

- Updated dependencies [d92fa29]
  - @ai-sdk/react@1.2.2

## 4.2.4

### Patch Changes

- 3d6d96d: fix (ai/core): validate that messages are not empty

## 4.2.3

### Patch Changes

- 0b3bf29: fix (ai/core): custom env support for stdio MCP transport

## 4.2.2

### Patch Changes

- f10f0fa: fix (provider-utils): improve event source stream parsing performance
- Updated dependencies [f10f0fa]
  - @ai-sdk/provider-utils@2.2.1
  - @ai-sdk/react@1.2.1
  - @ai-sdk/ui-utils@1.2.1

## 4.2.1

### Patch Changes

- b796152: feat (ai/core): add headers to MCP SSE transport
- 06361d6: feat (ai/core): expose JSON RPC types (MCP)

## 4.2.0

### Minor Changes

- 5bc638d: AI SDK 4.2

### Patch Changes

- Updated dependencies [5bc638d]
  - @ai-sdk/provider@1.1.0
  - @ai-sdk/provider-utils@2.2.0
  - @ai-sdk/react@1.2.0
  - @ai-sdk/ui-utils@1.2.0

## 4.1.66

### Patch Changes

- 5d0fc29: chore (ai): improve cosine similarity calculation

## 4.1.65

### Patch Changes

- 16c444f: fix (ai): expose ai/mcp-stdio

## 4.1.64

### Patch Changes

- Updated dependencies [d0c4659]
  - @ai-sdk/provider-utils@2.1.15
  - @ai-sdk/react@1.1.25
  - @ai-sdk/ui-utils@1.1.21

## 4.1.63

### Patch Changes

- 0bd5bc6: feat (ai): support model-generated files
- Updated dependencies [0bd5bc6]
  - @ai-sdk/provider@1.0.12
  - @ai-sdk/provider-utils@2.1.14
  - @ai-sdk/ui-utils@1.1.20
  - @ai-sdk/react@1.1.24

## 4.1.62

### Patch Changes

- c9ed3c4: feat: enable custom mcp transports
  breaking change: remove internal stdio transport creation

## 4.1.61

### Patch Changes

- 2e1101a: feat (provider/openai): pdf input support
- Updated dependencies [2e1101a]
  - @ai-sdk/provider@1.0.11
  - @ai-sdk/provider-utils@2.1.13
  - @ai-sdk/ui-utils@1.1.19
  - @ai-sdk/react@1.1.23

## 4.1.60

### Patch Changes

- 0b8797f: feat (ai/core): expose response body for each generateText step

## 4.1.59

### Patch Changes

- dd18049: fix (ai/core): suppress next.js warnings for node.js specific code path

## 4.1.58

### Patch Changes

- e9897eb: fix (ai/core): move process access into functions and use globalThis

## 4.1.57

### Patch Changes

- 092fdaa: feat (ai/core): add defaultSettingsMiddleware

## 4.1.56

### Patch Changes

- 80be82b: feat (ai/core): add simulateStreamingMiddleware
- 8109a24: fix (ai/core): limit node imports to types where possible

## 4.1.55

### Patch Changes

- 1531959: feat (ai/core): add MCP client for using MCP tools
- Updated dependencies [1531959]
  - @ai-sdk/provider-utils@2.1.12
  - @ai-sdk/react@1.1.22
  - @ai-sdk/ui-utils@1.1.18

## 4.1.54

### Patch Changes

- ee1c787: fix (ai/core): correct spread apply order to fix extract reasoning middleware with generateText

## 4.1.53

### Patch Changes

- e1d3d42: feat (ai): expose raw response body in generateText and generateObject
- Updated dependencies [e1d3d42]
  - @ai-sdk/provider@1.0.10
  - @ai-sdk/provider-utils@2.1.11
  - @ai-sdk/ui-utils@1.1.17
  - @ai-sdk/react@1.1.21

## 4.1.52

### Patch Changes

- 5329a69: fix (ai/core): fix duplicated reasoning in streamText onFinish and messages

## 4.1.51

### Patch Changes

- 0cb2647: feat (ai/core): add streamText sendStart & sendFinish data stream options

## 4.1.50

### Patch Changes

- ae98f0d: fix (ai/core): forward providerOptions for text, image, and file parts

## 4.1.49

### Patch Changes

- dc027d3: fix (ai/core): add reasoning support to appendResponseMessages

## 4.1.48

### Patch Changes

- Updated dependencies [6255fbc]
  - @ai-sdk/react@1.1.20

## 4.1.47

### Patch Changes

- Updated dependencies [da5c734]
  - @ai-sdk/react@1.1.19

## 4.1.46

### Patch Changes

- ddf9740: feat (ai): add anthropic reasoning
- Updated dependencies [ddf9740]
  - @ai-sdk/provider@1.0.9
  - @ai-sdk/ui-utils@1.1.16
  - @ai-sdk/provider-utils@2.1.10
  - @ai-sdk/react@1.1.18

## 4.1.45

### Patch Changes

- 93bd5a0: feat (ai/ui): add writeSource to createDataStream

## 4.1.44

### Patch Changes

- f8e7df2: fix (ai/core): add `startWithReasoning` option to `extractReasoningMiddleware`

## 4.1.43

### Patch Changes

- ef2e23b: feat (ai/core): add experimental repairText function to generateObject

## 4.1.42

### Patch Changes

- Updated dependencies [2761f06]
  - @ai-sdk/provider@1.0.8
  - @ai-sdk/provider-utils@2.1.9
  - @ai-sdk/ui-utils@1.1.15
  - @ai-sdk/react@1.1.17

## 4.1.41

### Patch Changes

- Updated dependencies [60c3220]
  - @ai-sdk/react@1.1.16

## 4.1.40

### Patch Changes

- Updated dependencies [c43df41]
  - @ai-sdk/react@1.1.15

## 4.1.39

### Patch Changes

- 075a9a9: fix (ai): improve tsdoc on custom provider

## 4.1.38

### Patch Changes

- 4c9c194: chore (ai): add description to provider-defined tools for better accessibility
- 2e898b4: chore (ai): move mockId test helper into provider utils
- Updated dependencies [2e898b4]
  - @ai-sdk/provider-utils@2.1.8
  - @ai-sdk/react@1.1.14
  - @ai-sdk/ui-utils@1.1.14

## 4.1.37

### Patch Changes

- c1e10d1: chore: export UIMessage type

## 4.1.36

### Patch Changes

- Updated dependencies [3ff4ef8]
  - @ai-sdk/provider-utils@2.1.7
  - @ai-sdk/react@1.1.13
  - @ai-sdk/ui-utils@1.1.13

## 4.1.35

### Patch Changes

- 166e09e: feat (ai/ui): forward source parts to useChat
- Updated dependencies [166e09e]
  - @ai-sdk/ui-utils@1.1.12
  - @ai-sdk/react@1.1.12

## 4.1.34

### Patch Changes

- dc49119: chore: deprecate ai/react

## 4.1.33

### Patch Changes

- 74f0f0e: chore (ai/core): move providerMetadata to stable

## 4.1.32

### Patch Changes

- c128ca5: fix (ai/core): fix streamText onFinish messages with structured output

## 4.1.31

### Patch Changes

- b30b1cc: feat (ai/core): add onError callback to streamObject

## 4.1.30

### Patch Changes

- 4ee5b6f: fix (core): remove invalid providerOptions from streamObject onFinish callback

## 4.1.29

### Patch Changes

- 605de49: feat (ai/core): export callback types

## 4.1.28

### Patch Changes

- 6eb7fc4: feat (ai/core): url source support

## 4.1.27

### Patch Changes

- Updated dependencies [318b351]
  - @ai-sdk/ui-utils@1.1.11
  - @ai-sdk/react@1.1.11

## 4.1.26

### Patch Changes

- 34983d4: fix (ai/core): bind supportsUrl when creating wrapper

## 4.1.25

### Patch Changes

- 5a21310: fix (ai/core): use ai types on custom provider to prevent ts error

## 4.1.24

### Patch Changes

- 38142b8: feat (ai/core): introduce streamText consumeStream

## 4.1.23

### Patch Changes

- b08f7c1: fix (ai/core): suppress errors in textStream

## 4.1.22

### Patch Changes

- 2bec72a: feat (ai/core): add onError callback to streamText

## 4.1.21

### Patch Changes

- d387989: feat (ai/core): re-export zodSchema

## 4.1.20

### Patch Changes

- bcc61d4: feat (ui): introduce message parts for useChat
- Updated dependencies [bcc61d4]
  - @ai-sdk/ui-utils@1.1.10
  - @ai-sdk/react@1.1.10

## 4.1.19

### Patch Changes

- Updated dependencies [6b8cc14]
  - @ai-sdk/ui-utils@1.1.9
  - @ai-sdk/react@1.1.9

## 4.1.18

### Patch Changes

- 6a1acfe: fix (ai/core): revert '@internal' tag on function definitions due to build impacts

## 4.1.17

### Patch Changes

- 5af8cdb: fix (ai/core): support this reference in model.supportsUrl implementations

## 4.1.16

### Patch Changes

- 7e299a4: feat (ai/core): wrapLanguageModel can apply multiple middlewares

## 4.1.15

### Patch Changes

- d89c3b9: feat (provider): add image model support to provider specification
- d89c3b9: feat (core): type ahead for model ids with custom provider
- 08f54fc: chore (ai/core): move custom provider to stable
- Updated dependencies [d89c3b9]
  - @ai-sdk/provider@1.0.7
  - @ai-sdk/provider-utils@2.1.6
  - @ai-sdk/ui-utils@1.1.8
  - @ai-sdk/react@1.1.8

## 4.1.14

### Patch Changes

- ca89615: fix (ai/core): only append assistant response at the end when there is a final user message

## 4.1.13

### Patch Changes

- 999085e: feat (ai/core): add write function to DataStreamWriter

## 4.1.12

### Patch Changes

- 0d2d9bf: fix (ui): single assistant message with multiple tool steps
- Updated dependencies [0d2d9bf]
- Updated dependencies [0d2d9bf]
  - @ai-sdk/react@1.1.7
  - @ai-sdk/ui-utils@1.1.7

## 4.1.11

### Patch Changes

- 4c58da5: chore (core): move providerOptions to stable

## 4.1.10

### Patch Changes

- bf2c9c6: feat (core): move middleware to stable

## 4.1.9

### Patch Changes

- 3a602ca: chore (core): rename CoreTool to Tool
- Updated dependencies [3a602ca]
  - @ai-sdk/provider-utils@2.1.5
  - @ai-sdk/ui-utils@1.1.6
  - @ai-sdk/react@1.1.6

## 4.1.8

### Patch Changes

- 92f5f36: feat (core): add extractReasoningMiddleware

## 4.1.7

### Patch Changes

- 066206e: feat (provider-utils): move delay to provider-utils from ai
- Updated dependencies [066206e]
  - @ai-sdk/provider-utils@2.1.4
  - @ai-sdk/react@1.1.5
  - @ai-sdk/ui-utils@1.1.5

## 4.1.6

### Patch Changes

- Updated dependencies [39e5c1f]
  - @ai-sdk/provider-utils@2.1.3
  - @ai-sdk/react@1.1.4
  - @ai-sdk/ui-utils@1.1.4

## 4.1.5

### Patch Changes

- 9ce598c: feat (ai/ui): add reasoning support to useChat
- Updated dependencies [9ce598c]
  - @ai-sdk/ui-utils@1.1.3
  - @ai-sdk/react@1.1.3

## 4.1.4

### Patch Changes

- caaad11: feat (ai/core): re-export languagemodelv1 types for middleware implementations
- caaad11: feat (ai/core): expose TelemetrySettings type

## 4.1.3

### Patch Changes

- 7f30a77: feat (core): export core message schemas
- 4298996: feat (core): add helper for merging single client message

## 4.1.2

### Patch Changes

- 3c5fafa: chore (ai/core): move streamText toolCallStreaming option to stable
- 3a58a2e: feat (ai/core): throw NoImageGeneratedError from generateImage when no predictions are returned.
- Updated dependencies [ed012d2]
- Updated dependencies [6f4d063]
- Updated dependencies [3a58a2e]
  - @ai-sdk/provider-utils@2.1.2
  - @ai-sdk/react@1.1.2
  - @ai-sdk/provider@1.0.6
  - @ai-sdk/ui-utils@1.1.2

## 4.1.1

### Patch Changes

- 0a699f1: feat: add reasoning token support
- Updated dependencies [e7a9ec9]
- Updated dependencies [0a699f1]
  - @ai-sdk/ui-utils@1.1.1
  - @ai-sdk/provider-utils@2.1.1
  - @ai-sdk/provider@1.0.5
  - @ai-sdk/react@1.1.1

## 4.1.0

### Minor Changes

- 62ba5ad: release: AI SDK 4.1

### Patch Changes

- Updated dependencies [62ba5ad]
  - @ai-sdk/provider-utils@2.1.0
  - @ai-sdk/react@1.1.0
  - @ai-sdk/ui-utils@1.1.0

## 4.0.41

### Patch Changes

- Updated dependencies [44f04d5]
  - @ai-sdk/react@1.0.14

## 4.0.40

### Patch Changes

- 33592d2: fix (ai/core): switch to json schema 7 target for zod to json schema conversion
- Updated dependencies [33592d2]
  - @ai-sdk/ui-utils@1.0.12
  - @ai-sdk/react@1.0.13

## 4.0.39

### Patch Changes

- 00114c5: feat: expose IDGenerator and createIdGenerator
- 00114c5: feat (ui): generate and forward message ids for response messages
- Updated dependencies [00114c5]
- Updated dependencies [00114c5]
  - @ai-sdk/provider-utils@2.0.8
  - @ai-sdk/ui-utils@1.0.11
  - @ai-sdk/react@1.0.12

## 4.0.38

### Patch Changes

- 0118fa7: fix (ai/core): handle empty tool invocation array in convertToCoreMessages

## 4.0.37

### Patch Changes

- 8304ed8: feat (ai/core): Add option `throwErrorForEmptyVectors` to cosineSimilarity
- ed28182: feat (ai/ui): add appendResponseMessages helper

## 4.0.36

### Patch Changes

- Updated dependencies [37f4510]
  - @ai-sdk/ui-utils@1.0.10
  - @ai-sdk/react@1.0.11

## 4.0.35

### Patch Changes

- 3491f78: feat (ai/core): support multiple stream text transforms

## 4.0.34

### Patch Changes

- 2495973: feat (ai/core): use openai compatible mode for json schema conversion
- 2495973: fix (ai/core): duplicate instead of using reference in json schema
- Updated dependencies [2495973]
- Updated dependencies [2495973]
  - @ai-sdk/ui-utils@1.0.9
  - @ai-sdk/react@1.0.10

## 4.0.33

### Patch Changes

- 5510ee7: feat (ai/core): add stopStream option to streamText transforms

## 4.0.32

### Patch Changes

- de66619: feat (ai/core): add tool call id to ToolExecution error

## 4.0.31

### Patch Changes

- Updated dependencies [90fb95a]
- Updated dependencies [e6dfef4]
- Updated dependencies [6636db6]
  - @ai-sdk/provider-utils@2.0.7
  - @ai-sdk/react@1.0.9
  - @ai-sdk/ui-utils@1.0.8

## 4.0.30

### Patch Changes

- e4ce80c: fix (ai/core): prevent onFinish from masking stream errors

## 4.0.29

### Patch Changes

- a92f5f6: feat (ai/core): generate many images with parallel model calls

## 4.0.28

### Patch Changes

- 19a2ce7: feat (ai/core): add aspectRatio and seed options to generateImage
- 6337688: feat: change image generation errors to warnings
- 8b422ea: feat (ai/core): add caching to generated images
- Updated dependencies [19a2ce7]
- Updated dependencies [19a2ce7]
- Updated dependencies [6337688]
  - @ai-sdk/provider@1.0.4
  - @ai-sdk/provider-utils@2.0.6
  - @ai-sdk/ui-utils@1.0.7
  - @ai-sdk/react@1.0.8

## 4.0.27

### Patch Changes

- a56734f: feat (ai/core): export simulateReadableStream in ai package
- 9589601: feat (ai/core): support null delay in smoothStream
- e3cc23a: feat (ai/core): support regexp chunking pattern in smoothStream
- e463e73: feat (ai/core): support skipping delays in simulateReadableStream

## 4.0.26

### Patch Changes

- a8f3242: feat (ai/core): add line chunking mode to smoothStream

## 4.0.25

### Patch Changes

- 0823899: fix (ai/core): throw error when accessing output when no output is defined in generateText (breaking/experimental)

## 4.0.24

### Patch Changes

- ae0485b: feat (ai/core): add experimental output setting to streamText

## 4.0.23

### Patch Changes

- bc4cd19: feat (ai/core): consolidate whitespace in smooth stream

## 4.0.22

### Patch Changes

- Updated dependencies [5ed5e45]
  - @ai-sdk/provider-utils@2.0.5
  - @ai-sdk/provider@1.0.3
  - @ai-sdk/react@1.0.7
  - @ai-sdk/ui-utils@1.0.6

## 4.0.21

### Patch Changes

- a8669a2: fix (ai/core): prefer auto-detected image mimetype
- 6fb3e91: fix (ai/core): include type in generateText toolResults result property.

## 4.0.20

### Patch Changes

- da9d240: fix (ai/core): suppress errors caused by writing to closed stream
- 6f1bfde: fix (ai/core): invoke streamText tool call repair when tool cannot be found

## 4.0.19

### Patch Changes

- c3a6065: fix (ai/core): apply transform before callbacks and resolvables

## 4.0.18

### Patch Changes

- 304e6d3: feat (ai/core): standardize generateObject, streamObject, and output errors to NoObjectGeneratedError
- 304e6d3: feat (ai/core): add additional information to NoObjectGeneratedError

## 4.0.17

### Patch Changes

- 54bbf21: fix (ai/core): change streamText.experimental_transform signature to support tool type inference

## 4.0.16

### Patch Changes

- e3fac3f: fix (ai/core): change smoothStream default delay to 10ms

## 4.0.15

### Patch Changes

- cc16a83: feat (ai/core): add smoothStream helper
- cc16a83: feat (ai/core): add experimental transform option to streamText

## 4.0.14

### Patch Changes

- 09a9cab: feat (ai/core): add experimental generateImage function
- Updated dependencies [09a9cab]
  - @ai-sdk/provider@1.0.2
  - @ai-sdk/provider-utils@2.0.4
  - @ai-sdk/ui-utils@1.0.5
  - @ai-sdk/react@1.0.6

## 4.0.13

### Patch Changes

- 9f32213: feat (ai/core): add experimental tool call repair

## 4.0.12

### Patch Changes

- 5167bec: fix (ai/core): forward streamText errors as error parts
- 0984f0b: feat (ai/core): add ToolExecutionError type
- Updated dependencies [0984f0b]
  - @ai-sdk/provider-utils@2.0.3
  - @ai-sdk/react@1.0.5
  - @ai-sdk/ui-utils@1.0.4

## 4.0.11

### Patch Changes

- Updated dependencies [953469c]
- Updated dependencies [a3dd2ed]
  - @ai-sdk/ui-utils@1.0.3
  - @ai-sdk/react@1.0.4

## 4.0.10

### Patch Changes

- 913872d: fix (ai/core): track promise from async createDataStream.execute

## 4.0.9

### Patch Changes

- fda9695: feat (ai/core): reworked data stream management

## 4.0.8

### Patch Changes

- a803d76: feat (ai/core): pass toolCallId option into tool execute function

## 4.0.7

### Patch Changes

- 5b4f07b: fix (ai/core): change default error message for data streams to "An error occurred."

## 4.0.6

### Patch Changes

- fc18132: feat (ai/core): experimental output for generateText
- 2779f6d: fix (ai/core): do not send maxRetries into providers

## 4.0.5

### Patch Changes

- Updated dependencies [630ac31]
  - @ai-sdk/react@1.0.3

## 4.0.4

### Patch Changes

- 6ff6689: fix (ai): trigger onFinal when stream adapter finishes
- 6ff6689: chore (ai): deprecate onCompletion (stream callbacks)

## 4.0.3

### Patch Changes

- Updated dependencies [88b364b]
- Updated dependencies [b446ae5]
  - @ai-sdk/ui-utils@1.0.2
  - @ai-sdk/provider@1.0.1
  - @ai-sdk/react@1.0.2
  - @ai-sdk/provider-utils@2.0.2

## 4.0.2

### Patch Changes

- Updated dependencies [c3ab5de]
  - @ai-sdk/provider-utils@2.0.1
  - @ai-sdk/react@1.0.1
  - @ai-sdk/ui-utils@1.0.1

## 4.0.1

### Patch Changes

- b117255: feat (ai/core): add messages to tool call options

## 4.0.0

### Major Changes

- 4e38b38: chore (ai): remove LanguageModelResponseMetadataWithHeaders type
- 8bf5756: chore: remove legacy function/tool calling
- f0cb69d: chore (ai/core): remove experimental function exports
- da8c609: chore (ai): remove Tokens RSC helper
- cbab571: chore (ai): remove ExperimentalXXXMessage types
- b469a7e: chore: remove isXXXError methods
- 54cb888: chore (ai): remove experimental_StreamData export
- 4d61295: chore (ai): remove streamToResponse and streamingTextResponse
- 9a3d741: chore (ai): remove ExperimentalTool export
- 064257d: chore (ai/core): rename simulateReadableStream values parameter to chunks
- 60e69ed: chore (ai/core): remove ai-stream related methods from streamText
- a4f8ce9: chore (ai): AssistantResponse cleanups
- d3ae4f6: chore (ui/react): remove useObject setInput helper
- 7264b0a: chore (ai): remove responseMessages property from streamText/generateText result
- b801982: chore (ai/core): remove init option from streamText result methods
- f68d7b1: chore (ai/core): streamObject returns result immediately (no Promise)
- 6090cea: chore (ai): remove rawResponse from generate/stream result objects
- 073f282: chore (ai): remove AIStream and related exports
- 1c58337: chore (ai): remove 2.x prompt helpers
- a40a93d: chore (ai/ui): remove vue, svelte, solid re-export and dependency
- a7ad35a: chore: remove legacy providers & rsc render
- c0ddc24: chore (ai): remove toJSON method from AI SDK errors
- 007cb81: chore (ai): change `streamText` warnings result to Promise
- effbce3: chore (ai): remove responseMessage from streamText onFinish callback
- 545d133: chore (ai): remove deprecated roundtrip settings from streamText / generateText
- 7e89ccb: chore: remove nanoid export
- f967199: chore (ai/core): streamText returns result immediately (no Promise)
- 62d08fd: chore (ai): remove TokenUsage, CompletionTokenUsage, and EmbeddingTokenUsage types
- e5d2ce8: chore (ai): remove deprecated provider registry exports
- 70ce742: chore (ai): remove experimental_continuationSteps option
- 2f09717: chore (ai): remove deprecated telemetry data
- 0827bf9: chore (ai): remove LangChain adapter `toAIStream` method

### Patch Changes

- dce4158: chore (dependencies): update eventsource-parser to 3.0.0
- f0ec721: chore (ai): remove openai peer dependency
- f9bb30c: chore (ai): remove unnecessary dev dependencies
- b053413: chore (ui): refactorings & README update
- Updated dependencies [e117b54]
- Updated dependencies [8bf5756]
- Updated dependencies [b469a7e]
- Updated dependencies [79c6dd9]
- Updated dependencies [9f81e66]
- Updated dependencies [70f28f6]
- Updated dependencies [dce4158]
- Updated dependencies [d3ae4f6]
- Updated dependencies [68d30e9]
- Updated dependencies [7814c4b]
- Updated dependencies [ca3e586]
- Updated dependencies [c0ddc24]
- Updated dependencies [fe4f109]
- Updated dependencies [84edae5]
- Updated dependencies [b1da952]
- Updated dependencies [04d3747]
- Updated dependencies [dce4158]
- Updated dependencies [7e89ccb]
- Updated dependencies [8426f55]
- Updated dependencies [db46ce5]
- Updated dependencies [b053413]
  - @ai-sdk/react@1.0.0
  - @ai-sdk/ui-utils@1.0.0
  - @ai-sdk/provider-utils@2.0.0
  - @ai-sdk/provider@1.0.0

## 4.0.0-canary.13

### Major Changes

- 064257d: chore (ai/core): rename simulateReadableStream values parameter to chunks

### Patch Changes

- Updated dependencies [79c6dd9]
- Updated dependencies [04d3747]
  - @ai-sdk/react@1.0.0-canary.9
  - @ai-sdk/ui-utils@1.0.0-canary.9

## 4.0.0-canary.12

### Patch Changes

- b053413: chore (ui): refactorings & README update
- Updated dependencies [b053413]
  - @ai-sdk/ui-utils@1.0.0-canary.8
  - @ai-sdk/react@1.0.0-canary.8

## 4.0.0-canary.11

### Major Changes

- f68d7b1: chore (ai/core): streamObject returns result immediately (no Promise)
- f967199: chore (ai/core): streamText returns result immediately (no Promise)

## 4.0.0-canary.10

### Major Changes

- effbce3: chore (ai): remove responseMessage from streamText onFinish callback

### Patch Changes

- Updated dependencies [fe4f109]
  - @ai-sdk/ui-utils@1.0.0-canary.7
  - @ai-sdk/react@1.0.0-canary.7

## 4.0.0-canary.9

### Patch Changes

- f0ec721: chore (ai): remove openai peer dependency

## 4.0.0-canary.8

### Major Changes

- 007cb81: chore (ai): change `streamText` warnings result to Promise

### Patch Changes

- Updated dependencies [70f28f6]
  - @ai-sdk/ui-utils@1.0.0-canary.6
  - @ai-sdk/react@1.0.0-canary.6

## 4.0.0-canary.7

### Major Changes

- 4e38b38: chore (ai): remove LanguageModelResponseMetadataWithHeaders type
- 54cb888: chore (ai): remove experimental_StreamData export
- 9a3d741: chore (ai): remove ExperimentalTool export
- a4f8ce9: chore (ai): AssistantResponse cleanups
- 7264b0a: chore (ai): remove responseMessages property from streamText/generateText result
- 62d08fd: chore (ai): remove TokenUsage, CompletionTokenUsage, and EmbeddingTokenUsage types
- e5d2ce8: chore (ai): remove deprecated provider registry exports
- 70ce742: chore (ai): remove experimental_continuationSteps option
- 0827bf9: chore (ai): remove LangChain adapter `toAIStream` method

## 4.0.0-canary.6

### Major Changes

- b801982: chore (ai/core): remove init option from streamText result methods

### Patch Changes

- f9bb30c: chore (ai): remove unnecessary dev dependencies

## 4.0.0-canary.5

### Major Changes

- 4d61295: chore (ai): remove streamToResponse and streamingTextResponse
- d3ae4f6: chore (ui/react): remove useObject setInput helper
- 6090cea: chore (ai): remove rawResponse from generate/stream result objects
- 2f09717: chore (ai): remove deprecated telemetry data

### Patch Changes

- Updated dependencies [9f81e66]
- Updated dependencies [d3ae4f6]
- Updated dependencies [8426f55]
  - @ai-sdk/ui-utils@1.0.0-canary.5
  - @ai-sdk/react@1.0.0-canary.5
  - @ai-sdk/provider-utils@2.0.0-canary.3

## 4.0.0-canary.4

### Major Changes

- f0cb69d: chore (ai/core): remove experimental function exports
- da8c609: chore (ai): remove Tokens RSC helper
- cbab571: chore (ai): remove ExperimentalXXXMessage types
- 60e69ed: chore (ai/core): remove ai-stream related methods from streamText
- 073f282: chore (ai): remove AIStream and related exports
- 545d133: chore (ai): remove deprecated roundtrip settings from streamText / generateText

### Patch Changes

- dce4158: chore (dependencies): update eventsource-parser to 3.0.0
- Updated dependencies [dce4158]
- Updated dependencies [ca3e586]
- Updated dependencies [dce4158]
  - @ai-sdk/provider-utils@2.0.0-canary.2
  - @ai-sdk/react@1.0.0-canary.4
  - @ai-sdk/ui-utils@1.0.0-canary.4

## 4.0.0-canary.3

### Patch Changes

- Updated dependencies [68d30e9]
- Updated dependencies [b1da952]
  - @ai-sdk/react@1.0.0-canary.3
  - @ai-sdk/provider-utils@2.0.0-canary.1
  - @ai-sdk/ui-utils@1.0.0-canary.3

## 4.0.0-canary.2

### Major Changes

- b469a7e: chore: remove isXXXError methods
- c0ddc24: chore (ai): remove toJSON method from AI SDK errors

### Patch Changes

- Updated dependencies [e117b54]
- Updated dependencies [b469a7e]
- Updated dependencies [7814c4b]
- Updated dependencies [c0ddc24]
- Updated dependencies [db46ce5]
  - @ai-sdk/react@1.0.0-canary.2
  - @ai-sdk/provider-utils@2.0.0-canary.0
  - @ai-sdk/provider@1.0.0-canary.0
  - @ai-sdk/ui-utils@1.0.0-canary.2

## 4.0.0-canary.1

### Major Changes

- 8bf5756: chore: remove legacy function/tool calling

### Patch Changes

- 1c58337: chore (ai): remove 2.x prompt helpers
- Updated dependencies [8bf5756]
  - @ai-sdk/ui-utils@1.0.0-canary.1
  - @ai-sdk/react@1.0.0-canary.1

## 4.0.0-canary.0

### Major Changes

- a40a93d: chore (ai/ui): remove vue, svelte, solid re-export and dependency

### Patch Changes

- a7ad35a: chore: remove legacy providers & rsc render
- 7e89ccb: chore: remove nanoid export
- Updated dependencies [84edae5]
- Updated dependencies [7e89ccb]
  - @ai-sdk/react@1.0.0-canary.0
  - @ai-sdk/ui-utils@1.0.0-canary.0

## 3.4.33

### Patch Changes

- ac380e3: fix (provider/anthropic): continuation mode with 3+ steps

## 3.4.32

### Patch Changes

- 6bb9e51: fix (ai/core): expose response.messages in streamText

## 3.4.31

### Patch Changes

- Updated dependencies [2dfb93e]
  - @ai-sdk/react@0.0.70

## 3.4.30

### Patch Changes

- Updated dependencies [a85c965]
  - @ai-sdk/ui-utils@0.0.50
  - @ai-sdk/react@0.0.69
  - @ai-sdk/solid@0.0.54
  - @ai-sdk/svelte@0.0.57
  - @ai-sdk/vue@0.0.59

## 3.4.29

### Patch Changes

- 54b56f7: feat (ai/core): send tool and tool choice telemetry data

## 3.4.28

### Patch Changes

- 29f1390: feat (ai/test): add simulateReadableStream helper

## 3.4.27

### Patch Changes

- fa772ae: feat (ai/core): automatically convert ui messages to core messages

## 3.4.26

### Patch Changes

- 57f39ea: feat (ai/core): support multi-modal tool results in convertToCoreMessages

## 3.4.25

### Patch Changes

- 6e0fa1c: fix (ai/core): wait for tool results to arrive before sending finish event

## 3.4.24

### Patch Changes

- d92fd9f: feat (ui/svelte): support Svelte 5 peer dependency
- Updated dependencies [d92fd9f]
  - @ai-sdk/svelte@0.0.56

## 3.4.23

### Patch Changes

- 8301e41: fix (ai/react): update React peer dependency version to allow rc releases.
- Updated dependencies [8301e41]
  - @ai-sdk/react@0.0.68

## 3.4.22

### Patch Changes

- Updated dependencies [3bf8da0]
  - @ai-sdk/ui-utils@0.0.49
  - @ai-sdk/react@0.0.67
  - @ai-sdk/solid@0.0.53
  - @ai-sdk/svelte@0.0.55
  - @ai-sdk/vue@0.0.58

## 3.4.21

### Patch Changes

- 3954471: (experimental) fix passing "experimental_toToolResultContent" into PoolResultPart

## 3.4.20

### Patch Changes

- aa98cdb: chore: more flexible dependency versioning
- 1486128: feat: add supportsUrl to language model specification
- 3b1b69a: feat: provider-defined tools
- 85b98da: revert fix (ai/core): handle tool calls without results in message conversion
- 7ceed77: feat (ai/core): expose response message for each step
- 811a317: feat (ai/core): multi-part tool results (incl. images)
- Updated dependencies [aa98cdb]
- Updated dependencies [1486128]
- Updated dependencies [7b937c5]
- Updated dependencies [3b1b69a]
- Updated dependencies [811a317]
  - @ai-sdk/provider-utils@1.0.22
  - @ai-sdk/provider@0.0.26
  - @ai-sdk/ui-utils@0.0.48
  - @ai-sdk/svelte@0.0.54
  - @ai-sdk/react@0.0.66
  - @ai-sdk/vue@0.0.57
  - @ai-sdk/solid@0.0.52

## 3.4.19

### Patch Changes

- b9b0d7b: feat (ai): access raw request body
- Updated dependencies [b9b0d7b]
  - @ai-sdk/provider@0.0.25
  - @ai-sdk/provider-utils@1.0.21
  - @ai-sdk/ui-utils@0.0.47
  - @ai-sdk/react@0.0.65
  - @ai-sdk/solid@0.0.51
  - @ai-sdk/svelte@0.0.53
  - @ai-sdk/vue@0.0.56

## 3.4.18

### Patch Changes

- 95c67b4: fix (ai/core): handle tool calls without results in message conversion

## 3.4.17

### Patch Changes

- e4ff512: fix (core): prevent unnecessary input/output serialization when telemetry is not enabled

## 3.4.16

### Patch Changes

- 01dcc44: feat (ai/core): add experimental activeTools option to generateText and streamText

## 3.4.15

### Patch Changes

- Updated dependencies [98a3b08]
  - @ai-sdk/react@0.0.64

## 3.4.14

### Patch Changes

- e930f40: feat (ai/core): expose core tool result and tool call types

## 3.4.13

### Patch Changes

- fc39158: fix (ai/core): add abortSignal to tool helper function

## 3.4.12

### Patch Changes

- a23da5b: feat (ai/core): forward abort signal to tools

## 3.4.11

### Patch Changes

- caedcda: feat (ai/ui): add setData helper to useChat
- Updated dependencies [caedcda]
  - @ai-sdk/svelte@0.0.52
  - @ai-sdk/react@0.0.63
  - @ai-sdk/solid@0.0.50
  - @ai-sdk/vue@0.0.55

## 3.4.10

### Patch Changes

- 0b557d7: feat (ai/core): add tracer option to telemetry settings
- 44f6bc5: feat (ai/core): expose StepResult type

## 3.4.9

### Patch Changes

- d347538: fix (ai/core): export FilePart interface

## 3.4.8

### Patch Changes

- Updated dependencies [b5f577e]
  - @ai-sdk/vue@0.0.54

## 3.4.7

### Patch Changes

- db04700: feat (core): support converting attachments to file parts
- 988707c: feat (ai/core): automatically download files from urls

## 3.4.6

### Patch Changes

- d595d0d: feat (ai/core): file content parts
- Updated dependencies [d595d0d]
  - @ai-sdk/provider@0.0.24
  - @ai-sdk/provider-utils@1.0.20
  - @ai-sdk/ui-utils@0.0.46
  - @ai-sdk/react@0.0.62
  - @ai-sdk/solid@0.0.49
  - @ai-sdk/svelte@0.0.51
  - @ai-sdk/vue@0.0.53

## 3.4.5

### Patch Changes

- cd77c5d: feat (ai/core): add isContinued to steps
- Updated dependencies [cd77c5d]
  - @ai-sdk/ui-utils@0.0.45
  - @ai-sdk/react@0.0.61
  - @ai-sdk/solid@0.0.48
  - @ai-sdk/svelte@0.0.50
  - @ai-sdk/vue@0.0.52

## 3.4.4

### Patch Changes

- 4db074b: fix (ai/core): correct whitespace in generateText continueSteps
- 1297e1b: fix (ai/core): correct whitespace in streamText continueSteps

## 3.4.3

### Patch Changes

- b270ae3: feat (ai/core): streamText continueSteps (experimental)
- b270ae3: chore (ai/core): rename generateText continuationSteps to continueSteps

## 3.4.2

### Patch Changes

- e6c7e98: feat (ai/core): add continuationSteps to generateText

## 3.4.1

### Patch Changes

- Updated dependencies [7e7104f]
  - @ai-sdk/react@0.0.60

## 3.4.0

### Minor Changes

- c0cea03: release (ai): 3.4

## 3.3.44

### Patch Changes

- Updated dependencies [d3933e0]
  - @ai-sdk/vue@0.0.51

## 3.3.43

### Patch Changes

- fea6bec: fix (ai/core): support tool calls without arguments

## 3.3.42

### Patch Changes

- de37aee: feat (ai): Add support for LlamaIndex

## 3.3.41

### Patch Changes

- Updated dependencies [692e265]
  - @ai-sdk/vue@0.0.50

## 3.3.40

### Patch Changes

- a91c308: feat (ai/core): add responseMessages to streamText

## 3.3.39

### Patch Changes

- 33cf3e1: feat (ai/core): add providerMetadata to StepResult
- 17ee757: feat (ai/core): add onStepFinish callback to generateText

## 3.3.38

### Patch Changes

- 83da52c: feat (ai/core): add onStepFinish callback to streamText

## 3.3.37

### Patch Changes

- Updated dependencies [273f696]
  - @ai-sdk/provider-utils@1.0.19
  - @ai-sdk/react@0.0.59
  - @ai-sdk/solid@0.0.47
  - @ai-sdk/svelte@0.0.49
  - @ai-sdk/ui-utils@0.0.44
  - @ai-sdk/vue@0.0.49

## 3.3.36

### Patch Changes

- a3882f5: feat (ai/core): add steps property to streamText result and onFinish callback
- 1f590ef: chore (ai): rename roundtrips to steps
- 7e82d36: fix (ai/core): pass topK to providers
- Updated dependencies [54862e4]
- Updated dependencies [1f590ef]
  - @ai-sdk/react@0.0.58
  - @ai-sdk/ui-utils@0.0.43
  - @ai-sdk/solid@0.0.46
  - @ai-sdk/svelte@0.0.48
  - @ai-sdk/vue@0.0.48

## 3.3.35

### Patch Changes

- 14210d5: feat (ai/core): add sendUsage information to streamText data stream methods
- Updated dependencies [14210d5]
  - @ai-sdk/ui-utils@0.0.42
  - @ai-sdk/react@0.0.57
  - @ai-sdk/solid@0.0.45
  - @ai-sdk/svelte@0.0.47
  - @ai-sdk/vue@0.0.47

## 3.3.34

### Patch Changes

- a0403d6: feat (react): support sending attachments using append
- 678449a: feat (ai/core): export test helpers
- ff22fac: fix (ai/rsc): streamUI onFinish is called when tool calls have finished
- Updated dependencies [a0403d6]
  - @ai-sdk/react@0.0.56

## 3.3.33

### Patch Changes

- cbddc83: fix (ai/core): filter out empty text parts

## 3.3.32

### Patch Changes

- ce7a4af: feat (ai/core): support providerMetadata in functions

## 3.3.31

### Patch Changes

- 561fd7e: feat (ai/core): add output: enum to generateObject

## 3.3.30

### Patch Changes

- 6ee1f8e: feat (ai/core): add toDataStream to streamText result

## 3.3.29

### Patch Changes

- 1e3dfd2: feat (ai/core): enhance pipeToData/TextStreamResponse methods

## 3.3.28

### Patch Changes

- db61c53: feat (ai/core): middleware support

## 3.3.27

### Patch Changes

- 03313cd: feat (ai): expose response id, response model, response timestamp in telemetry and api
- 3be7c1c: fix (provider/anthropic): support prompt caching on assistant messages
- Updated dependencies [03313cd]
- Updated dependencies [3be7c1c]
  - @ai-sdk/provider-utils@1.0.18
  - @ai-sdk/provider@0.0.23
  - @ai-sdk/react@0.0.55
  - @ai-sdk/solid@0.0.44
  - @ai-sdk/svelte@0.0.46
  - @ai-sdk/ui-utils@0.0.41
  - @ai-sdk/vue@0.0.46

## 3.3.26

### Patch Changes

- Updated dependencies [4ab883f]
  - @ai-sdk/react@0.0.54

## 3.3.25

### Patch Changes

- 4f1530f: feat (ai/core): add OpenTelemetry Semantic Conventions for GenAI operations to v1.27.0 of standard
- dad775f: feat (ai/core): add finish event and avg output tokens per second (telemetry)

## 3.3.24

### Patch Changes

- d87a655: fix (ai/core): provide fallback when globalThis.performance is not available

## 3.3.23

### Patch Changes

- b55e6f7: fix (ai/core): streamObject text stream in array mode must not include elements: prefix.

## 3.3.22

### Patch Changes

- a5a56fd: fix (ai/core): only send roundtrip-finish event after async tool calls are done

## 3.3.21

### Patch Changes

- aa2dc58: feat (ai/core): add maxToolRoundtrips to streamText
- Updated dependencies [aa2dc58]
  - @ai-sdk/ui-utils@0.0.40
  - @ai-sdk/react@0.0.53
  - @ai-sdk/solid@0.0.43
  - @ai-sdk/svelte@0.0.45
  - @ai-sdk/vue@0.0.45

## 3.3.20

### Patch Changes

- 7807677: fix (rsc): Deep clone currentState in getMutableState()

## 3.3.19

### Patch Changes

- 7235de0: fix (ai/core): convertToCoreMessages accepts Message[]

## 3.3.18

### Patch Changes

- 9e3b5a5: feat (ai/core): add experimental_customProvider
- 26515cb: feat (ai/provider): introduce ProviderV1 specification
- Updated dependencies [26515cb]
  - @ai-sdk/provider@0.0.22
  - @ai-sdk/provider-utils@1.0.17
  - @ai-sdk/ui-utils@0.0.39
  - @ai-sdk/react@0.0.52
  - @ai-sdk/solid@0.0.42
  - @ai-sdk/svelte@0.0.44
  - @ai-sdk/vue@0.0.44

## 3.3.17

### Patch Changes

- d151349: feat (ai/core): array output for generateObject / streamObject
- Updated dependencies [d151349]
  - @ai-sdk/ui-utils@0.0.38
  - @ai-sdk/react@0.0.51
  - @ai-sdk/solid@0.0.41
  - @ai-sdk/svelte@0.0.43
  - @ai-sdk/vue@0.0.43

## 3.3.16

### Patch Changes

- 09f895f: feat (ai/core): no-schema output for generateObject / streamObject
- Updated dependencies [09f895f]
  - @ai-sdk/provider-utils@1.0.16
  - @ai-sdk/react@0.0.50
  - @ai-sdk/solid@0.0.40
  - @ai-sdk/svelte@0.0.42
  - @ai-sdk/ui-utils@0.0.37
  - @ai-sdk/vue@0.0.42

## 3.3.15

### Patch Changes

- b5a82b7: chore (ai): update zod-to-json-schema to 3.23.2
- Updated dependencies [b5a82b7]
  - @ai-sdk/ui-utils@0.0.36
  - @ai-sdk/react@0.0.49
  - @ai-sdk/solid@0.0.39
  - @ai-sdk/svelte@0.0.41
  - @ai-sdk/vue@0.0.41

## 3.3.14

### Patch Changes

- Updated dependencies [d67fa9c]
  - @ai-sdk/provider-utils@1.0.15
  - @ai-sdk/react@0.0.48
  - @ai-sdk/solid@0.0.38
  - @ai-sdk/svelte@0.0.40
  - @ai-sdk/ui-utils@0.0.35
  - @ai-sdk/vue@0.0.40

## 3.3.13

### Patch Changes

- 412f943: fix (ai/core): make Buffer validation optional for environments without buffer

## 3.3.12

### Patch Changes

- f2c025e: feat (ai/core): prompt validation
- Updated dependencies [f2c025e]
  - @ai-sdk/provider@0.0.21
  - @ai-sdk/provider-utils@1.0.14
  - @ai-sdk/ui-utils@0.0.34
  - @ai-sdk/react@0.0.47
  - @ai-sdk/solid@0.0.37
  - @ai-sdk/svelte@0.0.39
  - @ai-sdk/vue@0.0.39

## 3.3.11

### Patch Changes

- 03eb0f4: feat (ai/core): add "ai.operationId" telemetry attribute
- 099db96: feat (ai/core): add msToFirstChunk telemetry data
- Updated dependencies [b6c1dee]
  - @ai-sdk/react@0.0.46

## 3.3.10

### Patch Changes

- Updated dependencies [04084a3]
  - @ai-sdk/vue@0.0.38

## 3.3.9

### Patch Changes

- 6ac355e: feat (provider/anthropic): add cache control support
- b56dee1: chore (ai): deprecate prompt helpers
- Updated dependencies [6ac355e]
  - @ai-sdk/provider@0.0.20
  - @ai-sdk/provider-utils@1.0.13
  - @ai-sdk/ui-utils@0.0.33
  - @ai-sdk/react@0.0.45
  - @ai-sdk/solid@0.0.36
  - @ai-sdk/svelte@0.0.38
  - @ai-sdk/vue@0.0.37

## 3.3.8

### Patch Changes

- Updated dependencies [dd712ac]
  - @ai-sdk/provider-utils@1.0.12
  - @ai-sdk/ui-utils@0.0.32
  - @ai-sdk/react@0.0.44
  - @ai-sdk/solid@0.0.35
  - @ai-sdk/svelte@0.0.37
  - @ai-sdk/vue@0.0.36

## 3.3.7

### Patch Changes

- eccbd8e: feat (ai/core): add onChunk callback to streamText
- Updated dependencies [dd4a0f5]
  - @ai-sdk/provider@0.0.19
  - @ai-sdk/provider-utils@1.0.11
  - @ai-sdk/ui-utils@0.0.31
  - @ai-sdk/react@0.0.43
  - @ai-sdk/solid@0.0.34
  - @ai-sdk/svelte@0.0.36
  - @ai-sdk/vue@0.0.35

## 3.3.6

### Patch Changes

- e9c891d: feat (ai/react): useObject supports non-Zod schemas
- 3719e8a: chore (ai/core): provider registry code improvements
- Updated dependencies [e9c891d]
- Updated dependencies [4bd27a9]
- Updated dependencies [845754b]
  - @ai-sdk/ui-utils@0.0.30
  - @ai-sdk/react@0.0.42
  - @ai-sdk/provider-utils@1.0.10
  - @ai-sdk/provider@0.0.18
  - @ai-sdk/solid@0.0.33
  - @ai-sdk/svelte@0.0.35
  - @ai-sdk/vue@0.0.34

## 3.3.5

### Patch Changes

- 9ada023: feat (ai/core): mask data stream error messages with streamText
- Updated dependencies [e5b58f3]
  - @ai-sdk/ui-utils@0.0.29
  - @ai-sdk/react@0.0.41
  - @ai-sdk/solid@0.0.32
  - @ai-sdk/svelte@0.0.34
  - @ai-sdk/vue@0.0.33

## 3.3.4

### Patch Changes

- 029af4c: feat (ai/core): support schema name & description in generateObject & streamObject
- 3806c0c: chore (ai/ui): increase stream data warning timeout to 15 seconds
- db0118a: feat (ai/core): export Schema type
- Updated dependencies [029af4c]
  - @ai-sdk/provider@0.0.17
  - @ai-sdk/provider-utils@1.0.9
  - @ai-sdk/ui-utils@0.0.28
  - @ai-sdk/react@0.0.40
  - @ai-sdk/solid@0.0.31
  - @ai-sdk/svelte@0.0.33
  - @ai-sdk/vue@0.0.32

## 3.3.3

### Patch Changes

- d58517b: feat (ai/openai): structured outputs
- Updated dependencies [d58517b]
  - @ai-sdk/provider@0.0.16
  - @ai-sdk/provider-utils@1.0.8
  - @ai-sdk/ui-utils@0.0.27
  - @ai-sdk/react@0.0.39
  - @ai-sdk/solid@0.0.30
  - @ai-sdk/svelte@0.0.32
  - @ai-sdk/vue@0.0.31

## 3.3.2

### Patch Changes

- Updated dependencies [96aed25]
  - @ai-sdk/provider@0.0.15
  - @ai-sdk/provider-utils@1.0.7
  - @ai-sdk/ui-utils@0.0.26
  - @ai-sdk/react@0.0.38
  - @ai-sdk/solid@0.0.29
  - @ai-sdk/svelte@0.0.31
  - @ai-sdk/vue@0.0.30

## 3.3.1

### Patch Changes

- 9614584: fix (ai/core): use Symbol.for
- 0762a22: feat (ai/core): support zod transformers in generateObject & streamObject
- Updated dependencies [9614584]
- Updated dependencies [0762a22]
  - @ai-sdk/provider-utils@1.0.6
  - @ai-sdk/react@0.0.37
  - @ai-sdk/solid@0.0.28
  - @ai-sdk/svelte@0.0.30
  - @ai-sdk/ui-utils@0.0.25
  - @ai-sdk/vue@0.0.29

## 3.3.0

### Minor Changes

- dbc3afb7: chore (ai): release AI SDK 3.3

### Patch Changes

- b9827186: feat (ai/core): update operation.name telemetry attribute to include function id and detailed name

## 3.2.45

### Patch Changes

- Updated dependencies [5be25124]
  - @ai-sdk/ui-utils@0.0.24
  - @ai-sdk/react@0.0.36
  - @ai-sdk/solid@0.0.27
  - @ai-sdk/svelte@0.0.29
  - @ai-sdk/vue@0.0.28

## 3.2.44

### Patch Changes

- Updated dependencies [a147d040]
  - @ai-sdk/react@0.0.35

## 3.2.43

### Patch Changes

- Updated dependencies [b68fae4f]
  - @ai-sdk/react@0.0.34

## 3.2.42

### Patch Changes

- f63c99e7: feat (ai/core): record OpenTelemetry gen_ai attributes
- Updated dependencies [fea7b604]
  - @ai-sdk/ui-utils@0.0.23
  - @ai-sdk/react@0.0.33
  - @ai-sdk/solid@0.0.26
  - @ai-sdk/svelte@0.0.28
  - @ai-sdk/vue@0.0.27

## 3.2.41

### Patch Changes

- a12044c7: feat (ai/core): add recordInputs / recordOutputs setting to telemetry options
- Updated dependencies [1d93d716]
  - @ai-sdk/ui-utils@0.0.22
  - @ai-sdk/react@0.0.32
  - @ai-sdk/solid@0.0.25
  - @ai-sdk/svelte@0.0.27
  - @ai-sdk/vue@0.0.26

## 3.2.40

### Patch Changes

- f56b7e66: feat (ai/ui): add toDataStreamResponse to LangchainAdapter.

## 3.2.39

### Patch Changes

- b694f2f9: feat (ai/svelte): add tool calling support to useChat
- Updated dependencies [b694f2f9]
  - @ai-sdk/svelte@0.0.26

## 3.2.38

### Patch Changes

- 5c4b8cfc: chore (ai/core): rename ai stream methods to data stream (in streamText, LangChainAdapter).
- c450fcf7: feat (ui): invoke useChat onFinish with finishReason and tokens
- e4a1719f: chore (ai/ui): rename streamMode to streamProtocol
- 10158bf2: fix (ai/core): generateObject.doGenerate sets object telemetry attribute
- Updated dependencies [c450fcf7]
- Updated dependencies [e4a1719f]
  - @ai-sdk/ui-utils@0.0.21
  - @ai-sdk/svelte@0.0.25
  - @ai-sdk/react@0.0.31
  - @ai-sdk/solid@0.0.24
  - @ai-sdk/vue@0.0.25

## 3.2.37

### Patch Changes

- b2bee4c5: fix (ai/ui): send data, body, headers in useChat().reload
- Updated dependencies [b2bee4c5]
  - @ai-sdk/svelte@0.0.24
  - @ai-sdk/react@0.0.30
  - @ai-sdk/solid@0.0.23

## 3.2.36

### Patch Changes

- a8d1c9e9: feat (ai/core): parallel image download
- cfa360a8: feat (ai/core): add telemetry support to embedMany function.
- 49808ca5: feat (ai/core): add telemetry to streamObject
- Updated dependencies [a8d1c9e9]
  - @ai-sdk/provider-utils@1.0.5
  - @ai-sdk/provider@0.0.14
  - @ai-sdk/react@0.0.29
  - @ai-sdk/svelte@0.0.23
  - @ai-sdk/ui-utils@0.0.20
  - @ai-sdk/vue@0.0.24
  - @ai-sdk/solid@0.0.22

## 3.2.35

### Patch Changes

- 1be014b7: feat (ai/core): add telemetry support for embed function.
- 4f88248f: feat (core): support json schema
- 0d545231: chore (ai/svelte): change sswr into optional peer dependency
- Updated dependencies [4f88248f]
  - @ai-sdk/provider-utils@1.0.4
  - @ai-sdk/react@0.0.28
  - @ai-sdk/svelte@0.0.22
  - @ai-sdk/ui-utils@0.0.19
  - @ai-sdk/vue@0.0.23
  - @ai-sdk/solid@0.0.21

## 3.2.34

### Patch Changes

- 2b9da0f0: feat (core): support stopSequences setting.
- a5b58845: feat (core): support topK setting
- 420f170f: chore (ai/core): use interfaces for core function results
- 13b27ec6: chore (ai/core): remove grammar mode
- 644f6582: feat (ai/core): add telemetry to generateObject
- Updated dependencies [2b9da0f0]
- Updated dependencies [a5b58845]
- Updated dependencies [4aa8deb3]
- Updated dependencies [13b27ec6]
  - @ai-sdk/provider@0.0.13
  - @ai-sdk/provider-utils@1.0.3
  - @ai-sdk/react@0.0.27
  - @ai-sdk/svelte@0.0.21
  - @ai-sdk/ui-utils@0.0.18
  - @ai-sdk/solid@0.0.20
  - @ai-sdk/vue@0.0.22

## 3.2.33

### Patch Changes

- 4b2c09d9: feat (ai/ui): add mutator function support to useChat / setMessages
- 281e7662: chore: add description to ai package
- Updated dependencies [f63829fe]
- Updated dependencies [4b2c09d9]
  - @ai-sdk/ui-utils@0.0.17
  - @ai-sdk/svelte@0.0.20
  - @ai-sdk/react@0.0.26
  - @ai-sdk/solid@0.0.19
  - @ai-sdk/vue@0.0.21

## 3.2.32

### Patch Changes

- Updated dependencies [5b7b3bbe]
  - @ai-sdk/ui-utils@0.0.16
  - @ai-sdk/react@0.0.25
  - @ai-sdk/solid@0.0.18
  - @ai-sdk/svelte@0.0.19
  - @ai-sdk/vue@0.0.20

## 3.2.31

### Patch Changes

- b86af092: feat (ai/core): add langchain stream event v2 support to LangChainAdapter

## 3.2.30

### Patch Changes

- Updated dependencies [19c3d50f]
  - @ai-sdk/react@0.0.24
  - @ai-sdk/vue@0.0.19

## 3.2.29

### Patch Changes

- e710b388: fix (ai/core): race condition in mergeStreams
- 6078a690: feat (ai/core): introduce stream data support in toAIStreamResponse

## 3.2.28

### Patch Changes

- 68d1f78c: fix (ai/core): do not construct object promise in streamObject result until requested
- f0bc1e79: feat (ai/ui): add system message support to convertToCoreMessages
- 1f67fe49: feat (ai/ui): stream tool calls with streamText and useChat
- Updated dependencies [1f67fe49]
  - @ai-sdk/ui-utils@0.0.15
  - @ai-sdk/react@0.0.23
  - @ai-sdk/solid@0.0.17
  - @ai-sdk/svelte@0.0.18
  - @ai-sdk/vue@0.0.18

## 3.2.27

### Patch Changes

- 811f4493: fix (ai/core): generateText token usage is sum over all roundtrips

## 3.2.26

### Patch Changes

- 8f545ce9: fix (ai/core): forward request headers in generateObject and streamObject

## 3.2.25

### Patch Changes

- 99ddbb74: feat (ai/react): add experimental support for managing attachments to useChat
- Updated dependencies [99ddbb74]
  - @ai-sdk/ui-utils@0.0.14
  - @ai-sdk/react@0.0.22
  - @ai-sdk/solid@0.0.16
  - @ai-sdk/svelte@0.0.17
  - @ai-sdk/vue@0.0.17

## 3.2.24

### Patch Changes

- f041c056: feat (ai/core): add roundtrips property to generateText result

## 3.2.23

### Patch Changes

- a6cb2c8b: feat (ai/ui): add keepLastMessageOnError option to useChat
- Updated dependencies [a6cb2c8b]
  - @ai-sdk/ui-utils@0.0.13
  - @ai-sdk/svelte@0.0.16
  - @ai-sdk/react@0.0.21
  - @ai-sdk/solid@0.0.15
  - @ai-sdk/vue@0.0.16

## 3.2.22

### Patch Changes

- 53fccf1c: fix (ai/core): report error on controller
- dd0d854e: feat (ai/vue): add useAssistant
- Updated dependencies [dd0d854e]
  - @ai-sdk/vue@0.0.15

## 3.2.21

### Patch Changes

- 56bbc2a7: feat (ai/ui): set body and headers directly on options for handleSubmit and append
- Updated dependencies [56bbc2a7]
  - @ai-sdk/ui-utils@0.0.12
  - @ai-sdk/svelte@0.0.15
  - @ai-sdk/react@0.0.20
  - @ai-sdk/solid@0.0.14
  - @ai-sdk/vue@0.0.14

## 3.2.20

### Patch Changes

- 671331b6: feat (core): add experimental OpenTelemetry support for generateText and streamText

## 3.2.19

### Patch Changes

- b7290943: chore (ai/core): rename TokenUsage type to CompletionTokenUsage
- b7290943: feat (ai/core): add token usage to embed and embedMany
- Updated dependencies [b7290943]
  - @ai-sdk/provider@0.0.12
  - @ai-sdk/provider-utils@1.0.2
  - @ai-sdk/react@0.0.19
  - @ai-sdk/svelte@0.0.14
  - @ai-sdk/ui-utils@0.0.11
  - @ai-sdk/solid@0.0.13
  - @ai-sdk/vue@0.0.13

## 3.2.18

### Patch Changes

- Updated dependencies [70d18003]
  - @ai-sdk/react@0.0.18

## 3.2.17

### Patch Changes

- 3db90c3d: allow empty handleSubmit submissions for useChat
- abb22602: feat (ai): verify that system messages have string content
- 5c1f0bd3: fix unclosed streamable value console message
- Updated dependencies [6a11cfaa]
- Updated dependencies [3db90c3d]
- Updated dependencies [d481729f]
  - @ai-sdk/react@0.0.17
  - @ai-sdk/svelte@0.0.13
  - @ai-sdk/solid@0.0.12
  - @ai-sdk/vue@0.0.12
  - @ai-sdk/provider-utils@1.0.1
  - @ai-sdk/ui-utils@0.0.10

## 3.2.16

### Patch Changes

- Updated dependencies [3f756a6b]
  - @ai-sdk/react@0.0.16

## 3.2.15

### Patch Changes

- 6c99581e: fix (ai/react): stop() on useObject does not throw error and clears isLoading
- Updated dependencies [6c99581e]
  - @ai-sdk/react@0.0.15

## 3.2.14

### Patch Changes

- Updated dependencies [9b50003d]
- Updated dependencies [1894f811]
  - @ai-sdk/react@0.0.14
  - @ai-sdk/ui-utils@0.0.9
  - @ai-sdk/solid@0.0.11
  - @ai-sdk/svelte@0.0.12
  - @ai-sdk/vue@0.0.11

## 3.2.13

### Patch Changes

- d3100b9c: feat (ai/ui): support custom fetch function in useChat, useCompletion, useAssistant, useObject
- Updated dependencies [d3100b9c]
  - @ai-sdk/ui-utils@0.0.8
  - @ai-sdk/svelte@0.0.11
  - @ai-sdk/react@0.0.13
  - @ai-sdk/solid@0.0.10
  - @ai-sdk/vue@0.0.10

## 3.2.12

### Patch Changes

- 5edc6110: feat (ai/core): add custom request header support
- Updated dependencies [5edc6110]
- Updated dependencies [5edc6110]
- Updated dependencies [5edc6110]
  - @ai-sdk/provider@0.0.11
  - @ai-sdk/provider-utils@1.0.0
  - @ai-sdk/react@0.0.12
  - @ai-sdk/svelte@0.0.10
  - @ai-sdk/ui-utils@0.0.7
  - @ai-sdk/solid@0.0.9
  - @ai-sdk/vue@0.0.9

## 3.2.11

### Patch Changes

- c908f741: chore (ui/solid): update solidjs useChat and useCompletion to feature parity with React
- 827ef450: feat (ai/ui): improve error handling in useAssistant
- Updated dependencies [c908f741]
- Updated dependencies [827ef450]
  - @ai-sdk/solid@0.0.8
  - @ai-sdk/svelte@0.0.9
  - @ai-sdk/react@0.0.11

## 3.2.10

### Patch Changes

- Updated dependencies [5b04204b]
- Updated dependencies [8f482903]
  - @ai-sdk/react@0.0.10

## 3.2.9

### Patch Changes

- 82d9c8de: feat (ai/ui): make event in useAssistant submitMessage optional
- Updated dependencies [82d9c8de]
- Updated dependencies [321a7d0e]
- Updated dependencies [82d9c8de]
  - @ai-sdk/svelte@0.0.8
  - @ai-sdk/react@0.0.9
  - @ai-sdk/vue@0.0.8

## 3.2.8

### Patch Changes

- 54bf4083: feat (ai/react): control request body in useChat
- Updated dependencies [54bf4083]
  - @ai-sdk/ui-utils@0.0.6
  - @ai-sdk/react@0.0.8
  - @ai-sdk/solid@0.0.7
  - @ai-sdk/svelte@0.0.7
  - @ai-sdk/vue@0.0.7

## 3.2.7

### Patch Changes

- d42b8907: feat (ui): make event in handleSubmit optional
- Updated dependencies [d42b8907]
  - @ai-sdk/svelte@0.0.6
  - @ai-sdk/react@0.0.7
  - @ai-sdk/solid@0.0.6
  - @ai-sdk/vue@0.0.6

## 3.2.6

### Patch Changes

- 74e28222: fix (ai/rsc): "could not find InternalStreamableUIClient" bug

## 3.2.5

### Patch Changes

- 4d426d0c: fix (ai): split provider and model ids correctly in the provider registry

## 3.2.4

### Patch Changes

- Updated dependencies [3cb103bc]
  - @ai-sdk/react@0.0.6

## 3.2.3

### Patch Changes

- 89b7552b: chore (ai): remove deprecation from ai/react imports, add experimental_useObject
- Updated dependencies [02f6a088]
  - @ai-sdk/provider-utils@0.0.16
  - @ai-sdk/react@0.0.5
  - @ai-sdk/svelte@0.0.5
  - @ai-sdk/ui-utils@0.0.5
  - @ai-sdk/solid@0.0.5
  - @ai-sdk/vue@0.0.5

## 3.2.2

### Patch Changes

- 0565cd72: feat (ai/core): add toJsonResponse to generateObject result.

## 3.2.1

### Patch Changes

- 008725ec: feat (ai): add textStream, toTextStreamResponse(), and pipeTextStreamToResponse() to streamObject
- 520fb2d5: feat (rsc): add streamUI onFinish callback
- Updated dependencies [008725ec]
- Updated dependencies [008725ec]
  - @ai-sdk/react@0.0.4
  - @ai-sdk/ui-utils@0.0.4
  - @ai-sdk/solid@0.0.4
  - @ai-sdk/svelte@0.0.4
  - @ai-sdk/vue@0.0.4

## 3.2.0

### Minor Changes

- 85ef6d18: chore (ai): AI SDK 3.2 release

### Patch Changes

- b965dd2d: fix (core): pass settings correctly for generateObject and streamObject

## 3.1.37

### Patch Changes

- 85712895: chore (@ai-sdk/provider-utils): move test helper to provider utils
- Updated dependencies [85712895]
- Updated dependencies [85712895]
  - @ai-sdk/provider-utils@0.0.15
  - @ai-sdk/react@0.0.3
  - @ai-sdk/svelte@0.0.3
  - @ai-sdk/ui-utils@0.0.3
  - @ai-sdk/solid@0.0.3
  - @ai-sdk/vue@0.0.3

## 3.1.36

### Patch Changes

- 4728c37f: feat (core): add text embedding model support to provider registry
- 8c49166e: chore (core): rename experimental_createModelRegistry to experimental_createProviderRegistry
- Updated dependencies [7910ae84]
  - @ai-sdk/provider-utils@0.0.14
  - @ai-sdk/react@0.0.2
  - @ai-sdk/svelte@0.0.2
  - @ai-sdk/ui-utils@0.0.2
  - @ai-sdk/solid@0.0.2
  - @ai-sdk/vue@0.0.2

## 3.1.35

### Patch Changes

- 06123501: feat (core): support https and data url strings in image parts

## 3.1.34

### Patch Changes

- d25566ac: feat (core): add cosineSimilarity helper function
- 87a5d27e: feat (core): introduce InvalidMessageRoleError.

## 3.1.33

### Patch Changes

- 6fb14b5d: chore (streams): deprecate nanoid export.
- 05536768: feat (core): add experimental model registry

## 3.1.32

### Patch Changes

- 3cabf078: fix(ai/rsc): Refactor streamable UI internal implementation

## 3.1.31

### Patch Changes

- 85f209a4: chore: extracted ui library support into separate modules
- 85f209a4: removed (streams): experimental_StreamingReactResponse was removed. Please use AI SDK RSC instead.
- Updated dependencies [85f209a4]
  - @ai-sdk/ui-utils@0.0.1
  - @ai-sdk/svelte@0.0.1
  - @ai-sdk/react@0.0.1
  - @ai-sdk/solid@0.0.1
  - @ai-sdk/vue@0.0.1

## 3.1.30

### Patch Changes

- fcf4323b: fix (core): filter out empty assistant text messages

## 3.1.29

### Patch Changes

- 28427d3e: feat (core): add streamObject onFinish callback

## 3.1.28

### Patch Changes

- 102ca22f: feat (core): add object promise to streamObject result
- Updated dependencies [102ca22f]
  - @ai-sdk/provider@0.0.10
  - @ai-sdk/provider-utils@0.0.13

## 3.1.27

### Patch Changes

- c9198d4d: feat (ui): send annotation and data fields in useChat when sendExtraMessageFields is true
- Updated dependencies [09295e2e]
- Updated dependencies [09295e2e]
- Updated dependencies [043a5de2]
  - @ai-sdk/provider@0.0.9
  - @ai-sdk/provider-utils@0.0.12

## 3.1.26

### Patch Changes

- 5ee44cae: feat (provider): langchain StringOutputParser support

## 3.1.25

### Patch Changes

- ff281126: fix(ai/rsc): Remove extra reconcilation of streamUI

## 3.1.24

### Patch Changes

- 93cae126: fix(ai/rsc): Fix unsafe {} type in application code for StreamableValue
- 08b5c509: feat (core): add tokenUsage to streamObject result

## 3.1.23

### Patch Changes

- c03cafe6: chore (core, ui): rename maxAutomaticRoundtrips to maxToolRoundtrips

## 3.1.22

### Patch Changes

- 14bb8694: chore (ui): move maxAutomaticRoundtrips and addToolResult out of experimental

## 3.1.21

### Patch Changes

- 213f2411: fix (core,streams): support ResponseInit variants
- 09698bca: chore (streams): deprecate streaming helpers that have a provider replacement

## 3.1.20

### Patch Changes

- 0e1da476: feat (core): add maxAutomaticRoundtrips setting to generateText

## 3.1.19

### Patch Changes

- 9882d24b: fix (ui/svelte): send data to server
- 131bbd3e: fix (ui): remove console.log statements

## 3.1.18

### Patch Changes

- f9dee8ac: fix(ai/rsc): Fix types for createStreamableValue and createStreamableUI
- 1c0ebf8e: feat (core): add responseMessages to generateText result

## 3.1.17

### Patch Changes

- 92b993b7: ai/rsc: improve getAIState and getMutableAIState types
- 7de628e9: chore (ui): deprecate old function/tool call handling
- 7de628e9: feat (ui): add onToolCall handler to useChat

## 3.1.16

### Patch Changes

- f39c0dd2: feat (core, rsc): add toolChoice setting
- Updated dependencies [f39c0dd2]
  - @ai-sdk/provider@0.0.8
  - @ai-sdk/provider-utils@0.0.11

## 3.1.15

### Patch Changes

- 8e780288: feat (ai/core): add onFinish callback to streamText
- 8e780288: feat (ai/core): add text, toolCalls, and toolResults promises to StreamTextResult (matching the generateText result API with async methods)
- Updated dependencies [8e780288]
  - @ai-sdk/provider@0.0.7
  - @ai-sdk/provider-utils@0.0.10

## 3.1.14

### Patch Changes

- 6109c6a: feat (ai/react): add experimental_maxAutomaticRoundtrips to useChat

## 3.1.13

### Patch Changes

- 60117c9: dependencies (ai/ui): add React 18.3 and 19 support (peer dependency)
- Updated dependencies [6a50ac4]
- Updated dependencies [6a50ac4]
  - @ai-sdk/provider@0.0.6
  - @ai-sdk/provider-utils@0.0.9

## 3.1.12

### Patch Changes

- ae05fb7: feat (ai/streams): add StreamData support to streamToResponse

## 3.1.11

### Patch Changes

- a085d42: fix (ai/ui): decouple StreamData chunks from LLM stream

## 3.1.10

### Patch Changes

- 3a21030: feat (ai/core): add embedMany function

## 3.1.9

### Patch Changes

- 18a9655: feat (ai/svelte): add useAssistant

## 3.1.8

### Patch Changes

- 0f6bc4e: feat (ai/core): add embed function
- Updated dependencies [0f6bc4e]
  - @ai-sdk/provider@0.0.5
  - @ai-sdk/provider-utils@0.0.8

## 3.1.7

### Patch Changes

- f617b97: feat (ai): support client/server tool calls with useChat and streamText

## 3.1.6

### Patch Changes

- 2e78acb: Deprecate StreamingReactResponse (use AI SDK RSC instead).
- 8439884: ai/rsc: make RSC streamable utils chainable
- 325ca55: feat (ai/core): improve image content part error message
- Updated dependencies [325ca55]
  - @ai-sdk/provider@0.0.4
  - @ai-sdk/provider-utils@0.0.7

## 3.1.5

### Patch Changes

- 5b01c13: feat (ai/core): add system message support in messages list

## 3.1.4

### Patch Changes

- ceb44bc: feat (ai/ui): add stop() helper to useAssistant (important: AssistantResponse now requires OpenAI SDK 4.42+)
- 37c9d4c: feat (ai/streams): add LangChainAdapter.toAIStream()

## 3.1.3

### Patch Changes

- 970a099: fix (ai/core): streamObject fixes partial json with empty objects correctly
- 1ac2390: feat (ai/core): add usage and finishReason to streamText result.
- Updated dependencies [276f22b]
  - @ai-sdk/provider-utils@0.0.6

## 3.1.2

### Patch Changes

- d1b1880: fix (ai/core): allow reading streams in streamText result multiple times

## 3.1.1

### Patch Changes

- 0f77132: ai/rsc: remove experimental\_ from streamUI

## 3.1.0

### Minor Changes

- 73356a9: Move AI Core functions out of experimental (streamText, generateText, streamObject, generateObject).

## 3.0.35

### Patch Changes

- 41d5736: ai/core: re-expose language model types.
- b4c68ec: ai/rsc: ReadableStream as provider for createStreamableValue; add .append() method
- Updated dependencies [41d5736]
  - @ai-sdk/provider@0.0.3
  - @ai-sdk/provider-utils@0.0.5

## 3.0.34

### Patch Changes

- b9a831e: ai/rsc: add experimental_streamUI()

## 3.0.33

### Patch Changes

- 56ef84a: ai/core: fix abort handling in transformation stream
- Updated dependencies [56ef84a]
  - @ai-sdk/provider-utils@0.0.4

## 3.0.32

### Patch Changes

- 0e0d2af: ai/core: add pipeTextStreamToResponse helper to streamText.

## 3.0.31

### Patch Changes

- 74c63b1: ai/core: add toAIStreamResponse() helper to streamText.

## 3.0.30

### Patch Changes

- e7e5898: use-assistant: fix missing message content

## 3.0.29

### Patch Changes

- 22a737e: Fix: mark useAssistant as in progress for append/submitMessage.

## 3.0.28

### Patch Changes

- d6431ae: ai/core: add logprobs support (thanks @SamStenner for the contribution)
- 25f3350: ai/core: add support for getting raw response headers.
- Updated dependencies [d6431ae]
- Updated dependencies [25f3350]
  - @ai-sdk/provider@0.0.2
  - @ai-sdk/provider-utils@0.0.3

## 3.0.27

### Patch Changes

- eb150a6: ai/core: remove scaling of setting values (breaking change). If you were using the temperature, frequency penalty, or presence penalty settings, you need to update the providers and adjust the setting values.
- Updated dependencies [eb150a6]
  - @ai-sdk/provider-utils@0.0.2
  - @ai-sdk/provider@0.0.1

## 3.0.26

### Patch Changes

- f90f6a1: ai/core: add pipeAIStreamToResponse() to streamText result.

## 3.0.25

### Patch Changes

- 1e84d6d: Fix: remove mistral lib type dependency.
- 9c2a049: Add append() helper to useAssistant.

## 3.0.24

### Patch Changes

- e94fb32: feat(ai/rsc): Make `onSetAIState` and `onGetUIState` stable

## 3.0.23

### Patch Changes

- 66b5892: Add streamMode parameter to useChat and useCompletion.
- Updated dependencies [7b8791d]
  - @ai-sdk/provider-utils@0.0.1

## 3.0.22

### Patch Changes

- d544886: Breaking change: extract experimental AI core provider packages. They can now be imported with e.g. import { openai } from '@ai-sdk/openai' after adding them to a project.
- ea6b0e1: Expose formatStreamPart, parseStreamPart, and readDataStream helpers.

## 3.0.21

### Patch Changes

- 87d3db5: Extracted @ai-sdk/provider package
- 8c40f8c: ai/core: Fix openai provider streamObject for gpt-4-turbo
- 5cd29bd: ai/core: add toTextStreamResponse() method to streamText result

## 3.0.20

### Patch Changes

- f42bbb5: Remove experimental from useAssistant and AssistantResponse.
- 149fe26: Deprecate <Tokens/>
- 2eb4b55: Remove experimental\_ prefix from StreamData.
- e45fa96: Add stream support for Bedrock/Cohere.
- a6b2500: Deprecated the `experimental_streamData: true` setting from AIStreamCallbacksAndOptions. You can delete occurrences in your code. The stream data protocol is now used by default.

## 3.0.19

### Patch Changes

- 4f4c7f5: ai/core: Anthropic tool call support

## 3.0.18

### Patch Changes

- 63d587e: Add Anthropic provider for ai/core functions (no tool calling).
- 63d587e: Add automatic mime type detection for images in ai/core prompts.

## 3.0.17

### Patch Changes

- 2b991c4: Add Google Generative AI provider for ai/core functions.

## 3.0.16

### Patch Changes

- a54ea77: feat(ai/rsc): add `useStreamableValue`

## 3.0.15

### Patch Changes

- 4aed2a5: Add JSDoc comments for ai/core functions.
- cf8d12f: Export experimental language model specification under `ai/spec`.

## 3.0.14

### Patch Changes

- 8088de8: fix(ai/rsc): improve typings for `StreamableValue`
- 20007b9: feat(ai/rsc): support string diff and patch in streamable value
- 6039460: Support Bedrock Anthropic Stream for Messages API.
- e83bfe3: Added experimental ai/core functions (streamText, generateText, streamObject, generateObject). Add OpenAI and Mistral language model providers.

## 3.0.13

### Patch Changes

- 026d061: Expose setMessages in useAssistant hook
- 42209be: AssistantResponse: specify forwardStream return type.

## 3.0.12

### Patch Changes

- b99b008: fix(ai/rsc): avoid appending boundary if the same reference was passed

## 3.0.11

### Patch Changes

- ce009e2: Added OpenAI assistants streaming.
- 3f9bf3e: Updates types to OpenAI SDK 4.29.0

## 3.0.10

### Patch Changes

- 33d261a: fix(ai/rsc): Fix .append() behavior

## 3.0.9

### Patch Changes

- 81ca3d6: fix(ai/rsc): improve .done() argument type

## 3.0.8

### Patch Changes

- a94aab2: ai/rsc: optimize streamable value stream size

## 3.0.7

### Patch Changes

- 9a9ae73: feat(ai/rsc): readStreamableValue

## 3.0.6

### Patch Changes

- 1355ad0: Fix: experimental_onToolCall is called with parsed tool args
- 9348f06: ai/rsc: improve dev error and warnings by trying to detect hanging streams
- 8be9404: fix type resolution

## 3.0.5

### Patch Changes

- a973f1e: Support Anthropic SDK v0.15.0
- e25f3ca: type improvements

## 3.0.4

### Patch Changes

- 7962862: fix `useActions` type inference
- aab5324: Revert "fix(render): parse the args based on the zod schema"
- fe55612: Bump OpenAI dependency to 4.28.4; fix type error in render

## 3.0.3

### Patch Changes

- 4d816ca: fix(render): parse the args based on the zod schema
- d158a47: fix potential race conditions

## 3.0.2

### Patch Changes

- 73bd06e: fix(useActions): return typed object

## 3.0.1

### Patch Changes

- ac20a25: ai/rsc: fix text response and async generator
- b88778f: Added onText callback for text tokens.

## 3.0.0

### Major Changes

- 51054a9: add ai/rsc

## 2.2.37

### Patch Changes

- a6b5764: Add support for Mistral's JavaScript SDK

## 2.2.36

### Patch Changes

- 141f0ce: Fix: onFinal callback is invoked with text from onToolCall when onToolCall returns string

## 2.2.35

### Patch Changes

- b717dad: Adding Inkeep as a stream provider

## 2.2.34

### Patch Changes

- 2c8ffdb: cohere-stream: support AsyncIterable
- ed1e278: Message annotations handling for all Message types

## 2.2.33

### Patch Changes

- 8542ae7: react/use-assistant: add onError handler
- 97039ff: OpenAIStream: Add support for the Azure OpenAI client library

## 2.2.32

### Patch Changes

- 7851fa0: StreamData: add `annotations` and `appendMessageAnnotation` support

## 2.2.31

### Patch Changes

- 9b89c4d: react/use-assistant: Expose setInput
- 75751c9: ai/react: Add experimental_onToolCall to useChat.

## 2.2.30

### Patch Changes

- ac503e0: ai/solid: add chat request options to useChat
- b78a73e: Add GoogleGenerativeAIStream for Gemini support
- 5220336: ai/svelte: Add experimental_onToolCall to useChat.
- ef99062: Add support for the Anthropic message API
- 5220336: Add experimental_onToolCall to OpenAIStream.
- ac503e0: ai/vue: add chat request options to useChat

## 2.2.29

### Patch Changes

- 5a9ae2e: ai/prompt: add `experimental_buildOpenAIMessages` to validate and cast AI SDK messages to OpenAI messages

## 2.2.28

### Patch Changes

- 07a679c: Add data message support to useAssistant & assistantResponse.
- fbae595: ai/react: `api` functions are no longer used as a cache key in `useChat`

## 2.2.27

### Patch Changes

- 0fd1205: ai/vue: Add complex response parsing and StreamData support to useCompletion
- a7dc746: experimental_useAssistant: Expose extra fetch options
- 3dcf01e: ai/react Add data support to useCompletion
- 0c3b338: ai/svelte: Add complex response parsing and StreamData support to useCompletion
- 8284777: ai/solid: Add complex response parsing and StreamData support to useCompletion

## 2.2.26

### Patch Changes

- df1ad33: ai/vue: Add complex response parsing and StreamData support to useChat
- 3ff8a56: Add `generateId` to use-chat params to allow overriding message ID generation
- 6c2a49c: ai/react experimental_useAssistant() submit can be called without an event
- 8b4f7d1: ai/react: Add complex response parsing and StreamData support to useCompletion

## 2.2.25

### Patch Changes

- 1e61c69: chore: specify the minimum react version to 18
- 6aec2d2: Expose threadId in useAssistant
- c2369df: Add AWS Bedrock support
- 223fde3: ai/svelte: Add complex response parsing and StreamData support to useChat

## 2.2.24

### Patch Changes

- 69ca8f5: ai/react: add experimental_useAssistant hook and experimental_AssistantResponse
- 3e2299e: experimental_StreamData/StreamingReactResponse: optimize parsing, improve types
- 70bd2ac: ai/solid: add experimental_StreamData support to useChat

## 2.2.23

### Patch Changes

- 5a04321: add StreamData support to StreamingReactResponse, add client-side data API to react/use-chat

## 2.2.22

### Patch Changes

- 4529831: ai/react: Do not store initialMessages in useState
- db5378c: experimental_StreamData: fix data type to be JSONValue

## 2.2.21

### Patch Changes

- 2c8d4bd: Support openai@4.16.0 and later

## 2.2.20

### Patch Changes

- 424d5ee: experimental_StreamData: fix trailing newline parsing bug in decoder
- c364c6a: cohere: fix closing cohere stream, avoids response from hanging

## 2.2.19

### Patch Changes

- 699552d: add experimental_StreamingReactResponse

## 2.2.18

### Patch Changes

- 0bd27f6: react/use-chat: allow client-side handling of function call without following response

## 2.2.17

### Patch Changes

- 5ed581d: Use interface instead of type for Message to allow declaration merging
- 9adec1e: vue and solid: fix including `function_call` and `name` fields in subsequent requests

## 2.2.16

### Patch Changes

- e569688: Fix for #637, resync interfaces

## 2.2.15

### Patch Changes

- c5d1857: fix: return complete response in onFinish when onCompletion isn't passed
- c5d1857: replicate-stream: fix types for replicate@0.20.0+

## 2.2.14

### Patch Changes

- 6229d6b: openai: fix OpenAIStream types with openai@4.11+

## 2.2.13

### Patch Changes

- a4a997f: all providers: reset error message on (re)submission

## 2.2.12

### Patch Changes

- cb181b4: ai/vue: wrap body with unref to support reactivity

## 2.2.11

### Patch Changes

- 2470658: ai/react: fix: handle partial chunks in react getStreamedResponse when using experimental_StreamData

## 2.2.10

### Patch Changes

- 8a2cbaf: vue/use-completion: fix: don't send network request for loading state"
- bbf4403: langchain-stream: return langchain `writer` from LangChainStream

## 2.2.9

### Patch Changes

- 3fc2b32: ai/vue: fix: make body parameter reactive

## 2.2.8

### Patch Changes

- 26bf998: ai/react: make reload/complete/append functions stable via useCallback

## 2.2.7

### Patch Changes

- 2f97630: react/use-chat: fix aborting clientside function calls too early
- 1157340: fix: infinite loop for experimental stream data (#484)

## 2.2.6

### Patch Changes

- e5bf68d: react/use-chat: fix experimental functions returning proper function messages

  Closes #478

## 2.2.5

### Patch Changes

- e5bf68d: react/use-chat: fix experimental functions returning proper function messages

  Closes #478

## 2.2.4

### Patch Changes

- 7b389a7: fix: improve safety for type check in openai-stream

## 2.2.3

### Patch Changes

- 867a3f9: Fix client-side function calling (#467, #469)

  add Completion type from the `openai` SDK to openai-stream (#472)

## 2.2.2

### Patch Changes

- 84e0cc8: Add experimental_StreamData and new opt-in wire protocol to enable streaming additional data. See https://github.com/vercel/ai/pull/425.

  Changes `onCompletion` back to run every completion, including recursive function calls. Adds an `onFinish` callback that runs once everything has streamed.

  If you're using experimental function handlers on the server _and_ caching via `onCompletion`,
  you may want to adjust your caching code to account for recursive calls so the same key isn't used.

  ```
  let depth = 0

  const stream = OpenAIStream(response, {
      async onCompletion(completion) {
        depth++
        await kv.set(key + '_' + depth, completion)
        await kv.expire(key + '_' + depth, 60 * 60)
      }
    })
  ```

## 2.2.1

### Patch Changes

- 04084a8: openai-stream: fix experimental_onFunctionCall types for OpenAI SDK v4

## 2.2.0

### Minor Changes

- dca1ed9: Update packages and examples to use OpenAI SDK v4

## 2.1.34

### Patch Changes

- c2917d3: Add support for the Anthropic SDK, newer Anthropic API versions, and improve Anthropic error handling

## 2.1.33

### Patch Changes

- 4ef8015: Prevent `isLoading` in vue integration from triggering extraneous network requests

## 2.1.32

### Patch Changes

- 5f91427: ai/svelte: fix isLoading return value

## 2.1.31

### Patch Changes

- ab2b973: fix pnpm-lock.yaml

## 2.1.30

### Patch Changes

- 4df2a49: Fix termination of ReplicateStream by removing the terminating `{}`from output

## 2.1.29

### Patch Changes

- 3929a41: Add ReplicateStream helper

## 2.1.28

### Patch Changes

- 9012e17: react/svelte/vue: fix making unnecessary SWR request to API endpoint

## 2.1.27

### Patch Changes

- 3d29799: React/Svelte/Vue: keep isLoading in sync between hooks with the same ID.

  React: don't throw error when submitting

## 2.1.26

### Patch Changes

- f50d9ef: Add experimental_buildLlama2Prompt helper for Hugging Face

## 2.1.25

### Patch Changes

- 877c16f: ai/react: don't throw error if onError is passed

## 2.1.24

### Patch Changes

- f3f5866: Adds SolidJS support and SolidStart example

## 2.1.23

### Patch Changes

- 0ebc2f0: streams/openai-stream: don't call onStart/onCompletion when recursing

## 2.1.22

### Patch Changes

- 9320e95: Add (experimental) prompt construction helpers for StarChat and OpenAssistant
- e3a7ec8: Support <|end|> token for StarChat beta in huggingface-stream

## 2.1.21

### Patch Changes

- 561a49a: Providing a function to `function_call` request parameter of the OpenAI Chat Completions API no longer breaks OpenAI function stream parsing.

## 2.1.20

### Patch Changes

- e361114: OpenAI functions: allow returning string in callback

## 2.1.19

### Patch Changes

- e4281ca: Add experimental server-side OpenAI function handling

## 2.1.18

### Patch Changes

- 6648b21: Add experimental client side OpenAI function calling to Svelte bindings
- e5b983f: feat(streams): add http error handling for openai

## 2.1.17

### Patch Changes

- 3ed65bf: Remove dependency on node crypto API

## 2.1.16

### Patch Changes

- 8bfb43d: Fix svelte peer dependency version

## 2.1.15

### Patch Changes

- 4a2b978: Update cohere stream and add docs

## 2.1.14

### Patch Changes

- 3164adb: Fix regression with generated ids

## 2.1.13

### Patch Changes

- fd82961: Use rfc4122 IDs when generating chat/completion IDs

## 2.1.12

### Patch Changes

- b7b93e5: Add <Tokens> RSC to ai/react

## 2.1.11

### Patch Changes

- 8bf637a: Fix langchain handlers so that they now are correctly invoked and update examples and docs to show correct usage (passing the handlers to `llm.call` and not the model itself).

## 2.1.10

### Patch Changes

- a7b3d0e: Experimental support for OpenAI function calling

## 2.1.9

### Patch Changes

- 9cdf968: core/react: add Tokens react server component

## 2.1.8

### Patch Changes

- 44d9879: Support extra request options in chat and completion hooks

## 2.1.7

### Patch Changes

- bde3898: Allow an async onResponse callback in useChat/useCompletion

## 2.1.6

### Patch Changes

- 23f0899: Set stream: true when decoding streamed chunks

## 2.1.5

### Patch Changes

- 89938b0: Provider direct callback handlers in LangChain now that `CallbackManager` is deprecated.

## 2.1.4

### Patch Changes

- c16d650: Improve type saftey for AIStream. Added JSDoc comments.

## 2.1.3

### Patch Changes

- a9591fe: Add `createdAt` on `user` input message in `useChat` (it was already present in `assistant` messages)

## 2.1.2

### Patch Changes

- f37d4ec: fix bundling

## 2.1.1

### Patch Changes

- 9fdb51a: fix: add better typing for store within svelte implementation (#104)

## 2.1.0

### Minor Changes

- 71f9c51: This adds Vue support for `ai` via the `ai/vue` subpath export. Vue composables `useChat` and `useCompletion` are provided.

### Patch Changes

- ad54c79: add tests

## 2.0.1

### Patch Changes

- be90740: - Switches `LangChainStream` helper callback `handler` to return use `handleChainEnd` instead of `handleLLMEnd` so as to work with sequential chains

## 2.0.0

### Major Changes

- 095de43: New package name!

## 0.0.14

### Patch Changes

- c6586a2: Add onError callback, include response text in error if response is not okay

## 0.0.13

### Patch Changes

- c1f4a91: Throw error when provided AI response isn't valid

## 0.0.12

### Patch Changes

- ea4e66a: improve API types

## 0.0.11

### Patch Changes

- a6bc35c: fix package exports for react and svelte subpackages

## 0.0.10

### Patch Changes

- 56f9537: add svelte apis

## 0.0.9

### Patch Changes

- 78477d3: - Create `/react` sub-package.
  - Create `import { useChat, useCompletion } from 'ai/react'` and mark React as an optional peer dependency so we can add more framework support in the future.
  - Also renamed `set` to `setMessages` and `setCompletion` to unify the API naming as we have `setInput` too.
  - Added an `sendExtraMessageFields` field to `useChat` that defaults to `false`, to prevent OpenAI errors when `id` is not filtered out.
- c4c1be3: useCompletion.handleSubmit does not clear the input anymore
- 7de2185: create /react export

## 0.0.8

### Patch Changes

- fc83e95: Implement new start-of-stream newline trimming
- 2c6fa04: Optimize callbacks TransformStream to be more memory efficient when `onCompletion` is not specified

## 0.0.7

### Patch Changes

- fdfef52: - Splits the `EventSource` parser into a reusable helper
  - Uses a `TransformStream` for this, so the stream respects back-pressure
  - Splits the "forking" stream for callbacks into a reusable helper
  - Changes the signature for `customParser` to avoid Stringify -> Encode -> Decode -> Parse round trip
  - Uses ?.() optional call syntax for callbacks
  - Uses string.includes to perform newline checking
  - Handles the `null` `res.body` case
  - Fixes Anthropic's streaming responses
    - Anthropic returns cumulative responses, not deltas like OpenAI
    - https://github.com/hwchase17/langchain/blob/3af36943/langchain/llms/anthropic.py#L190-L193

## 0.0.6

### Patch Changes

- d70a9e7: Add streamToResponse
- 47b85b2: Improve abortController and callbacks of `useChat`
- 6f7b43a: Export `UseCompletionHelpers` as a TypeScript type alias

## 0.0.5

### Patch Changes

- 4405a8a: fix duplicated `'use client'` directives

## 0.0.4

### Patch Changes

- b869104: Added `LangChainStream`, `useCompletion`, and `useChat`

## 0.0.3

### Patch Changes

- 677d222: add useCompletion

## 0.0.2

### Patch Changes

- af400e2: Fix release script

## 0.0.1

### Patch Changes

- b7e227d: Add `useChat` hook

## 0.0.2

### Patch Changes

- 9a8a845: Testing out release
