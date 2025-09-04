# Adding Voice to Agents

Mastra agents can be enhanced with voice capabilities, allowing them to speak responses and listen to user input. You can configure an agent to use either a single voice provider or combine multiple providers for different operations.

## Using a Single Provider

The simplest way to add voice to an agent is to use a single provider for both speaking and listening:

```typescript
import { createReadStream } from "fs";
import path from "path";
import { Agent } from "@mastra/core/agent";
import { OpenAIVoice } from "@mastra/voice-openai";
import { openai } from "@ai-sdk/openai";

// Initialize the voice provider with default settings
const voice = new OpenAIVoice();

// Create an agent with voice capabilities
export const agent = new Agent({
  name: "Agent",
  instructions: `You are a helpful assistant with both STT and TTS capabilities.`,
  model: openai("gpt-4o"),
  voice,
});

// The agent can now use voice for interaction
const audioStream = await agent.voice.speak("Hello, I'm your AI assistant!", {
  filetype: "m4a",
});

playAudio(audioStream!);

try {
  const transcription = await agent.voice.listen(audioStream);
  console.log(transcription);
} catch (error) {
  console.error("Error transcribing audio:", error);
}
```

## Using Multiple Providers

For more flexibility, you can use different providers for speaking and listening using the CompositeVoice class:

```typescript
import { Agent } from "@mastra/core/agent";
import { CompositeVoice } from "@mastra/core/voice";
import { OpenAIVoice } from "@mastra/voice-openai";
import { PlayAIVoice } from "@mastra/voice-playai";
import { openai } from "@ai-sdk/openai";

export const agent = new Agent({
  name: "Agent",
  instructions: `You are a helpful assistant with both STT and TTS capabilities.`,
  model: openai("gpt-4o"),

  // Create a composite voice using OpenAI for listening and PlayAI for speaking
  voice: new CompositeVoice({
    input: new OpenAIVoice(),
    output: new PlayAIVoice(),
  }),
});
```

## Working with Audio Streams

The `speak()` and `listen()` methods work with Node.js streams. Here's how to save and load audio files:

### Saving Speech Output

The `speak` method returns a stream that you can pipe to a file or speaker.

```typescript
import { createWriteStream } from "fs";
import path from "path";

// Generate speech and save to file
const audio = await agent.voice.speak("Hello, World!");
const filePath = path.join(process.cwd(), "agent.mp3");
const writer = createWriteStream(filePath);

audio.pipe(writer);

await new Promise<void>((resolve, reject) => {
  writer.on("finish", () => resolve());
  writer.on("error", reject);
});
```

### Transcribing Audio Input

The `listen` method expects a stream of audio data from a microphone or file.

```typescript
import { createReadStream } from "fs";
import path from "path";

// Read audio file and transcribe
const audioFilePath = path.join(process.cwd(), "/agent.m4a");
const audioStream = createReadStream(audioFilePath);

try {
  console.log("Transcribing audio file...");
  const transcription = await agent.voice.listen(audioStream, {
    filetype: "m4a",
  });
  console.log("Transcription:", transcription);
} catch (error) {
  console.error("Error transcribing audio:", error);
}
```

## Speech-to-Speech Voice Interactions

For more dynamic and interactive voice experiences, you can use real-time voice providers that support speech-to-speech capabilities:

```typescript
import { Agent } from "@mastra/core/agent";
import { getMicrophoneStream } from "@mastra/node-audio";
import { OpenAIRealtimeVoice } from "@mastra/voice-openai-realtime";
import { search, calculate } from "../tools";

// Initialize the realtime voice provider
const voice = new OpenAIRealtimeVoice({
  apiKey: process.env.OPENAI_API_KEY,
  model: "gpt-4o-mini-realtime",
  speaker: "alloy",
});

// Create an agent with speech-to-speech voice capabilities
export const agent = new Agent({
  name: "Agent",
  instructions: `You are a helpful assistant with speech-to-speech capabilities.`,
  model: openai("gpt-4o"),
  tools: {
    // Tools configured on Agent are passed to voice provider
    search,
    calculate,
  },
  voice,
});

// Establish a WebSocket connection
await agent.voice.connect();

// Start a conversation
agent.voice.speak("Hello, I'm your AI assistant!");

// Stream audio from a microphone
const microphoneStream = getMicrophoneStream();
agent.voice.send(microphoneStream);

// When done with the conversation
agent.voice.close();
```

### Event System

The realtime voice provider emits several events you can listen for:

```typescript
// Listen for speech audio data sent from voice provider
agent.voice.on("speaking", ({ audio }) => {
  // audio contains ReadableStream or Int16Array audio data
});

// Listen for transcribed text sent from both voice provider and user
agent.voice.on("writing", ({ text, role }) => {
  console.log(`${role} said: ${text}`);
});

// Listen for errors
agent.voice.on("error", (error) => {
  console.error("Voice error:", error);
});
```

## Supported Voice Providers

Mastra supports multiple voice providers for text-to-speech (TTS) and speech-to-text (STT) capabilities:

| Provider        | Package                         | Features                  | Reference                                         |
| --------------- | ------------------------------- | ------------------------- | ------------------------------------------------- |
| OpenAI          | `@mastra/voice-openai`          | TTS, STT                  | [Documentation](/reference/voice/openai)          |
| OpenAI Realtime | `@mastra/voice-openai-realtime` | Realtime speech-to-speech | [Documentation](/reference/voice/openai-realtime) |
| ElevenLabs      | `@mastra/voice-elevenlabs`      | High-quality TTS          | [Documentation](/reference/voice/elevenlabs)      |
| PlayAI          | `@mastra/voice-playai`          | TTS                       | [Documentation](/reference/voice/playai)          |
| Google          | `@mastra/voice-google`          | TTS, STT                  | [Documentation](/reference/voice/google)          |
| Deepgram        | `@mastra/voice-deepgram`        | STT                       | [Documentation](/reference/voice/deepgram)        |
| Murf            | `@mastra/voice-murf`            | TTS                       | [Documentation](/reference/voice/murf)            |
| Speechify       | `@mastra/voice-speechify`       | TTS                       | [Documentation](/reference/voice/speechify)       |
| Sarvam          | `@mastra/voice-sarvam`          | TTS, STT                  | [Documentation](/reference/voice/sarvam)          |
| Azure           | `@mastra/voice-azure`           | TTS, STT                  | [Documentation](/reference/voice/mastra-voice)    |
| Cloudflare      | `@mastra/voice-cloudflare`      | TTS                       | [Documentation](/reference/voice/mastra-voice)    |

For more details on voice capabilities, see the [Voice API Reference](/reference/voice/mastra-voice).
