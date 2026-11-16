import { Button, Spinner } from "@heroui/react";
import { useState } from "react";
import type { SavedSession } from "../lib/daemon";
import { sinceText } from "../lib/sinceText";

// How many show before "Show all"; the newest come first.
const SHOWN = 3;

interface SessionsToContinueProps {
  sessions: SavedSession[];
  // The room being opened now, so its button can say so while the others wait.
  opening: string | null;
  onContinue: (session: SavedSession) => void;
}

// The sessions this computer kept after their host stopped. A session lives on the host's computer, so
// stopping a room does not lose it: it can be continued here, with everything that was said.
export function SessionsToContinue({ sessions, opening, onContinue }: SessionsToContinueProps) {
  const [all, setAll] = useState(false);
  if (sessions.length === 0) {
    return null;
  }
  const shown = all ? sessions : sessions.slice(0, SHOWN);
  return (
    <section aria-labelledby="pl-continue" className="flex flex-col gap-2">
      <h3 id="pl-continue" className="m-0 text-[15px] font-medium">
        Continue a session
      </h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {shown.map((session) => (
          <li key={session.room} className="flex items-center gap-3 rounded-2xl border border-border p-3">
            <div className="min-w-0 flex-1">
              <p className="m-0 truncate text-[15px] font-medium">{session.title}</p>
              <p className="m-0 text-[13px] text-muted">
                {[session.folder, `${session.prompts} ${session.prompts === 1 ? "prompt" : "prompts"}`, sinceText(session.updated_at)].filter((part) => part !== null && part !== "").join(" · ")}
                {session.available ? null : " · folder is gone"}
              </p>
            </div>
            <Button size="sm" variant="secondary" isDisabled={!session.available || opening !== null} onPress={() => onContinue(session)}>
              {opening === session.room ? <Spinner size="sm" color="current" /> : null}
              {session.running ? "Open" : "Continue"}
            </Button>
          </li>
        ))}
      </ul>
      {sessions.length > SHOWN && !all ? (
        <button type="button" className="pl-quiet-button self-start" onClick={() => setAll(true)}>
          Show all {sessions.length}
        </button>
      ) : null}
    </section>
  );
}
