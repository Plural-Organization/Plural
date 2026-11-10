import type { Span } from "@plural/client";

/** One message of what a model was sent, or one tool call it asked for. */
export interface ChatPart {
  role: string;
  content: string;
  /** Tool calls the message carried, as pretty JSON each. */
  calls: { name: string; args: string }[];
  error: boolean;
  images: number;
}

export type Content =
  | { kind: "empty"; note: string }
  | { kind: "text"; text: string }
  | { kind: "json"; text: string }
  | { kind: "chat"; system: string; parts: ChatPart[]; omitted: number; tools: string[] };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

function parse(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function calls(value: unknown): ChatPart["calls"] {
  return Array.isArray(value)
    ? value.filter(isRecord).map((call) => ({ name: String(call.name ?? "tool"), args: JSON.stringify(call.args ?? {}, null, 2) }))
    : [];
}

/** What a span took in, ready to show: a model call's conversation, a tool call's arguments. */
export function spanInput(span: Span): Content {
  if (span.input === "") {
    return { kind: "empty", note: span.kind === "llm" ? "Only the host sees what the model was sent." : "Nothing was recorded." };
  }
  if (span.kind === "llm") {
    const data = parse(span.input);
    if (isRecord(data) && Array.isArray(data.messages)) {
      return {
        kind: "chat",
        system: typeof data.system === "string" ? data.system : "",
        omitted: typeof data.omitted === "number" ? data.omitted : 0,
        tools: Array.isArray(data.tools) ? data.tools.map(String) : [],
        parts: data.messages.filter(isRecord).map((message) => ({
          role: String(message.role ?? "user"),
          content: typeof message.content === "string" ? message.content : "",
          calls: calls(message.tool_calls),
          error: message.error === true,
          images: typeof message.images === "number" ? message.images : 0,
        })),
      };
    }
  }
  const data = parse(span.input);
  return data !== undefined && typeof data === "object" ? { kind: "json", text: JSON.stringify(data, null, 2) } : { kind: "text", text: span.input };
}

/** What a span gave back: a model's answer and the tools it asked for, a tool's result. */
export function spanOutput(span: Span): Content {
  if (span.output === "") {
    return { kind: "empty", note: span.status === "running" ? "Still running." : "Nothing came back." };
  }
  if (span.kind === "llm") {
    const data = parse(span.output);
    if (isRecord(data)) {
      const text = typeof data.text === "string" ? data.text : "";
      return { kind: "chat", system: "", omitted: 0, tools: [], parts: [{ role: "assistant", content: text, calls: calls(data.tool_calls), error: false, images: 0 }] };
    }
  }
  return { kind: "text", text: span.output };
}

/** The text a copy button puts on the clipboard: the span's own record, as stored. */
export function copyable(span: Span, which: "input" | "output"): string {
  const text = which === "input" ? span.input : span.output;
  const data = parse(text);
  return data !== undefined && typeof data === "object" ? JSON.stringify(data, null, 2) : text;
}
