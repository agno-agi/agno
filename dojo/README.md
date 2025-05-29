# AG-UI Protocol Dojo

A modern, interactive viewer for exploring CopilotKit agent demos with a clean, responsive UI and dark/light theme support.

## Overview

The Demo Viewer provides a centralized interface for browsing, viewing, and exploring the source code of various CopilotKit agent demos. It features:

- Clean, modern UI with dark/light theme support
- Interactive demo previews
- Source code exploration with syntax highlighting
- Organized demo listing with tags and descriptions
- LLM provider selection

## Development Setup

To run the Demo Viewer locally for development, follow these steps:

### Run the Demo Viewer

In a new terminal, navigate to the project root and start the Demo Viewer:

```bash
pnpm install
pnpm run dev
```

The Demo Viewer should now be running at [http://localhost:3000](http://localhost:3000).

### Adding a new integration

On a fresh clone of this repo, you'll find that we've created a mock agent that represents all of the events needed to create an ACP compliant agent. To extend this to support
your own integration, you'll need to:

1. Edit `src/examples/your-custom-http-agent.ts` to implement your own agent.
2. Alternatively, edit `src/examples/your-custom-agent.ts` to implement a non http based integration.
3. Read `src/app/api/sse/agentic_chat/route.ts` to understand what events need to be emitted on the agent side.

## Project Structure

- `src/examples` - Example agents
- `src/app` - Next.js app router files
- `src/components` - Reusable UI components
- `src/demos` - Demo configuration and utilities
- `src/hooks` - Custom React hooks
- `src/types` - TypeScript type definitions
- `public` - Static assets

## Technologies

- Next.js
- React
- TypeScript
- Tailwind CSS
- CopilotKit
