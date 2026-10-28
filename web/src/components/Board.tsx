import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import type { BoardCursor, BoardShape, BoardStroke, Command } from "@plural/client";
import { boardImage, COLORS, drawLine, MAX_DEPTH, rounded, sameLine, textSize, thin, TOOLS, WIDTHS, type Line } from "../lib/board";
import { colorFor } from "../lib/colors";
import { cx } from "../lib/cx";
import styles from "./Board.module.css";

// The relay lets a guest send 20 messages a second, so the cursor goes out at most 10 times.
const CURSOR_MS = 100;
// A point closer than this to the last one, in board widths, adds nothing but bytes.
const MIN_STEP = 0.0015;
// A shape smaller than this is a slip of the mouse, not a shape.
const MIN_SHAPE = 0.01;
// A stroke the host has not confirmed by then was refused or changed on the way, so its copy goes.
const PENDING_MS = 6000;

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

interface Pending {
  line: Line;
  at: number;
}

export function Board({ strokes, pointers, meId, canDraw, isHost, send, sendPresence, onSendToAgent, onClose }: BoardProps) {
  const room = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const base = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef<Line | null>(null);
  const trails = useRef(new Map<string, number[]>());
  const erasing = useRef(new Set<string>());
  const placed = useRef(new WeakSet<object>());
  const cursorAt = useRef(0);
  const queued = useRef<BoardCursor | null | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [color, setColor] = useState(COLORS[1]!);
  const [width, setWidth] = useState(WIDTHS[1]!);
  const [tool, setTool] = useState<BoardShape>("pen");
  const [typing, setTyping] = useState<{ x: number; y: number; value: string } | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [frame, setFrame] = useState(0);
  const [baseVersion, setBaseVersion] = useState(0);
  const redraw = () => setFrame((value) => value + 1);
  const scale = size.width;

  // The board fills the panel; its height in widths depends on the screen, never past MAX_DEPTH.
  useLayoutEffect(() => {
    const element = room.current;
    if (!element) {
      return;
    }
    const fit = () => {
      const box = element.getBoundingClientRect();
      setSize({ width: box.width, height: Math.min(box.height, box.width * MAX_DEPTH) });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    fit();
    return () => observer.disconnect();
  }, []);

  // A stroke the host confirmed replaces the copy drawn while it travelled; an old copy is dropped.
  useEffect(() => {
    setPending((current) => current.filter((item) => !strokes.some((stroke) => stroke.author_id === meId && sameLine(stroke, item.line))));
    erasing.current.forEach((id) => strokes.some((stroke) => stroke.id === id) || erasing.current.delete(id));
  }, [strokes, meId]);
  useEffect(() => {
    if (pending.length === 0) {
      return;
    }
    const check = setInterval(() => setPending((current) => current.filter((item) => Date.now() - item.at < PENDING_MS)), 1000);
    return () => clearInterval(check);
  }, [pending.length]);

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

  // Confirmed strokes are drawn once into a layer of their own; a move repaints only what is live.
  useEffect(() => {
    if (scale === 0) {
      return;
    }
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const layer = (base.current ??= document.createElement("canvas"));
    layer.width = Math.round(size.width * ratio);
    layer.height = Math.round(size.height * ratio);
    const context = layer.getContext("2d")!;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    strokes.forEach((stroke) => drawLine(context, stroke, scale));
    setBaseVersion((value) => value + 1);
  }, [strokes, size]);

  useEffect(() => {
    const element = canvas.current;
    const layer = base.current;
    if (!element || !layer || scale === 0) {
      return;
    }
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (element.width !== layer.width || element.height !== layer.height) {
      element.width = layer.width;
      element.height = layer.height;
    }
    const context = element.getContext("2d")!;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, element.width, element.height);
    context.drawImage(layer, 0, 0);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    pending.forEach((item) => drawLine(context, item.line, scale));
    for (const pointer of pointers) {
      const trail = trails.current.get(pointer.id);
      if (trail && trail.length >= 2) {
        drawLine(context, { color: pointer.cursor.color ?? colorFor(pointer.id), width: pointer.cursor.width ?? WIDTHS[1]!, points: trail }, scale);
      }
    }
    if (drawing.current) {
      drawLine(context, drawing.current, scale);
    }
  }, [baseVersion, pending, frame]);

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  const at = (event: PointerEvent) => {
    const rect = canvas.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(MAX_DEPTH, Math.max(0, (event.clientY - rect.top) / rect.width)),
    };
  };

  // The cursor goes out at most every CURSOR_MS, always ending on its latest position.
  const flush = () => {
    timer.current = null;
    if (queued.current !== undefined) {
      sendPresence({ type: "presence.cursor", cursor: queued.current });
      cursorAt.current = Date.now();
      queued.current = undefined;
    }
  };
  const share = (cursor: BoardCursor | null, now = false) => {
    queued.current = cursor;
    const wait = CURSOR_MS - (Date.now() - cursorAt.current);
    if (now || wait <= 0) {
      if (timer.current) {
        clearTimeout(timer.current);
      }
      flush();
    } else {
      timer.current ??= setTimeout(flush, wait);
    }
  };
  const cursor = (x: number, y: number, ink: boolean): BoardCursor => ({ x, y, ink, color: ink ? color : null, width: ink ? width : null });

  const place = (line: Line) => {
    const points = rounded(line.points);
    setPending((current) => [...current, { line: { ...line, points }, at: Date.now() }]);
    send({
      type: "board.draw",
      kind: line.kind ?? "pen",
      text: line.text ?? null,
      color: line.color,
      width: line.width,
      points: points as [number, number, ...number[]],
    });
  };

  // Enter and a click elsewhere both end a text; each one is placed once, and a newer text box stays open.
  const commitText = () => {
    const current = typing;
    if (current === null || placed.current.has(current)) {
      return;
    }
    placed.current.add(current);
    const value = current.value.trim();
    if (value !== "") {
      place({ kind: "text", text: [...value].slice(0, 500).join(""), color, width, points: [current.x, current.y] });
    }
    setTyping((open) => (open === current ? null : open));
  };

  const down = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!canDraw || event.button !== 0) {
      return;
    }
    const { x, y } = at(event);
    if (tool === "text") {
      event.preventDefault();
      commitText();
      setTyping({ x, y, value: "" });
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    drawing.current = { kind: tool, color, width, points: tool === "pen" ? [x, y] : [x, y, x, y] };
    share(cursor(x, y, tool === "pen"), true);
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
      if (Math.hypot(x - points.at(-2)!, y - points.at(-1)!) >= MIN_STEP) {
        points.push(x, y);
        redraw();
      }
    }
    share(cursor(x, y, line !== null && line.kind === "pen"));
  };

  const up = (event: PointerEvent<HTMLCanvasElement>) => {
    const line = drawing.current;
    drawing.current = null;
    if (!line) {
      return;
    }
    const { x, y } = at(event);
    const slip = line.kind !== "pen" && Math.hypot(line.points[2]! - line.points[0]!, line.points[3]! - line.points[1]!) < MIN_SHAPE;
    // The stroke goes before the pen lifts, so the others' trail turns into the stroke without a gap.
    if (!slip) {
      place({ ...line, points: line.kind === "pen" ? thin(line.points) : line.points });
    }
    share(cursor(x, y, false), true);
    redraw();
  };

  const mine = strokes.filter((stroke) => stroke.author_id === meId && !erasing.current.has(stroke.id));
  const undo = () => {
    const last = mine.at(-1);
    if (last) {
      erasing.current.add(last.id);
      send({ type: "board.erase", stroke_id: last.id });
      redraw();
    }
  };

  const toAgent = () =>
    void boardImage([...strokes, ...pending.map((item) => item.line)])
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
          <>
            <button className="button small ghost" type="button" onClick={() => send({ type: "board.open", open: false })} title="Close the board for everyone">
              close for all
            </button>
            <button className="button small primary" type="button" onClick={toAgent} disabled={strokes.length + pending.length === 0}>
              send to agent
            </button>
          </>
        ) : null}
        <button className="button small ghost" type="button" onClick={onClose} aria-label="Hide the board" title="Hide the board for you">
          ✕
        </button>
      </header>
      <div ref={room} className={styles.room}>
        <div className={styles.stage} style={{ height: size.height }}>
          <canvas
            ref={canvas}
            className={cx(styles.canvas, canDraw && (tool === "text" ? styles.texting : styles.drawable))}
            style={{ width: size.width, height: size.height }}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={up}
            onPointerLeave={() => (drawing.current ? undefined : share(null, true))}
          />
          {typing ? (
            <textarea
              autoFocus
              className={styles.typing}
              value={typing.value}
              rows={1}
              placeholder="type, enter to place"
              style={{ left: typing.x * scale, top: typing.y * scale, color, fontSize: textSize(width, scale) }}
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
          {pointers.map(({ id, name, cursor: where }) => (
            <div key={id} className={styles.pointer} style={{ left: where.x * scale, top: where.y * scale, "--who": colorFor(id) } as CSSProperties} aria-hidden="true">
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
