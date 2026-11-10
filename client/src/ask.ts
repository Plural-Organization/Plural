import type { Session } from "./session";
import { CommandRejected } from "./wire";

export interface AskRequest {
  focus: string | null;
  update: boolean;
}

// What a teammate's agent wrote for this person. `from` is the teammate, `asOf` the event it describes.
export interface Briefing {
  from: string;
  text: string;
  asOf: number;
  update: boolean;
}

// Their host has to agree first, so a person may be away: wait a while, not forever.
export const ASK_WAIT_MS = 5 * 60_000;

export interface AskOptions {
  from: string;
  onProgress?: (text: string) => void;
  waitMs?: number;
}

// Asks the agent behind `session` for a briefing and closes the session when it is over, however it ends. The
// session is a short visit: it is joined, asked once, and left, so the person never has to open the teammate's
// session to get an answer from it.
export async function askTeammate(session: Session, request: AskRequest, options: AskOptions): Promise<Briefing> {
  const { from, onProgress, waitMs = ASK_WAIT_MS } = options;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    session.close();
  }, waitMs);
  let asked = false;
  try {
    for await (const event of session.events()) {
      if (!asked && session.status === "online") {
        asked = true;
        await session.send({ type: "briefing.request", focus: request.focus, update: request.update }).catch((error: unknown) => {
          throw error instanceof CommandRejected ? new Error(error.error.message) : error;
        });
      }
      const me = session.projection.meId;
      if (event.type === "briefing.requested" && event.request.participant_id === me) {
        onProgress?.(`waiting for ${from} to agree`);
      } else if (event.type === "briefing.resolved" && event.participant_id === me) {
        if (event.decision !== "granted") {
          throw new Error(`${from} said no to the briefing`);
        }
        onProgress?.(`${from} agreed, their agent is writing it`);
      } else if (event.type === "briefing.delivered" && event.to === me) {
        if (event.error) {
          throw new Error(`${from}'s briefing could not be written: ${event.error}`);
        }
        return { from, text: event.text, asOf: event.as_of_seq, update: event.update };
      }
    }
    throw new Error(timedOut ? `${from} did not answer in ${Math.round(waitMs / 60_000)} minutes` : `the connection to ${from} closed before the briefing came`);
  } finally {
    clearTimeout(timer);
    session.close();
  }
}
