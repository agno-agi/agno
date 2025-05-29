import { type ComponentType } from "react";

export type LLMProvider = "openai" | "anthropic";

export interface DemoFile {
  name: string; // Display name (filename only)
  path: string; // Full file path
  content: string;
  language: string;
}

export interface DemoConfig {
  id: string;
  name: string;
  description: string;
  path: string;
  files: DemoFile[];
  defaultLLMProvider?: LLMProvider;
  tags?: string[];
}

export interface BrandConfig {
  id: string;
  name: string;
  logo: string;
  primaryColor: string;
  secondaryColor: string;
}

export interface ViewerConfig {
  showCodeEditor?: boolean;
  showFileTree?: boolean;
  showLLMSelector?: boolean;
}
