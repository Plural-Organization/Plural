import { useKeyboard } from "@opentui/react";
import { useEffect, useMemo, useState } from "react";
import { figures, LOGO, LOGO_MINI, shrink, type Mark } from "../logo";
import { theme } from "../theme";
import { Spinner } from "./Spinner";

const FULL = figures(LOGO);
const SMALL = shrink(FULL);
const MINI = figures(LOGO_MINI);
const FIGURES = 4;
const FIRST_MS = 150;
const STAGGER_MS = 230;
const TITLE = "plural";
const TITLE_AT = FIRST_MS + FIGURES * STAGGER_MS;
const LETTER_MS = 55;
const DONE_MS = TITLE_AT + TITLE.length * LETTER_MS + 250;
const FRAME_MS = 40;

// A figure fades in through the theme's quiet colors, flashes the accent and settles on the text color.
function shade(figure: number, elapsed: number): string | undefined {
  const age = elapsed - FIRST_MS - figure * STAGGER_MS;
  if (figure < 0 || age < 0) {
    return undefined;
  }
  return age < 90 ? theme.line : age < 180 ? theme.dim : age < 420 ? theme.accent : theme.text;
}

export function Picture({ mark = MINI, elapsed = Infinity }: { mark?: Mark; elapsed?: number }) {
  const lines: { top: string | undefined; bottom: string | undefined }[][] = [];
  for (let y = 0; y < mark.length; y += 2) {
    lines.push(mark[y]!.map((id, x) => ({ top: shade(id, elapsed), bottom: shade(mark[y + 1]?.[x] ?? -1, elapsed) })));
  }
  return (
    <box flexDirection="column" alignItems="center">
      {lines.map((cells, row) => (
        <text key={row} wrapMode="none">
          {cells.map((cell, column) =>
            cell.top === undefined && cell.bottom === undefined ? (
              <span key={column}> </span>
            ) : cell.top === undefined ? (
              <span key={column} fg={cell.bottom}>
                ▄
              </span>
            ) : (
              <span key={column} fg={cell.top} bg={cell.bottom}>
                ▀
              </span>
            ),
          )}
        </text>
      ))}
    </box>
  );
}

interface SplashProps {
  width: number;
  height: number;
  version: string;
  ready: boolean;
  status: string;
  failure?: string | null;
  onDone: () => void;
  onQuit: () => void;
}

export function Splash({ width, height, version, ready, status, failure = null, onDone, onQuit }: SplashProps) {
  const [elapsed, setElapsed] = useState(0);
  const animating = elapsed < DONE_MS;

  useEffect(() => {
    if (!animating) {
      return;
    }
    const started = Date.now() - elapsed;
    const timer = setInterval(() => setElapsed(Date.now() - started), FRAME_MS);
    return () => clearInterval(timer);
  }, [animating]);

  useEffect(() => {
    if (!animating && ready) {
      onDone();
    }
  }, [animating, ready]);

  useKeyboard((key) => {
    key.preventDefault();
    if (key.ctrl && key.name === "c") {
      onQuit();
    } else if (failure !== null && (key.name === "return" || key.name === "escape")) {
      onQuit();
    } else if (animating) {
      setElapsed(DONE_MS);
    }
  });

  const mark = useMemo(() => {
    const fits = (candidate: Mark) => candidate[0]!.length + 4 <= width && Math.ceil(candidate.length / 2) + 6 <= height;
    return fits(FULL) ? FULL : fits(SMALL) ? SMALL : null;
  }, [width, height]);
  const letters = Math.max(0, Math.min(TITLE.length, Math.floor((elapsed - TITLE_AT) / LETTER_MS) + 1));

  return (
    <box width={width} height={height} flexDirection="column" alignItems="center" justifyContent="center" backgroundColor={theme.bg}>
      {mark ? <Picture mark={mark} elapsed={elapsed} /> : null}
      <box height={1} marginTop={1}>
        <text>
          <span fg={theme.text}>
            <b>{TITLE.slice(0, letters)}</b>
          </span>
          <span fg={theme.dim}>{letters === TITLE.length ? `  v${version}` : ""}</span>
        </text>
      </box>
      <box height={1}>
        {animating ? null : failure !== null ? (
          <text fg={theme.danger}>✗ could not join</text>
        ) : (
          <text fg={theme.dim}>
            <Spinner color={theme.accent} /> {status}
          </text>
        )}
      </box>
      {!animating && failure !== null ? (
        <box flexDirection="column" alignItems="center" marginTop={1} maxWidth={Math.max(20, width - 8)}>
          <text fg={theme.text}>{failure}</text>
          <text fg={theme.dim}>enter or ctrl+c to leave</text>
        </box>
      ) : null}
    </box>
  );
}
