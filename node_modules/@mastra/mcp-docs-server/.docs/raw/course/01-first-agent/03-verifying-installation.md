# Verifying Your Mastra Installation

Before we begin building our agent, let's make sure you have the right development environment set up. Let's check if you have Node.js 18.x or later installed.

Then, let's check if @mastra/core is in the package.json and there is a src/mastra directory. If so, you can skip this step.

If you haven't installed Mastra yet, you can do so by running:

```bash
npm -y create mastra@latest
```

If you do need to install mastra, follow the on-screen prompts and make sure to:

- Opt-in to installing both Agents and Workflows
- Say yes to installing tools
- Select OpenAI, Anthropic, or Google for your model
- Say yes to adding an example

You'll also need to add your OpenAI, Anthropic, or Google API key to the project.
