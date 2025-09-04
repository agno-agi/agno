# @ai-sdk/provider

## 2.0.0

### Major Changes

- 742b7be: feat: forward id, streaming start, streaming end of content blocks
- 7cddb72: refactoring (provider): collapse provider defined tools into single definition
- ccce59b: feat (provider): support changing provider, model, supportedUrls in middleware
- e2b9e4b: feat (provider): add name for provider defined tools for future validation
- 95857aa: chore: restructure language model supported urls
- 6f6bb89: chore (provider): cleanup request and rawRequest (language model v2)
- d1a1aa1: chore (provider): merge rawRequest into request (language model v2)
- 63f9e9b: chore (provider,ai): tools have input/output instead of args,result
- d5f588f: AI SDK 5
- b6b43c7: chore: move warnings into stream-start part (spec)
- 411e483: chore (provider): refactor usage (language model v2)
- abf9a79: chore: rename mimeType to mediaType
- 14c9410: chore: refactor file towards source pattern (spec)
- e86be6f: chore: remove logprobs
- 0d06df6: chore (ai): remove v1 providers
- d9c98f4: chore: refactor reasoning parts (spec)
- a3f768e: chore: restructure reasoning support
- 7435eb5: feat: upgrade speech models to v2 specification
- 0054544: chore: refactor source parts (spec)
- 9e9c809: chore: refactor tool call and tool call delta parts (spec)
- 32831c6: chore: refactor text parts (spec)
- 6dc848c: chore (provider): remove image parts
- d0f9495: chore: refactor file parts (spec)
- 7979f7f: feat (provider): support reasoning tokens, cached input tokens, total token in usage information
- 44f4aba: feat: upgrade transcription models to v2 specification
- 7ea4132: chore: remove object generation mode
- 023ba40: feat (provider): support arbitrary media types in tool results
- e030615: chore (provider): remove prompt type from language model v2 spec
- 5e57fae: refactoring (provider): restructure tool result output
- c57e248: chore (provider): remove mode
- 3795467: chore: return content array from doGenerate (spec)
- 1766ede: chore: rename maxTokens to maxOutputTokens
- 33f4a6a: chore (provider): rename providerMetadata inputs to providerOptions

### Patch Changes

- dc714f3: release alpha.4
- b5da06a: update to LanguageModelV2ProviderDefinedClientTool to add server side tool later on
- 48d257a: release alpha.15
- 0d2c085: chore (provider): tweak provider definition
- 9222aeb: release alpha.8
- e2aceaf: feat: add raw chunk support
- 7b3ae3f: chore (provider): change getSupportedUrls to supportedUrls (language model v2)
- a166433: feat: add transcription with experimental_transcribe
- 26735b5: chore(embedding-model): add v2 interface
- 443d8ec: feat(embedding-model-v2): add response body field
- a8c8bd5: feat(embed-many): respect supportsParallelCalls & concurrency
- 9bf7291: chore(providers/openai): enable structuredOutputs by default & switch to provider option
- 2e13791: feat(anthropic): add server-side web search support
- 472524a: spec (ai): add provider options to tools
- dd3ff01: chore: add language setting to speechv2
- 9301f86: refactor (image-model): rename `ImageModelV1` to `ImageModelV2`
- 0a87932: core (ai): change transcription model mimeType to mediaType
- c4a2fec: chore (provider): extract shared provider options and metadata (spec)
- 79457bd: chore (provider): extract LanguageModelV2File
- 8aa9e20: feat: add speech with experimental_generateSpeech
- 4617fab: chore(embedding-models): remove remaining settings
- cb68df0: feat: add transcription and speech model support to provider registry
- ad80501: chore (provider): allow both binary and base64 file content (spec)

  Before

  ```ts
  import { convertUint8ArrayToBase64 } from '@ai-sdk/provider-utils';

  // Had to manually convert binary data to base64
  const fileData = new Uint8Array([0, 1, 2, 3]);
  const filePart = {
    type: 'file',
    mediaType: 'application/pdf',
    data: convertUint8ArrayToBase64(fileData), // Required conversion
  };
  ```

  After

  ```ts
  // Can use binary data directly
  const fileData = new Uint8Array([0, 1, 2, 3]);
  const filePart = {
    type: 'file',
    mediaType: 'application/pdf',
    data: fileData, // Direct Uint8Array support
  };
  ```

