import { createCliRenderer } from "@opentui/core";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import { createRoot } from "@opentui/react";
import { useReducer, useRef } from "react";
import { rejoinLink, type JoinedRoom } from "./joined";
import { ago, inFolder, type SessionInfo } from "./sessions";
import { truncate } from "./lib/wrap";
import { theme } from "./theme";

export type Pick = { kind: "host"; info: SessionInfo } | { kind: "joined"; room: JoinedRoom };

interface Row {
  pick: Pick;
  title: string;
  detail: string;
  search: string;
}

export function rowsFor(sessions: SessionInfo[], joined: JoinedRoom[], folder: string | null, now: Date = new Date()): Row[] {
  const hosted = folder === null ? sessions : inFolder(sessions, folder);
  const rows: Row[] = hosted.map((info) => ({
    pick: { kind: "host", info },
    title: info.title,
    detail: `${ago(info.updated_at, now)} · ${info.prompts} prompts${info.people > 1 ? ` · ${info.people} people` : ""}${info.workspace ? ` · ${info.workspace}` : ""}`,
    search: `${info.title} ${info.room} ${info.workspace ?? ""}`.toLowerCase(),
  }));
  const guest: Row[] = joined.map((room) => ({
    pick: { kind: "joined", room },
    title: `joined room ${room.room.slice(0, 14)}…`,
    detail: `${ago(room.savedAt, now)} · as ${room.name} · another person's session`,
    search: `${room.room} joined ${room.url}`.toLowerCase(),
  }));
  return [...rows, ...guest];
}

interface PickerProps {
  sessions: SessionInfo[];
  joined: JoinedRoom[];
  folder: string;
  onChoose: (pick: Pick | null) => void;
}

export function Picker({ sessions, joined, folder, onChoose }: PickerProps) {
  const { width, height } = useTerminalDimensions();
  const [, redraw] = useReducer((value: number) => value + 1, 0);
  const local = useRef({ everywhere: inFolder(sessions, folder).length === 0, query: "", index: 0 });
  const visible = (): Row[] => {
    const { everywhere, query } = local.current;
    const all = rowsFor(sessions, joined, everywhere ? null : folder);
    return query === "" ? all : all.filter((row) => row.search.includes(query.toLowerCase()));
  };
  const set = (changes: Partial<typeof local.current>): void => {
    local.current = { ...local.current, ...changes };
    redraw();
  };

  useKeyboard((key) => {
    key.preventDefault();
    const rows = visible();
    const { everywhere, query, index } = local.current;
    const chosen = Math.min(index, Math.max(0, rows.length - 1));
    if (key.name === "escape" || (key.ctrl && key.name === "c")) {
      onChoose(null);
    } else if (key.name === "return") {
      onChoose(rows[chosen]?.pick ?? null);
    } else if (key.name === "up") {
      set({ index: Math.max(0, chosen - 1) });
    } else if (key.name === "down") {
      set({ index: Math.min(Math.max(0, rows.length - 1), chosen + 1) });
    } else if (key.name === "tab") {
      set({ everywhere: !everywhere, index: 0 });
    } else if (key.name === "backspace") {
      set({ query: query.slice(0, -1), index: 0 });
    } else if (!key.ctrl && !key.meta && key.sequence.length === 1 && key.sequence >= " ") {
      set({ query: query + key.sequence, index: 0 });
    }
  });

  const rows = visible();
  const { everywhere, query, index } = local.current;
  const chosen = Math.min(index, Math.max(0, rows.length - 1));
  const room = Math.max(3, height - 7);
  const first = Math.max(0, Math.min(chosen - Math.floor(room / 2), rows.length - room));
  const window = rows.slice(first, first + room);

  return (
    <box flexDirection="column" width={width} height={height} paddingX={2} paddingY={1}>
      <text>
        <span fg={theme.accent}>
          <b>◆ resume a session</b>
        </span>
        <span fg={theme.dim}>{`  ${everywhere ? "all folders" : folder}${query === "" ? "" : `  ·  filter: ${query}`}`}</span>
      </text>
      <box flexDirection="column" marginTop={1} flexGrow={1}>
        {rows.length === 0 ? <text fg={theme.dim}>{query === "" ? "no sessions yet" : "nothing matches"}</text> : null}
        {window.map((row, position) => {
          const on = first + position === chosen;
          return (
            <box key={`${row.pick.kind}-${row.title}-${first + position}`} flexDirection="column" marginBottom={1}>
              <text fg={on ? theme.accent : theme.text}>
                {on ? "› " : "  "}
                <b>{truncate(row.title, width - 8)}</b>
              </text>
              <text fg={theme.dim}>{`    ${truncate(row.detail, width - 8)}`}</text>
            </box>
          );
        })}
      </box>
      <text fg={theme.dim}>↑↓ choose · enter resume · tab {everywhere ? "this folder" : "all folders"} · type to filter · esc cancel</text>
    </box>
  );
}

export async function pickSession(sessions: SessionInfo[], joined: JoinedRoom[], folder: string): Promise<Pick | null> {
  const renderer = await createCliRenderer({ exitOnCtrlC: false, useMouse: false });
  return new Promise((resolve) => {
    createRoot(renderer).render(
      <Picker
        sessions={sessions}
        joined={joined}
        folder={folder}
        onChoose={(pick) => {
          renderer.destroy();
          resolve(pick);
        }}
      />,
    );
  });
}

export function describePick(pick: Pick): string {
  return pick.kind === "host" ? `${pick.info.title} (${pick.info.room})` : `joined room ${pick.room.room} (${rejoinLink(pick.room).split("?")[0]})`;
}
