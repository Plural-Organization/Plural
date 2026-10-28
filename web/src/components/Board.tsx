import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import type { BoardCursor, BoardShape, BoardStroke, Command } from "@plural/client";
import { BOARD_RATIO, boardImage, COLORS, drawLine, sameLine, textSize, thin, TOOLS, WIDTHS, type Line } from "../lib/board";
import { colorFor } from "../lib/colors";
import { cx } from "../lib/cx";
import styles from "./Board.module.css";

const CURSOR_MS = 40;
// A point closer than this to the last one adds nothing but bytes.
const MIN_STEP = 0.0015;
// A shape smaller than this is a slip of the mouse, not a shape.
const MIN_SHAPE = 0.01;

const ICONS: Record<BoardShape, string> = {
  pen: "M4 20l4-1L19 8l-3-3L5 16l-1 4z",
  line: "M5 19L19 5",
  arrow: "M5 19L19 5M19 5h-7M19 5v7",
  rect: "M4 6h16v12H4z",
  ellipse: "M12 5c4.4 0 8 3.1 8 7s-3.6 7-8 7-8-3.1-8-7 3.6-7 8-7z",
  text: "M5 6V5h14v1M12 5v14M9 19h6",
};

export interface Pointer {
  id: string;
  name: string;
  cursor: BoardCursor;
}

interface BoardProps {
  strokes: BoardStroke[];
  pointers: Pointer[];
  meId: string | null;
  canDraw: boolean;
  isHost: boolean;
  send: (command: Command) => void;
  sendPresence: (command: Command) => boolean;
  onSendToAgent: (image: Blob) => void;
  onClose: () => void;
}

