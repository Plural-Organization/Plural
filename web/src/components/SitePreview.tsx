import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { BoardCursor, Command } from "@plural/client";
import { bridgeScript, readFrame, TO_FRAME, type PickedComponent, type ToFrame } from "../lib/bridge";
import { colorFor } from "../lib/colors";
import { componentPrompt } from "../lib/quote";
import { buildSite, localTarget, siteEntries, type Site } from "../lib/site";
import { cx } from "../lib/cx";
import type { Pointer } from "./Board";
import styles from "./SitePreview.module.css";

// The pointer goes out at most this often, like on the board: the relay allows a guest 20 messages a second.
const CURSOR_MS = 100;
const REBUILD_MS = 250;
const NOTE_WIDTH = 320;
const NOTE_HEIGHT = 120;

interface SitePreviewProps {
  entry: string;
  site: Site;
  pointers: Pointer[];
  // My own pointer as the host sent it back.
  echo: BoardCursor | undefined;
  canPick: boolean;
  sendPresence: (command: Command) => boolean;
  onAsk: (text: string) => void;
  onNotice: (text: string) => void;
}

export function SitePreview({ entry, site, pointers, echo, canPick, sendPresence, onAsk, onNotice }: SitePreviewProps) {
  const frame = useRef<HTMLIFrameElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(entry);
  const [built, setBuilt] = useState<{ html: string; problems: string[] } | null>(null);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<PickedComponent | null>(null);
  const [note, setNote] = useState("");
  const scrolled = useRef(0);
  const root = entry.includes("/") ? entry.slice(0, entry.lastIndexOf("/")) : "";

  useEffect(() => {
    setPage(entry);
    scrolled.current = 0;
  }, [entry]);

  // The page is rebuilt from the files whenever the agent changes one, keeping the scroll.
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      void buildSite(site.files, page, bridgeScript(scrolled.current), root).then((next) => {
        if (alive) {
          setBuilt(next);
          setError(null);
        }
      });
    }, built === null ? 0 : REBUILD_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [site.version, page, reload]);

  const tell = (message: ToFrame) => frame.current?.contentWindow?.postMessage({ from: TO_FRAME, ...message }, "*");

  const cursors = JSON.stringify(pointers.map(({ id, name, cursor }) => ({ id, name, color: colorFor(id), x: cursor.x, y: cursor.y })));
  const resend = () => {
    tell({ type: "cursors", list: JSON.parse(cursors) });
    tell({ type: "pick", on: picking });
  };
  useEffect(resend, [cursors, picking]);

  // My own pointer, at most every CURSOR_MS and always ending on where it last was.
  const queued = useRef<BoardCursor | null | undefined>(undefined);
  const sentAt = useRef(0);
  const pointed = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flush = () => {
    timer.current = null;
    if (queued.current !== undefined) {
      pointed.current ||= queued.current !== null;
      sendPresence({ type: "presence.cursor", cursor: queued.current });
      sentAt.current = Date.now();
      queued.current = undefined;
    }
  };
  // A host older than the preview drops the surface and would put this pointer on everyone's board.
  // Only an echo that follows a pointer sent from here tells; one left from the board does not.
  const unknown = useRef(false);
  useEffect(() => {
    if (pointed.current && echo && echo.surface !== "preview" && !unknown.current) {
      unknown.current = true;
      sendPresence({ type: "presence.cursor", cursor: null });
    }
  }, [echo]);
  const share = (cursor: BoardCursor | null) => {
    if (unknown.current) {
      return;
    }
    queued.current = cursor;
    if (timer.current === null) {
      timer.current = setTimeout(flush, Math.max(0, CURSOR_MS - (Date.now() - sentAt.current)));
    }
  };
  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
      }
      sendPresence({ type: "presence.cursor", cursor: null });
    },
    [],
  );

  const closeNote = () => {
    setPicked(null);
    setNote("");
    tell({ type: "unmark" });
  };

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow) {
        return;
      }
      const message = readFrame(event.data);
      if (message === null) {
        return;
      }
      switch (message.type) {
        case "cursor":
          share(message.x === null ? null : { x: round(message.x), y: round(message.y), ink: false, color: null, width: null, surface: "preview" });
          break;
        case "scroll":
          scrolled.current = message.y;
          break;
        case "picked":
          if (canPick) {
            setPicked(message.component);
            setPicking(false);
          }
          break;
        case "pick-cancel":
          setPicking(false);
          break;
        case "navigate": {
          const target = localTarget(page, message.href, root);
          const html = target === null ? null : [target, `${target}/index.html`].find((path) => siteEntries(site.files).includes(path) || site.files.has(path));
          if (html && /\.html?$/.test(html)) {
            scrolled.current = 0;
            closeNote();
            setPage(html);
          } else {
            onNotice(`${message.href} is not a page the agent wrote`);
          }
          break;
        }
        case "external":
          onNotice(`the preview does not open other sites: ${message.href}`);
          break;
        case "error":
          setError(message.message);
          break;
      }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [page, site, canPick]);

  const send = () => {
    if (picked === null || note.trim() === "") {
      return;
    }
    onAsk(componentPrompt(page, picked, note));
    closeNote();
  };

  const width = box.current?.clientWidth ?? 600;
  const height = box.current?.clientHeight ?? 600;
  const below = picked !== null && picked.rect.bottom + 8 + NOTE_HEIGHT <= height;
  const notePlace: CSSProperties | undefined =
    picked === null
      ? undefined
      : {
          left: Math.max(8, Math.min(width - NOTE_WIDTH - 8, picked.rect.left)),
          top: below ? Math.max(8, picked.rect.bottom + 8) : Math.max(8, Math.min(height - NOTE_HEIGHT - 8, picked.rect.top - NOTE_HEIGHT - 8)),
        };
  const problems = [...(built?.problems ?? []), ...(error ? [error] : [])];

  return (
    <div className={styles.preview} ref={box} onPointerLeave={() => share(null)}>
      {built !== null ? (
        <iframe
          ref={frame}
          className={cx(styles.frame, picking && styles.picking)}
          title={`Preview of ${page}`}
          sandbox="allow-scripts allow-forms"
          srcDoc={built.html}
          onLoad={resend}
        />
      ) : (
        <div className={styles.loading}>building the page…</div>
      )}
      <div className={styles.tools}>
        {page !== entry ? (
          <button className="button small ghost" type="button" onClick={() => setPage(entry)} title={`Back to ${entry}`}>
            ← {entry.split("/").pop()}
          </button>
        ) : null}
        <button className="button small ghost" type="button" onClick={() => setReload((value) => value + 1)} aria-label="Reload the page" title="Reload the page">
          ↻
        </button>
        {canPick ? (
          <button
            className={cx("button small", !picking && "ghost", picking && styles.on)}
            type="button"
            aria-pressed={picking}
            onClick={() => {
              closeNote();
              setPicking((value) => !value);
            }}
            title="Point at a part of the page to ask the agent about it"
          >
            {picking ? "click a component · esc" : "◎ pick"}
          </button>
        ) : null}
      </div>
      {picked !== null ? (
        <form
          className={styles.note}
          style={notePlace}
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          <code className={styles.what} title={picked.selector}>
            {picked.selector || picked.tag}
          </code>
          <textarea
            autoFocus
            rows={2}
            value={note}
            placeholder="What should the agent change here?"
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                closeNote();
              } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                send();
              }
            }}
          />
          <div className={styles.noteBar}>
            <button className="button small ghost" type="button" onClick={closeNote}>
              cancel
            </button>
            <button className="button small" type="submit" disabled={note.trim() === ""}>
              send to agent
            </button>
          </div>
        </form>
      ) : null}
      {problems.length > 0 ? (
        <div className={styles.problems} role="status">
          {problems.slice(0, 3).map((problem) => (
            <div key={problem}>{problem}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const round = (value: number) => Math.round(value * 10_000) / 10_000;
