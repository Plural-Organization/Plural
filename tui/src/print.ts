import type { Command, Event, Session } from "@plural/client";
import type { OutputFormat } from "./options";

export interface Writer {
  write: (text: string) => void;
}

export interface PrintRequest {
  prompt: string;
  format: OutputFormat;
  commands: Command[];
  room: string;
}

interface Outcome {
  ok: boolean;
  reason: string;
  error: string | null;
  usage: unknown;
}

const QUIET = new Set(["session.welcome", "session.snapshot", "invite.created"]);

function deny(subject: string): string {
  return `denied: ${subject} needs the host's approval and nobody is there to give it. Allow it with --allowedTools or --permission-mode.`;
}

export async function runPrint(session: Session, request: PrintRequest, out: Writer, err: Writer, clock: () => number = Date.now): Promise<number> {
  const started = clock();
  let reply = "";
  let turns = 0;
  let begun = false;
  let failure: string | null = null;
  let outcome: Outcome | null = null;
  const denied: string[] = [];

  const begin = async (): Promise<void> => {
    for (const command of request.commands) {
      await session.send(command);
    }
    await session.send({ type: "prompt.submit", text: request.prompt, delivery: "now" });
  };

  for await (const event of session.events() as AsyncIterable<Event>) {
    if (request.format === "stream-json" && !QUIET.has(event.type)) {
      out.write(`${JSON.stringify(event)}\n`);
    }
    switch (event.type) {
      case "session.welcome":
        if (!begun) {
          begun = true;
          begin().catch((error: unknown) => {
            failure = error instanceof Error ? error.message : String(error);
            session.close();
          });
        }
        break;
      case "message.started":
        turns += 1;
        break;
      case "message.ended":
        if (event.text.trim() !== "") {
          reply = event.text;
        }
        break;
      case "approval.requested": {
        const subject = `${event.approval.call.name} ${event.approval.call.subject}`.trim();
        denied.push(subject);
        err.write(`${deny(subject)}\n`);
        session.send({ type: "approval.respond", approval_id: event.approval.id, decision: "reject" }).catch(() => undefined);
        break;
      }
      case "error":
        if (outcome === null && !failure) {
          failure = event.message;
        }
        err.write(`error: ${event.message}\n`);
        break;
      case "run.ended":
        outcome = { ok: event.reason === "stop", reason: event.reason, error: event.error ?? null, usage: event.usage };
        session.close();
        break;
    }
  }
  session.close();

  const result: Outcome = outcome ?? { ok: false, reason: "error", error: failure ?? "the session ended before the agent answered", usage: null };
  const ok = result.ok && failure === null;
  if (request.format === "text") {
    if (reply !== "") {
      out.write(`${reply}\n`);
    }
  } else {
    out.write(
      `${JSON.stringify({
        type: "result",
        subtype: ok ? "success" : "error",
        is_error: !ok,
        result: reply,
        session_id: request.room,
        num_turns: turns,
        duration_ms: clock() - started,
        usage: result.usage,
        denied,
        error: ok ? null : (result.error ?? failure ?? result.reason),
      })}\n`,
    );
  }
  if (!ok) {
    err.write(`run ended: ${result.reason}${result.error ? ` (${result.error})` : failure ? ` (${failure})` : ""}\n`);
  } else if (denied.length > 0 && request.format === "text") {
    err.write(`${denied.length} action${denied.length === 1 ? " was" : "s were"} denied, the answer may be incomplete\n`);
  }
  return ok ? 0 : 1;
}

export async function readStdin(stream: NodeJS.ReadStream = process.stdin): Promise<string> {
  if (stream.isTTY === true) {
    return "";
  }
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export function composePrompt(prompt: string | null, piped: string): string {
  const text = piped.trim() === "" ? "" : piped.replace(/\s+$/, "");
  if (prompt === null || prompt.trim() === "") {
    return text;
  }
  return text === "" ? prompt : `${text}\n\n${prompt}`;
}