export function Board({ strokes, pointers, meId, canDraw, isHost, send, sendPresence, onSendToAgent, onClose }: BoardProps) {
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef<Line | null>(null);
  const lastCursor = useRef(0);
  const trails = useRef(new Map<string, number[]>());
  const [color, setColor] = useState(COLORS[1]!);
  const [width, setWidth] = useState(WIDTHS[1]!);
  const [tool, setTool] = useState<BoardShape>("pen");
  const [typing, setTyping] = useState<{ x: number; y: number; value: string } | null>(null);
  const [pending, setPending] = useState<Line[]>([]);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [frame, setFrame] = useState(0);
  const redraw = () => setFrame((value) => value + 1);

  // The stage keeps 16:10 inside whatever room the panel has.
  useLayoutEffect(() => {
    const element = stage.current?.parentElement;
    if (!element) {
      return;
    }
    const fit = () => {
      const room = element.getBoundingClientRect();
      const width = Math.max(0, Math.min(room.width - 32, (room.height - 32) * BOARD_RATIO));
      setSize({ width, height: width / BOARD_RATIO });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    fit();
    return () => observer.disconnect();
  }, []);

  // A stroke the host confirmed replaces the copy drawn while it travelled.
  useEffect(() => {
    setPending((current) => current.filter((line) => !strokes.some((stroke) => stroke.author_id === meId && sameLine(stroke, line))));
  }, [strokes, meId]);

  // Others' pens leave a trail from their cursor until their stroke arrives.
  const pointerKey = JSON.stringify(pointers.map((pointer) => [pointer.id, pointer.cursor]));
  useEffect(() => {
    const seen = new Set<string>();
    for (const { id, cursor } of pointers) {
      seen.add(id);
      if (!cursor.ink) {
        trails.current.delete(id);
        continue;
      }
      const trail = trails.current.get(id) ?? [];
      if (trail.at(-2) !== cursor.x || trail.at(-1) !== cursor.y) {
        trail.push(cursor.x, cursor.y);
      }
      trails.current.set(id, trail);
    }
    [...trails.current.keys()].filter((id) => !seen.has(id)).forEach((id) => trails.current.delete(id));
    redraw();
  }, [pointerKey]);

  useEffect(() => {
    const element = canvas.current;
    if (!element || size.width === 0) {
      return;
    }
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    element.width = Math.round(size.width * scale);
    element.height = Math.round(size.height * scale);
    const context = element.getContext("2d")!;
    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    const lines: Line[] = [...strokes, ...pending];
    for (const pointer of pointers) {
      const trail = trails.current.get(pointer.id);
      if (trail && trail.length >= 2) {
        lines.push({ color: pointer.cursor.color ?? colorFor(pointer.id), width: pointer.cursor.width ?? WIDTHS[1]!, points: trail });
      }
    }
    if (drawing.current) {
      lines.push(drawing.current);
    }
    lines.forEach((line) => drawLine(context, line, size.width, size.height));
  }, [strokes, pending, size, frame]);

  const at = (event: PointerEvent) => {
    const rect = canvas.current!.getBoundingClientRect();
    const clamp = (value: number) => Math.min(1, Math.max(0, value));
    return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) };
  };

  const share = (x: number, y: number, ink: boolean, force = false) => {
    const now = Date.now();
    if (!force && now - lastCursor.current < CURSOR_MS) {
      return;
    }
    lastCursor.current = now;
    sendPresence({ type: "presence.cursor", cursor: { x, y, ink, color: ink ? color : null, width: ink ? width : null } });
  };

  const down = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!canDraw || event.button !== 0) {
      return;
    }
    const { x, y } = at(event);
    if (tool === "text") {
      event.preventDefault();
      setTyping({ x, y, value: "" });
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    drawing.current = { kind: tool, color, width, points: tool === "pen" ? [x, y] : [x, y, x, y] };
    share(x, y, tool === "pen", true);
    redraw();
  };

  const move = (event: PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = at(event);
    const line = drawing.current;
    if (line && line.kind !== "pen") {
      line.points[2] = x;
      line.points[3] = y;
      redraw();
    } else if (line) {
      const points = line.points;
      if (Math.hypot(x - points.at(-2)!, (y - points.at(-1)!) * BOARD_RATIO) >= MIN_STEP) {
        points.push(x, y);
        redraw();
      }
    }
    share(x, y, line !== null && line.kind === "pen");
  };

  const up = (event: PointerEvent<HTMLCanvasElement>) => {
    const line = drawing.current;
    drawing.current = null;
    if (!line) {
      return;
    }
    const { x, y } = at(event);
    share(x, y, false, true);
    if (line.kind !== "pen" && Math.hypot(line.points[2]! - line.points[0]!, line.points[3]! - line.points[1]!) < MIN_SHAPE) {
      redraw();
      return;
    }
    place({ ...line, points: line.kind === "pen" ? thin(line.points) : line.points });
  };

  const place = (line: Line) => {
    setPending((current) => [...current, line]);
    send({
      type: "board.draw",
      kind: line.kind ?? "pen",
      text: line.text ?? null,
      color: line.color,
      width: line.width,
      points: line.points as [number, number, ...number[]],
    });
  };

  // Enter and a click elsewhere both end a text; each one is placed once, and a newer text box stays open.
  const placed = useRef(new WeakSet<object>());
  const commitText = () => {
    const current = typing;
    if (current === null || placed.current.has(current)) {
      return;
    }
    placed.current.add(current);
    const value = current.value.trim();
    if (value !== "") {
      place({ kind: "text", text: value.slice(0, 500), color, width, points: [current.x, current.y] });
    }
    setTyping((open) => (open === current ? null : open));
  };

  const mine = strokes.filter((stroke) => stroke.author_id === meId);
  const undo = () => {
    const last = mine.at(-1);
    if (last) {
      send({ type: "board.erase", stroke_id: last.id });
    }
  };

  const toAgent = () =>
    void boardImage([...strokes, ...pending])
      .then(onSendToAgent)
      .catch(() => undefined);

  return (
    <aside className={styles.board} aria-label="Board">
      <header className={styles.bar}>
        <span className={styles.title}>board</span>
        {canDraw ? (
          <>
            <div className={styles.tools} role="radiogroup" aria-label="Tool">
              {TOOLS.map((item) => (
                <button
                  key={item.kind}
                  type="button"
                  role="radio"
                  aria-checked={item.kind === tool}
                  aria-label={item.label}
                  title={item.label}
                  className={cx(styles.tool, item.kind === tool && styles.picked)}
                  onClick={() => setTool(item.kind)}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={ICONS[item.kind]} />
                  </svg>
                </button>
              ))}
            </div>
            <div className={styles.swatches} role="radiogroup" aria-label="Pen color">
              {COLORS.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={value === color}
                  aria-label={value}
                  className={cx(styles.swatch, value === color && styles.picked)}
                  style={{ "--swatch": value } as CSSProperties}
                  onClick={() => setColor(value)}
                />
              ))}
            </div>
            <div className={styles.widths} role="radiogroup" aria-label="Pen width">
              {WIDTHS.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={value === width}
                  aria-label={`width ${value}`}
                  className={cx(styles.width, value === width && styles.picked)}
                  onClick={() => setWidth(value)}
                >
                  <span style={{ width: value + 2, height: value + 2, background: color }} />
                </button>
              ))}
            </div>
            <button className="button small ghost" type="button" onClick={undo} disabled={mine.length === 0}>
              undo
            </button>
          </>
        ) : (
          <span className={styles.note}>viewers watch the board</span>
        )}
        <span className="grow" />
        {isHost ? (
          <button className="button small ghost" type="button" onClick={() => send({ type: "board.clear" })} disabled={strokes.length === 0}>
            clear
          </button>
        ) : null}
        {canDraw ? (
          <button className="button small primary" type="button" onClick={toAgent} disabled={strokes.length + pending.length === 0}>
            send to agent
          </button>
        ) : null}
        <button className="button small ghost" type="button" onClick={onClose} aria-label="Close the board">
          ✕
        </button>
      </header>
      <div className={styles.room}>
        <div ref={stage} className={styles.stage} style={{ width: size.width, height: size.height }}>
          <canvas
            ref={canvas}
            className={cx(styles.canvas, canDraw && (tool === "text" ? styles.texting : styles.drawable))}
            style={{ width: size.width, height: size.height }}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={up}
            onPointerLeave={() => (drawing.current ? undefined : sendPresence({ type: "presence.cursor", cursor: null }))}
          />
          {typing ? (
            <textarea
              autoFocus
              className={styles.typing}
              value={typing.value}
              rows={1}
              placeholder="type, enter to place"
              style={{ left: `${typing.x * 100}%`, top: `${typing.y * 100}%`, color, fontSize: textSize(width, size.width) }}
              onChange={(event) => setTyping({ ...typing, value: event.target.value })}
              onBlur={commitText}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  commitText();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  setTyping(null);
                }
              }}
            />
          ) : null}
          {pointers.map(({ id, name, cursor }) => (
            <div
              key={id}
              className={styles.pointer}
              style={{ left: `${cursor.x * 100}%`, top: `${cursor.y * 100}%`, "--who": colorFor(id) } as CSSProperties}
              aria-hidden="true"
            >
              <svg width="16" height="18" viewBox="0 0 16 18">
                <path d="M1 1 L1 15 L5 11 L8 17 L10.5 16 L7.5 10 L13 10 Z" />
              </svg>
              <span>{name}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
