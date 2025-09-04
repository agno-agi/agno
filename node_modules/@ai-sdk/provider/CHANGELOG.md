# @ai-sdk/provider

## 1.1.3

### Patch Changes

- beef951: feat: add speech with experimental_generateSpeech

## 1.1.2

### Patch Changes

- 013faa8: core (ai): change transcription model mimeType to mediaType

## 1.1.1

### Patch Changes

- c21fa6d: feat: add transcription with experimental_transcribe

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
