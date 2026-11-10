import type { PermissionMode, PromptMode } from "@plural/client";

// What the host can set on a room that is already running. Each option names what it does, so the
// panel can say it in words instead of leaving a bare toggle.
export type AdmissionMode = "approve" | "open";
export type BriefingSharing = "off" | "ask" | "team";

export interface Option<T extends string> {
  id: T;
  label: string;
  says: string;
}

export const PROMPTS: Option<PromptMode>[] = [
  { id: "open", label: "Open", says: "Everyone who can prompt talks to the agent directly." },
  { id: "review", label: "Review", says: "You approve each prompt before the agent sees it." },
];

export const PERMISSIONS: Option<PermissionMode>[] = [
  { id: "default", label: "Ask", says: "The agent asks you before it edits a file or runs a command." },
  { id: "accept_edits", label: "Edits", says: "File edits go through; commands still ask." },
  { id: "plan", label: "Plan", says: "The agent only reads and replies with a plan. Nothing is changed." },
  { id: "auto", label: "Auto", says: "Edits and commands go through. Deny rules still hold." },
];

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
