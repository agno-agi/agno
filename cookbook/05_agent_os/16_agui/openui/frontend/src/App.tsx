import { AgentInterface, createTheme } from "@openuidev/react-ui";
import { useMemo } from "react";

import { createAgnoLLM } from "./agno";
import { library } from "./library";

const lightTheme = createTheme({
  background: "oklch(0.985 0.012 92)",
  foreground: "oklch(0.96 0.02 90)",
  interactiveAccentDefault: "oklch(0.48 0.13 182)",
  interactiveAccentHover: "oklch(0.42 0.13 182)",
  chatUserResponseBg: "oklch(0.88 0.08 82)",
  chatUserResponseText: "oklch(0.25 0.03 70)",
  radiusM: "14px",
  radiusL: "20px",
  fontBody: '"Avenir Next", Avenir, "Segoe UI", sans-serif',
  fontHeading: '"Avenir Next", Avenir, "Segoe UI", sans-serif',
  barChartPalette: ["oklch(0.58 0.15 181)", "oklch(0.72 0.16 73)", "oklch(0.62 0.14 246)"],
});

const darkTheme = createTheme({
  background: "oklch(0.18 0.025 196)",
  foreground: "oklch(0.23 0.025 196)",
  interactiveAccentDefault: "oklch(0.74 0.13 178)",
  interactiveAccentHover: "oklch(0.8 0.12 178)",
  chatUserResponseBg: "oklch(0.42 0.09 78)",
  chatUserResponseText: "oklch(0.97 0.015 92)",
  radiusM: "14px",
  radiusL: "20px",
  fontBody: '"Avenir Next", Avenir, "Segoe UI", sans-serif',
  fontHeading: '"Avenir Next", Avenir, "Segoe UI", sans-serif',
  barChartPalette: ["oklch(0.74 0.14 181)", "oklch(0.79 0.14 77)", "oklch(0.72 0.13 244)"],
});

const starters = [
  {
    displayText: "Chart + follow-ups",
    prompt:
      "Show quarterly revenue as a labeled bar or line chart: Q1 120, Q2 180, Q3 150, Q4 240. End with two relevant follow-up suggestions.",
  },
  {
    displayText: "Validated form",
    prompt:
      "Create a validated project estimate form with project name, team size, and notes fields, plus a primary submit action.",
  },
  {
    displayText: "Use an Agno tool",
    prompt:
      "Use the stored quarterly revenue data and show it as a labeled chart with two useful follow-up suggestions.",
  },
];

export default function App() {
  const llm = useMemo(() => createAgnoLLM(), []);

  return (
    <main className="app-shell" data-testid="openui-agno-app">
      <AgentInterface
        llm={llm}
        componentLibrary={library}
        agentName="Agno × OpenUI"
        theme={{ mode: "light", lightTheme, darkTheme }}
        starterVariant="short"
        starters={starters}
      >
        <AgentInterface.Welcome
          className="agno-openui-welcome"
          glowAnimation
          title="Agno × OpenUI"
          description="Intelligent agents from Agno, rendered as generative interfaces with OpenUI."
        />
      </AgentInterface>
    </main>
  );
}
