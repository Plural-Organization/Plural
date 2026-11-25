// The first-visit tour of a room: what it points at, in what order, and whether this browser has seen it.
//
// Only a newcomer gets it. A browser that already holds rooms, a name or a prompt history belongs to someone who
// used Plural before this tour existed, so it is marked as toured without showing anything.

export type TourPlacement = "top" | "bottom" | "left" | "right";

export interface TourStep {
  id: string;
  // The `data-tour` value of the element the step points at; null centres the card with nothing lit.
  target: string | null;
  // Whether the element lives in the room panel, which a narrow screen keeps closed.
  panel: boolean;
  placement: TourPlacement;
  title: string;
  body: string;
  // A short list under the words, for a step that compares a few choices.
  points?: TourPoint[];
}

export interface TourPoint {
  label: string;
  says: string;
  tone: "safe" | "warn" | "danger";
}

type Store = Pick<Storage, "getItem" | "setItem">;

const DONE_KEY = "plural.toured";
// Keys only an earlier visit leaves behind.
const TRACES = ["plural.rooms", "plural.name", "plural.history"];

const WELCOME = "Your agent runs on the host's computer, and everyone in the room works with it together. Here is where things are; it takes half a minute.";

const HOST: TourStep[] = [
  { id: "welcome", target: null, panel: false, placement: "bottom", title: "Welcome to Plural", body: WELCOME },
  { id: "composer", target: "composer", panel: false, placement: "top", title: "Talk to the agent", body: "Write here. / opens the commands, @ tags a person, and ↑ brings back what you sent before." },
  { id: "agent", target: "agent", panel: true, placement: "left", title: "Pick the agent", body: "Claude Code, Codex or a model by API key. Switch agent changes it at any time and the conversation stays." },
  { id: "replies", target: "replies", panel: true, placement: "left", title: "When it answers", body: "With @plrl the agent answers only when tagged and reads the rest as the team's chat. With Every message it answers all of them." },
  { id: "prompts", target: "prompts", panel: true, placement: "left", title: "Who may prompt", body: "Open lets guests prompt the agent directly. Review sends their prompts to you first, to approve or edit." },
  {
    id: "permissions", target: "permissions", panel: true, placement: "left", title: "What the agent may do",
    body: "How much runs without asking you. You can change it here at any time.",
    points: [
      { label: "Ask", says: "Every edit and command waits for your yes.", tone: "safe" },
      { label: "Auto", says: "Your own requests go through; a guest's still ask you.", tone: "warn" },
      { label: "Danger zone", says: "A guest's commands run on your computer unasked. Only with people you trust; it ends when the room restarts.", tone: "danger" },
    ],
  },
  { id: "people", target: "people", panel: true, placement: "left", title: "Bring the team", body: "Room link lets people prompt with you; a viewer invite lets them watch. Edits and commands always ask you first." },
  { id: "done", target: null, panel: false, placement: "bottom", title: "You are all set", body: "Ask the agent something, then share the room link when you want company." },
];

const GUEST: TourStep[] = [
  { id: "welcome", target: null, panel: false, placement: "bottom", title: "Welcome to Plural", body: WELCOME },
  { id: "composer", target: "composer", panel: false, placement: "top", title: "Talk to the agent", body: "Write here. / opens the commands, @ tags a person, and ↑ brings back what you sent before." },
  { id: "replies", target: "replies", panel: true, placement: "left", title: "When it answers", body: "This says whether the agent answers every message, or only the ones that tag @plrl. The host decides." },
  { id: "prompts", target: "prompts", panel: true, placement: "left", title: "Who may prompt", body: "In review mode the host approves each prompt before the agent sees it." },
  {
    id: "permissions", target: "permissions", panel: true, placement: "left", title: "What the agent may do",
    body: "The host decides how much the agent does without asking them.",
    points: [
      { label: "Ask", says: "The host approves each edit and command you start.", tone: "safe" },
      { label: "Danger zone", says: "What you ask for runs on the host's computer straight away. Ask with care.", tone: "danger" },
    ],
  },
  { id: "people", target: "people", panel: true, placement: "left", title: "Who is here", body: "Everyone in the room sees the same conversation, and every message says who wrote it." },
  { id: "done", target: null, panel: false, placement: "bottom", title: "You are all set", body: "Say hello, or ask the agent what it is working on." },
];

export function tourSteps(isHost: boolean): TourStep[] {
  return isHost ? HOST : GUEST;
}

function storage(): Store | null {
  try {
    return localStorage;
  } catch {
    return null;
  }
}

// Read once when the app starts, before the first room writes its traces.
export function isNewcomer(store: Store | null = storage()): boolean {
  if (store === null) {
    return false;
  }
  try {
    if (store.getItem(DONE_KEY) !== null) {
      return false;
    }
    if (TRACES.some((key) => store.getItem(key) !== null)) {
      store.setItem(DONE_KEY, "returning");
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

export function finishTour(how: "done" | "skipped", store: Store | null = storage()): void {
  try {
    store?.setItem(DONE_KEY, how);
  } catch {
    return;
  }
}
