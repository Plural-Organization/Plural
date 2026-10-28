import { displayName, kindOf, type Feed, type Projection, type ToolKind } from "@plural/client";

export type ActivityKind = "approval" | "tool" | "writing" | "thinking" | "compacting" | "waiting";

export interface Activity {
  kind: ActivityKind;
  text: string;
  detail: string;
}

// What the agent is doing right now, in the words the room sees under the last message.
export function activity(projection: Projection, feed: Feed): Activity | null {
  const state = projection.state;
  if (state.run === null) {
    return null;
  }
  if (projection.compacting !== null) {
    return { kind: "compacting", text: "Compacting the context", detail: "" };
  }
  const approval = Object.values(state.approvals)[0];
  if (approval !== undefined) {
    const host = projection.me?.role === "host";
    return {
      kind: "approval",
      text: host ? "Asks your permission" : "Waits for the host's permission",
      detail: `${displayName(approval.call.name)} ${approval.call.subject}`.trim(),
    };
  }
  const last = feed.items.at(-1);
  if (last?.kind === "tool" && last.status === "running") {
    return { kind: "tool", text: verb(last.call.name), detail: "" };
  }
  if (last?.kind === "assistant" && last.streaming) {
    return { kind: "writing", text: "Writing", detail: "" };
  }
  if (projection.reasoning > 0) {
    return { kind: "thinking", text: "Thinking", detail: "" };
  }
  return { kind: "waiting", text: "Thinking", detail: "" };
}

const VERBS: Record<ToolKind, string> = {
  bash: "Running a command",
  read: "Reading",
  edit: "Editing",
  write: "Writing a file",
  list: "Looking around",
  search: "Searching",
  other: "",
};

function verb(tool: string): string {
  return VERBS[kindOf(tool)] || (tool.includes("web") ? "Searching the web" : `Using ${displayName(tool)}`);
}
