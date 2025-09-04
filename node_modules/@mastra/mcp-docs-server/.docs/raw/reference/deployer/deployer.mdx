---
title: "Mastra Deployer"
description: Documentation for the Deployer abstract class, which handles packaging and deployment of Mastra applications.
---

# Deployer

The Deployer handles the deployment of standalone Mastra applications by packaging code, managing environment files, and serving applications using the Hono framework. Concrete implementations must define the deploy method for specific deployment targets.

## Usage Example

```typescript
import { Deployer } from "@mastra/deployer";

// Create a custom deployer by extending the abstract Deployer class
class CustomDeployer extends Deployer {
  constructor() {
    super({ name: "custom-deployer" });
  }

  // Implement the abstract deploy method
  async deploy(outputDirectory: string): Promise<void> {
    // Prepare the output directory
    await this.prepare(outputDirectory);

    // Bundle the application
    await this._bundle("server.ts", "mastra.ts", outputDirectory);

    // Custom deployment logic
    // ...
  }
}
```

## Parameters

### Constructor Parameters

<PropertiesTable
  content={[
    {
      name: "args",
      type: "object",
      description: "Configuration options for the Deployer.",
      isOptional: false,
    },
    {
      name: "args.name",
      type: "string",
      description: "A unique name for the deployer instance.",
      isOptional: false,
    },
  ]}
/>

### deploy Parameters

<PropertiesTable
  content={[
    {
      name: "outputDirectory",
      type: "string",
      description:
        "The directory where the bundled and deployment-ready application will be output.",
      isOptional: false,
    },
  ]}
/>

## Methods

<PropertiesTable
  content={[
    {
      name: "getEnvFiles",
      type: "() => Promise<string[]>",
      description:
        "Returns a list of environment files to be used during deployment. By default, it looks for '.env.production' and '.env' files.",
    },
    {
      name: "deploy",
      type: "(outputDirectory: string) => Promise<void>",
      description:
        "Abstract method that must be implemented by subclasses. Handles the deployment process to the specified output directory.",
    },
  ]}
/>

## Inherited Methods from Bundler

The Deployer class inherits the following key methods from the Bundler class:

<PropertiesTable
  content={[
    {
      name: "prepare",
      type: "(outputDirectory: string) => Promise<void>",
      description:
        "Prepares the output directory by cleaning it and creating necessary subdirectories.",
    },
    {
      name: "writeInstrumentationFile",
      type: "(outputDirectory: string) => Promise<void>",
      description:
        "Writes an instrumentation file to the output directory for telemetry purposes.",
    },
    {
      name: "writePackageJson",
      type: "(outputDirectory: string, dependencies: Map<string, string>) => Promise<void>",
      description:
        "Generates a package.json file in the output directory with the specified dependencies.",
    },
    {
      name: "_bundle",
      type: "(serverFile: string, mastraEntryFile: string, outputDirectory: string, bundleLocation?: string) => Promise<void>",
      description:
        "Bundles the application using the specified server and Mastra entry files.",
    },
  ]}
/>

## Core Concepts

### Deployment Lifecycle

The Deployer abstract class implements a structured deployment lifecycle:

1. **Initialization**: The deployer is initialized with a name and creates a Deps instance for dependency management.
2. **Environment Setup**: The `getEnvFiles` method identifies environment files (.env.production, .env) to be used during deployment.
3. **Preparation**: The `prepare` method (inherited from Bundler) cleans the output directory and creates necessary subdirectories.
4. **Bundling**: The `_bundle` method (inherited from Bundler) packages the application code and its dependencies.
5. **Deployment**: The abstract `deploy` method is implemented by subclasses to handle the actual deployment process.

### Environment File Management

The Deployer class includes built-in support for environment file management through the `getEnvFiles` method. This method:

- Looks for environment files in a predefined order (.env.production, .env)
- Uses the FileService to find the first existing file
- Returns an array of found environment files
- Returns an empty array if no environment files are found

```typescript
getEnvFiles(): Promise<string[]> {
  const possibleFiles = ['.env.production', '.env.local', '.env'];

  try {
    const fileService = new FileService();
    const envFile = fileService.getFirstExistingFile(possibleFiles);

    return Promise.resolve([envFile]);
  } catch {}

  return Promise.resolve([]);
}
```

### Bundling and Deployment Relationship

The Deployer class extends the Bundler class, establishing a clear relationship between bundling and deployment:

1. **Bundling as a Prerequisite**: Bundling is a prerequisite step for deployment, where the application code is packaged into a deployable format.
2. **Shared Infrastructure**: Both bundling and deployment share common infrastructure like dependency management and file system operations.
3. **Specialized Deployment Logic**: While bundling focuses on code packaging, deployment adds environment-specific logic for deploying the bundled code.
4. **Extensibility**: The abstract `deploy` method allows for creating specialized deployers for different target environments.
