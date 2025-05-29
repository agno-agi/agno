"use client";
import { CopilotKit, useCopilotAction } from "@copilotkit/react-core";
import { CopilotKitCSSProperties, CopilotSidebar } from "@copilotkit/react-ui";
import { useState } from "react";
import "@copilotkit/react-ui/styles.css";
import "./style.css";

export default function AgenticChat() {
  return (
    <CopilotKit
      runtimeUrl="/api/copilotkit"
      showDevConsole={false}
      // agent lock to the relevant agent
      agent="toolBasedGenerativeUIAgent"
    >
      <div
        className="min-h-full w-full flex items-center justify-center"
        style={
          {
            // "--copilot-kit-primary-color": "#222",
            // "--copilot-kit-separator-color": "#CCC",
          } as CopilotKitCSSProperties
        }
      >
        <Haiku />
        <CopilotSidebar
          defaultOpen={true}
          labels={{
            title: "Haiku Generator",
            initial: "I'm a haiku generator 👋. How can I help you?",
          }}
          clickOutsideToClose={false}
        />
      </div>
    </CopilotKit>
  );
}

function Haiku() {
  const [haiku, setHaiku] = useState<{
    japanese: string[];
    english: string[];
  }>({
    japanese: ["仮の句よ", "まっさらながら", "花を呼ぶ"],
    english: [
      "A placeholder verse—",
      "even in a blank canvas,",
      "it beckons flowers.",
    ],
  });

  useCopilotAction({
    name: "generate_haiku",
    parameters: [
      {
        name: "japanese",
        type: "string[]",
      },
      {
        name: "english",
        type: "string[]",
      },
    ],
    followUp: false,
    handler: async () => {
      return "Haiku generated.";
    },
    render: ({ args: generatedHaiku, result, status }) => {
      return (
        <HaikuApproval
          setHaiku={setHaiku}
          generatedHaiku={generatedHaiku}
          status={status}
        />
      );
    },
  });
  return (
    <>
      <div className="text-left">
        {haiku?.japanese.map((line, index) => (
          <div className="flex items-center gap-6 mb-2" key={index}>
            <p className="text-4xl font-bold text-gray-500">{line}</p>
            <p className="text-base font-light">{haiku?.english?.[index]}</p>
          </div>
        ))}
      </div>
    </>
  );
}

interface HaikuApprovalProps {
  setHaiku: any;
  status: any;
  generatedHaiku: any;
}

function HaikuApproval({
  setHaiku,
  status,
  generatedHaiku,
}: HaikuApprovalProps) {
  const [isApplied, setIsApplied] = useState(false);
  if (
    !generatedHaiku ||
    !generatedHaiku.japanese ||
    !generatedHaiku.japanese.length
  ) {
    return <></>;
  }

  return (
    <div className="text-left rounded-md p-4 mt-4 mb-4 flex flex-col bg-gray-100 dark:bg-zinc-900">
      <div
        className={status === "complete" ? "border-b border-gray-300 mb-4" : ""}
      >
        {generatedHaiku?.japanese?.map((line: string, index: number) => (
          <div className="flex items-center gap-3 mb-2 pb-2" key={index}>
            <p className="text-lg font-bold">{line}</p>
            <p className="text-sm font-light">
              {generatedHaiku?.english?.[index]}
            </p>
          </div>
        ))}
      </div>
      {status === "complete" && (
        <button
          onClick={() => {
            setHaiku(generatedHaiku);
            setIsApplied(true);
          }}
          className="ml-auto px-3 py-1 bg-white dark:bg-black text-black dark:text-white text-sm rounded cursor-pointer font-sm border "
        >
          {isApplied ? "Applied ✓" : "Apply"}
        </button>
      )}
    </div>
  );
}