- 68ecf2f: release alpha.13
- 6b98118: release alpha.3
- 3f2f00c: feat: `ImageModelV2#maxImagesPerCall` can be set to a function that returns a `number` or `undefined`, optionally as a promise

  pull request: https://github.com/vercel/ai/pull/6343

- 9bd5ab5: feat (provider): add providerMetadata to ImageModelV2 interface (#5977)

  The `experimental_generateImage` method from the `ai` package now returnes revised prompts for OpenAI's image models.

  ```js
  const prompt = 'Santa Claus driving a Cadillac';

  const { providerMetadata } = await experimental_generateImage({
    model: openai.image('dall-e-3'),
    prompt,
  });

  const revisedPrompt = providerMetadata.openai.images[0]?.revisedPrompt;

  console.log({
    prompt,
    revisedPrompt,
  });
  ```

- 5c56081: release alpha.7
- fd65bc6: chore(embedding-model-v2): rename rawResponse to response
- 26535e0: release alpha.2
- 393138b: feat(embedding-model-v2): add providerOptions
- 7182d14: Remove `Experimental_LanguageModelV2Middleware` type
- c1e6647: release alpha.11
- 811dff3: release alpha.9
- f10304b: feat(tool-calling): don't require the user to have to pass parameters
- 27deb4d: feat (provider/gateway): Add providerMetadata to embeddings response
- c4df419: release alpha.10

## 2.0.0-beta.2

### Patch Changes

- 27deb4d: feat (provider/gateway): Add providerMetadata to embeddings response

## 2.0.0-beta.1

### Major Changes

- 742b7be: feat: forward id, streaming start, streaming end of content blocks
- 7cddb72: refactoring (provider): collapse provider defined tools into single definition
- ccce59b: feat (provider): support changing provider, model, supportedUrls in middleware
- e2b9e4b: feat (provider): add name for provider defined tools for future validation
- 0d06df6: chore (ai): remove v1 providers
- 7435eb5: feat: upgrade speech models to v2 specification
- 44f4aba: feat: upgrade transcription models to v2 specification
- 023ba40: feat (provider): support arbitrary media types in tool results
- 5e57fae: refactoring (provider): restructure tool result output

### Patch Changes

- 472524a: spec (ai): add provider options to tools
- dd3ff01: chore: add language setting to speechv2
- cb68df0: feat: add transcription and speech model support to provider registry

## 2.0.0-alpha.15

### Patch Changes

- 48d257a: release alpha.15

## 2.0.0-alpha.14

### Major Changes

- 63f9e9b: chore (provider,ai): tools have input/output instead of args,result

### Patch Changes

- b5da06a: update to LanguageModelV2ProviderDefinedClientTool to add server side tool later on
- 2e13791: feat(anthropic): add server-side web search support

## 2.0.0-alpha.13

### Patch Changes

- 68ecf2f: release alpha.13

## 2.0.0-alpha.12

### Patch Changes

- e2aceaf: feat: add raw chunk support

## 2.0.0-alpha.11

### Patch Changes

- c1e6647: release alpha.11

## 2.0.0-alpha.10

### Patch Changes

- c4df419: release alpha.10

## 2.0.0-alpha.9

### Patch Changes

- 811dff3: release alpha.9

## 2.0.0-alpha.8

### Patch Changes

- 9222aeb: release alpha.8

## 2.0.0-alpha.7

### Patch Changes

- 5c56081: release alpha.7

## 2.0.0-alpha.6

### Patch Changes

- 0d2c085: chore (provider): tweak provider definition

## 2.0.0-alpha.4

### Patch Changes

- dc714f3: release alpha.4

## 2.0.0-alpha.3

### Patch Changes

- 6b98118: release alpha.3

## 2.0.0-alpha.2

### Patch Changes

- 26535e0: release alpha.2

## 2.0.0-alpha.1

### Patch Changes

- 3f2f00c: feat: `ImageModelV2#maxImagesPerCall` can be set to a function that returns a `number` or `undefined`, optionally as a promise

  pull request: https://github.com/vercel/ai/pull/6343

## 2.0.0-canary.14

### Major Changes

- 7979f7f: feat (provider): support reasoning tokens, cached input tokens, total token in usage information

### Patch Changes

- a8c8bd5: feat(embed-many): respect supportsParallelCalls & concurrency

## 2.0.0-canary.13

### Patch Changes

- 9bd5ab5: feat (provider): add providerMetadata to ImageModelV2 interface (#5977)

  The `experimental_generateImage` method from the `ai` package now returnes revised prompts for OpenAI's image models.

  ```js
  const prompt = 'Santa Claus driving a Cadillac';

  const { providerMetadata } = await experimental_generateImage({
    model: openai.image('dall-e-3'),
    prompt,
  });

  const revisedPrompt = providerMetadata.openai.images[0]?.revisedPrompt;

  console.log({
    prompt,
    revisedPrompt,
  });
  ```

## 2.0.0-canary.12

### Patch Changes

- 7b3ae3f: chore (provider): change getSupportedUrls to supportedUrls (language model v2)

## 2.0.0-canary.11

### Major Changes

- e030615: chore (provider): remove prompt type from language model v2 spec

### Patch Changes

- 9bf7291: chore(providers/openai): enable structuredOutputs by default & switch to provider option
- 4617fab: chore(embedding-models): remove remaining settings

## 2.0.0-canary.10

### Major Changes

- a3f768e: chore: restructure reasoning support

### Patch Changes

- 9301f86: refactor (image-model): rename `ImageModelV1` to `ImageModelV2`

## 2.0.0-canary.9

### Major Changes

- e86be6f: chore: remove logprobs

## 2.0.0-canary.8

### Major Changes

- 95857aa: chore: restructure language model supported urls
- 7ea4132: chore: remove object generation mode

## 2.0.0-canary.7

### Major Changes

- b6b43c7: chore: move warnings into stream-start part (spec)
- 3795467: chore: return content array from doGenerate (spec)

### Patch Changes

- 8aa9e20: feat: add speech with experimental_generateSpeech

## 2.0.0-canary.6

### Major Changes

- 14c9410: chore: refactor file towards source pattern (spec)
- d9c98f4: chore: refactor reasoning parts (spec)
- 0054544: chore: refactor source parts (spec)
- 9e9c809: chore: refactor tool call and tool call delta parts (spec)
- 32831c6: chore: refactor text parts (spec)
- d0f9495: chore: refactor file parts (spec)

### Patch Changes

- 26735b5: chore(embedding-model): add v2 interface
- 443d8ec: feat(embedding-model-v2): add response body field
- c4a2fec: chore (provider): extract shared provider options and metadata (spec)
- fd65bc6: chore(embedding-model-v2): rename rawResponse to response
- 393138b: feat(embedding-model-v2): add providerOptions
- 7182d14: Remove `Experimental_LanguageModelV2Middleware` type

## 2.0.0-canary.5

### Major Changes

- 411e483: chore (provider): refactor usage (language model v2)
- ad80501: chore (provider): allow both binary and base64 file content (spec)
- 1766ede: chore: rename maxTokens to maxOutputTokens

### Patch Changes

- 79457bd: chore (provider): extract LanguageModelV2File
- f10304b: feat(tool-calling): don't require the user to have to pass parameters

## 2.0.0-canary.4

### Major Changes

- 6f6bb89: chore (provider): cleanup request and rawRequest (language model v2)

## 2.0.0-canary.3

### Major Changes

- d1a1aa1: chore (provider): merge rawRequest into request (language model v2)

## 2.0.0-canary.2

### Major Changes

- abf9a79: chore: rename mimeType to mediaType
- 6dc848c: chore (provider): remove image parts

### Patch Changes

- a166433: feat: add transcription with experimental_transcribe
- 0a87932: core (ai): change transcription model mimeType to mediaType

## 2.0.0-canary.1

### Major Changes

- c57e248: chore (provider): remove mode
- 33f4a6a: chore (provider): rename providerMetadata inputs to providerOptions

## 2.0.0-canary.0

### Major Changes

- d5f588f: AI SDK 5

## 1.1.0

### Minor Changes

- 5bc638d: AI SDK 4.2

## 1.0.12

### Patch Changes

- 0bd5bc6: feat (ai): support model-generated files

## 1.0.11

### Patch Changes

- 2e1101a: feat (provider/openai): pdf input support

## 1.0.10

### Patch Changes

- e1d3d42: feat (ai): expose raw response body in generateText and generateObject

## 1.0.9

### Patch Changes

- ddf9740: feat (ai): add anthropic reasoning

## 1.0.8

### Patch Changes

- 2761f06: fix (ai/provider): publish with LanguageModelV1Source

## 1.0.7

### Patch Changes

- d89c3b9: feat (provider): add image model support to provider specification

## 1.0.6

### Patch Changes

- 3a58a2e: feat (ai/core): throw NoImageGeneratedError from generateImage when no predictions are returned.

## 1.0.5

### Patch Changes

- 0a699f1: feat: add reasoning token support

## 1.0.4

### Patch Changes

- 19a2ce7: feat (provider): add message option to UnsupportedFunctionalityError
- 6337688: feat: change image generation errors to warnings

## 1.0.3

### Patch Changes

- 5ed5e45: chore (config): Use ts-library.json tsconfig for no-UI libs.

## 1.0.2

### Patch Changes

- 09a9cab: feat (ai/core): add experimental generateImage function

## 1.0.1

### Patch Changes

- b446ae5: feat (provider): Define type for ObjectGenerationMode.

## 1.0.0

### Major Changes

- b469a7e: chore: remove isXXXError methods
- c0ddc24: chore (ai): remove toJSON method from AI SDK errors

## 1.0.0-canary.0

### Major Changes

- b469a7e: chore: remove isXXXError methods
- c0ddc24: chore (ai): remove toJSON method from AI SDK errors

## 0.0.26

### Patch Changes

- aa98cdb: chore: more flexible dependency versioning
- 1486128: feat: add supportsUrl to language model specification
- 7b937c5: feat (provider-utils): improve id generator robustness
- 3b1b69a: feat: provider-defined tools
- 811a317: feat (ai/core): multi-part tool results (incl. images)

## 0.0.25

### Patch Changes

- b9b0d7b: feat (ai): access raw request body

## 0.0.24

### Patch Changes

- d595d0d: feat (ai/core): file content parts

## 0.0.23

### Patch Changes

- 03313cd: feat (ai): expose response id, response model, response timestamp in telemetry and api
- 3be7c1c: fix (provider/anthropic): support prompt caching on assistant messages

## 0.0.22

### Patch Changes

- 26515cb: feat (ai/provider): introduce ProviderV1 specification

## 0.0.21

### Patch Changes

- f2c025e: feat (ai/core): prompt validation

## 0.0.20

### Patch Changes

- 6ac355e: feat (provider/anthropic): add cache control support

## 0.0.19

### Patch Changes

- dd4a0f5: fix (ai/provider): remove invalid check in isJSONParseError

## 0.0.18

### Patch Changes

- 4bd27a9: chore (ai/provider): refactor type validation

## 0.0.17

### Patch Changes

- 029af4c: feat (ai/core): support schema name & description in generateObject & streamObject

## 0.0.16

### Patch Changes

- d58517b: feat (ai/openai): structured outputs

## 0.0.15

### Patch Changes

- 96aed25: fix (ai/provider): release new version

## 0.0.14

### Patch Changes

- a8d1c9e9: feat (ai/core): parallel image download

## 0.0.13

### Patch Changes

- 2b9da0f0: feat (core): support stopSequences setting.
- a5b58845: feat (core): support topK setting
- 4aa8deb3: feat (provider): support responseFormat setting in provider api
- 13b27ec6: chore (ai/core): remove grammar mode

## 0.0.12

### Patch Changes

- b7290943: feat (ai/core): add token usage to embed and embedMany

## 0.0.11

### Patch Changes

- 5edc6110: feat (provider): add headers support to language and embedding model spec

## 0.0.10

### Patch Changes

- 102ca22f: fix (@ai-sdk/provider): fix TypeValidationError.isTypeValidationError

## 0.0.9

### Patch Changes

- 09295e2e: feat (@ai-sdk/provider): add DownloadError

## 0.0.8

### Patch Changes

- f39c0dd2: feat (provider): add toolChoice to language model specification

## 0.0.7

### Patch Changes

- 8e780288: feat (ai/provider): add "unknown" finish reason (for models that don't provide a finish reason)

## 0.0.6

### Patch Changes

- 6a50ac4: feat (provider): add additional error types

## 0.0.5

### Patch Changes

- 0f6bc4e: feat (ai/core): add embed function

## 0.0.4

### Patch Changes

- 325ca55: feat (ai/core): improve image content part error message

## 0.0.3

### Patch Changes

- 41d5736: ai/core: re-expose language model types.

## 0.0.2

### Patch Changes

- d6431ae: ai/core: add logprobs support (thanks @SamStenner for the contribution)
- 25f3350: ai/core: add support for getting raw response headers.

## 0.0.1

### Patch Changes

- eb150a6: ai/core: remove scaling of setting values (breaking change). If you were using the temperature, frequency penalty, or presence penalty settings, you need to update the providers and adjust the setting values.
