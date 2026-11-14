import type { ChatMode, PermissionMode, PromptMode } from "@plural/client";

// What the host can set on a room that is already running. Each option names what it does, so the
// panel can say it in words instead of leaving a bare toggle.
export type AdmissionMode = "approve" | "open";
export type BriefingSharing = "off" | "ask" | "team";

export interface Option<T extends string> {
  id: T;
  label: string;
  says: string;
  // Drawn in the danger colour: the choice hands something over that is hard to take back.
  danger?: boolean;
}

export const PROMPTS: Option<PromptMode>[] = [
  { id: "open", label: "Open", says: "Everyone who can prompt talks to the agent directly." },
  { id: "review", label: "Review", says: "You approve each prompt before the agent sees it." },
];

export const REPLIES: Option<ChatMode>[] = [
  { id: "mention", label: "@plrl", says: "A plain message is chat between people. The agent reads it and answers only messages that tag @plrl." },
  { id: "all", label: "Every message", says: "The agent answers everything typed. /team writes to people only." },
];

export const PERMISSIONS: Option<PermissionMode>[] = [
  { id: "default", label: "Ask", says: "The agent asks you before it edits a file or runs a command." },
  { id: "accept_edits", label: "Edits", says: "File edits go through; commands still ask." },
  { id: "plan", label: "Plan", says: "The agent only reads and replies with a plan. Nothing is changed." },
  { id: "auto", label: "Auto", says: "Your own edits and commands go through. What a guest starts still asks you. Deny rules still hold." },
  { id: "danger", label: "Danger zone", danger: true, says: "What a guest starts runs without asking you. Other folders and files still ask. Ends when the room restarts." },
];

// Said once, before the host turns the danger zone on: it is the one setting that hands the host's machine to other people.
export const DANGER_TITLE = "Turn on the danger zone?";
export const DANGER_WARNING =
  "Commands and file edits that guests ask the agent for will run on your computer without asking you first, and a command can do anything your account can: delete files, send data out, install software. " +
  "You are responsible for everything that runs while this is on. Folders outside the project, protected files and your deny rules still ask or refuse, and it switches off when the room restarts.";

export const ADMISSION: Option<AdmissionMode>[] = [
  { id: "approve", label: "I approve", says: "You are asked to let in each person who uses the room link." },
  { id: "open", label: "Anyone", says: "Anyone with the room link joins at once." },
];

export const BRIEFINGS: Option<BriefingSharing>[] = [
  { id: "off", label: "Off", says: "Nobody can ask this session for a briefing." },
  { id: "ask", label: "Ask me", says: "You decide each time someone asks what this session is doing." },
  { id: "team", label: "Team", says: "Your team gets briefings at once." },
];

export function saysOf<T extends string>(options: Option<T>[], current: T): string {
  return options.find((option) => option.id === current)?.says ?? "";
}
