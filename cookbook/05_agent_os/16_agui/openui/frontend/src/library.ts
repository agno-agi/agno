import { openuiChatLibrary, openuiChatPromptOptions } from "@openuidev/react-ui/genui-lib";

export const library = openuiChatLibrary;

export const promptOptions = {
  ...openuiChatPromptOptions,
  additionalRules: [
    ...(openuiChatPromptOptions.additionalRules ?? []),
    "When the user asks for follow-up suggestions, include exactly the requested number of FollowUpItem values inside a FollowUpBlock at the end of the Card.",
    "When the user asks for a submit form, mark the requested fields required and make one primary submit Button whose Action contains @ToAssistant.",
  ],
};
