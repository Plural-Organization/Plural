import { useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type CSSProperties, type DragEvent, type PointerEvent } from "react";
import type { BoardCursor, BoardStroke, Command } from "@plural/client";
import {
  boardImage,
  bounds,
  COLORS,
  drawLine,
  eraserWidth,
  hasCorners,
  MAX_DEPTH,
  picks,
  rounded,
  sameLine,
  shifted,
  textSize,
  thin,
  TOOLS,
  WIDTHS,
  type Line,
  type Pictures,
  type Tool,
} from "../lib/board";
import { colorFor } from "../lib/colors";
import { cx } from "../lib/cx";
import styles from "./Board.module.css";

// The relay lets a guest send 20 messages a second, so the cursor goes out at most 10 times.
const CURSOR_MS = 100;
// A point closer than this to the last one, in board widths, adds nothing but bytes.
const MIN_STEP = 0.0015;
// A shape smaller than this is a slip of the mouse, not a shape.
const MIN_SHAPE = 0.01;
// A stroke or a move the host has not confirmed by then was refused or changed on the way.
const PENDING_MS = 6000;
// Deleting sends one mark at a time, spaced under the relay's rate limit.
const DELETE_MS = 110;
// Below the lowest mark the board keeps this much room, in widths, to draw on; the panel scrolls.
const ROOM_BELOW = 0.35;
// How close to a mark or a handle a click counts, in pixels.
const REACH_PX = 8;
// A new picture takes this share of the board's width.
const PICTURE_WIDTH = 0.4;
const PICTURE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
// The board zooms between half and three times the panel's width.
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 1.25;
// A canvas stays within what browsers draw reliably: 8192 pixels a side and 40 million in all.
const MAX_SIDE_PX = 8192;
const MAX_AREA_PX = 40_000_000;

const ICONS: Record<Tool, string> = {
  select: "M5 3l14 8-6 2-3 6L5 3z",
  pen: "M4 20l4-1L19 8l-3-3L5 16l-1 4z",
  line: "M5 19L19 5",
  arrow: "M5 19L19 5M19 5h-7M19 5v7",
  rect: "M4 6h16v12H4z",
  ellipse: "M12 5c4.4 0 8 3.1 8 7s-3.6 7-8 7-8-3.1-8-7 3.6-7 8-7z",
  text: "M5 6V5h14v1M12 5v14M9 19h6",
  eraser: "M16 3l5 5-10 10H6l-3-3L16 3zM6 18h14",
  delete: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
};
const PICTURE_ICON = "M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5M15 9.5a1 1 0 1 0 0-.01";

export function FullIcon({ full }: { full: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={full ? "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" : "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"} />
    </svg>
  );
}

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
  pictures: Record<string, string>;
  fetchPicture: (attachmentId: string) => void;
  uploadPicture: (file: Blob, name: string) => Promise<string | null>;
  send: (command: Command) => void;
  sendPresence: (command: Command) => boolean;
  onSendToAgent: (image: Blob) => void;
  onNotice: (text: string) => void;
  onClose: () => void;
  full: boolean;
  onToggleFull: () => void;
}

interface Pending {
  line: Line;
  at: number;
}

// A drag of the select tool: moving a mark, or pulling one of its corner handles.
interface Drag {
  id: string;
  handle: number | null;
  from: { x: number; y: number };
  points: number[];
}

// The handles of a mark: a line's two ends, or a box's four corners clockwise from the top left.
function handlesOf(line: Line): number[][] {
  if (line.kind === "line" || line.kind === "arrow") {
    return [
      [line.points[0]!, line.points[1]!],
      [line.points[2]!, line.points[3]!],
    ];
  }
  const [left, top, right, bottom] = bounds(line);
  return [
    [left, top],
    [right, top],
    [right, bottom],
    [left, bottom],
  ];
}

// The cursor over a handle: diagonal arrows on a box's corners, a grab on a line's ends.
function handleCursor(line: Line, handle: number): string {
  if (line.kind === "line" || line.kind === "arrow") {
    return "grab";
  }
  return handle === 0 || handle === 2 ? "nwse-resize" : "nesw-resize";
}

function resized(line: Line, handle: number, x: number, y: number): number[] {
  if (line.kind === "line" || line.kind === "arrow") {
    const points = [...line.points];
    points[handle * 2] = x;
    points[handle * 2 + 1] = y;
    return points;
  }
  let [left, top, right, bottom] = bounds(line);
  if (handle === 0 || handle === 3) left = x;
  if (handle === 1 || handle === 2) right = x;
  if (handle === 0 || handle === 1) top = y;
  if (handle === 2 || handle === 3) bottom = y;
  return [Math.min(left, right), Math.min(top, bottom), Math.max(left, right), Math.max(top, bottom)];
}

export function Board(props: BoardProps) {
  const { strokes, pointers, meId, canDraw, isHost, pictures, fetchPicture, uploadPicture, send, sendPresence, onSendToAgent, onNotice, onClose, full, onToggleFull } = props;
  const room = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const base = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef<Line | null>(null);
  const drag = useRef<Drag | null>(null);
  const trails = useRef(new Map<string, number[]>());
  const deleting = useRef(new Set<string>());
  const deleteQueue = useRef<string[]>([]);
  const sweeping = useRef(false);
  const placed = useRef(new WeakSet<object>());
  const images = useRef(new Map<string, HTMLImageElement>());
  const cursorAt = useRef(0);
  const queued = useRef<BoardCursor | null | undefined>(undefined);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [color, setColor] = useState(COLORS[1]!);
  const [width, setWidth] = useState(WIDTHS[1]!);
  const [tool, setTool] = useState<Tool>("pen");
  const [selected, setSelected] = useState<string | null>(null);
  // What the select tool's cursor shows: a hand over a mark, arrows over a handle, a closed hand while dragging.
  const [pointerStyle, setPointerStyle] = useState<string | undefined>(undefined);
  const [moving, setMoving] = useState<{ id: string; points: number[] } | null>(null);
  const [moved, setMoved] = useState<Record<string, { points: number[]; at: number }>>({});
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [typing, setTyping] = useState<{ x: number; y: number; value: string } | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [view, setView] = useState({ width: 0, height: 0 });
  const [frame, setFrame] = useState(0);
  const [loaded, setLoaded] = useState(0);
  const [baseVersion, setBaseVersion] = useState(0);
  const redraw = () => setFrame((value) => value + 1);

  // What the board shows: the host's strokes, with a move still on its way already in place.
  const shown: BoardStroke[] = strokes.map((stroke) => (moved[stroke.id] ? { ...stroke, points: moved[stroke.id]!.points as BoardStroke["points"] } : stroke));
  const byId = (id: string | null) => shown.find((stroke) => stroke.id === id) ?? null;
  const editable = (stroke: BoardStroke) => stroke.author_id === meId || isHost;

  // The board spans the panel's width and runs as deep as its lowest mark needs, the panel scrolling.
  const deepest = Math.max(0, ...shown.flatMap((stroke) => stroke.points.filter((_, index) => index % 2 === 1)));
  const [zoom, setZoom] = useState(1);
  const zoomAnchor = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const boardWidth = view.width * zoom;
  const size = { width: boardWidth, height: Math.min(boardWidth * MAX_DEPTH, Math.max(view.height, (deepest + ROOM_BELOW) * boardWidth)) };
  const scale = size.width;
  // Sharp on a retina screen, but never a canvas too large for the browser when zoomed in far.
  const pixelRatio = () =>
    Math.max(0.5, Math.min(window.devicePixelRatio || 1, 2, MAX_SIDE_PX / Math.max(1, size.width), MAX_SIDE_PX / Math.max(1, size.height), Math.sqrt(MAX_AREA_PX / Math.max(1, size.width * size.height))));

  // Zooming keeps the point under the pointer (or the middle of the view) where it was.
  const zoomTo = (next: number, at?: { clientX: number; clientY: number }) => {
    const element = room.current;
    const target = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next));
    if (!element || scale === 0 || target === zoom) {
      return;
    }
    const box = element.getBoundingClientRect();
    const left = at ? at.clientX - box.left : element.clientWidth / 2;
    const top = at ? at.clientY - box.top : element.clientHeight / 2;
    zoomAnchor.current = { x: (element.scrollLeft + left) / scale, y: (element.scrollTop + top) / scale, left, top };
    setZoom(target);
  };
  useLayoutEffect(() => {
    const element = room.current;
    const anchor = zoomAnchor.current;
    if (element && anchor) {
      element.scrollLeft = anchor.x * scale - anchor.left;
      element.scrollTop = anchor.y * scale - anchor.top;
      zoomAnchor.current = null;
    }
  }, [zoom]);
  const reach = scale > 0 ? REACH_PX / scale : 0.01;
  const picture: Pictures = (id) => {
    const image = images.current.get(id);
    return image?.complete && image.naturalWidth > 0 ? image : undefined;
  };

  useLayoutEffect(() => {
    const element = room.current;
    if (!element) {
      return;
    }
    const fit = () => setView({ width: element.clientWidth, height: element.getBoundingClientRect().height });
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    fit();
    return () => observer.disconnect();
  }, []);

  // Pictures on the board are asked for once and drawn when they load.
  useEffect(() => {
    for (const stroke of strokes) {
      const id = stroke.image;
      if (!id || images.current.has(id)) {
        continue;
      }
      const url = pictures[id];
      if (!url) {
        fetchPicture(id);
        continue;
      }
      const image = new Image();
      image.onload = () => setLoaded((value) => value + 1);
      image.src = url;
      images.current.set(id, image);
    }
  }, [strokes, pictures]);

  // A stroke or a move the host confirmed replaces the copy drawn while it travelled; an old copy goes.
  useEffect(() => {
    setPending((current) => current.filter((item) => !strokes.some((stroke) => stroke.author_id === meId && sameLine(stroke, item.line))));
    setMoved((current) => {
      const kept = Object.entries(current).filter(([id, item]) => {
        const stroke = strokes.find((candidate) => candidate.id === id);
        return stroke !== undefined && !sameLine(stroke, { ...stroke, points: item.points });
      });
      return kept.length === Object.keys(current).length ? current : Object.fromEntries(kept);
    });
    deleting.current.forEach((id) => strokes.some((stroke) => stroke.id === id) || deleting.current.delete(id));
    setHidden((current) => (current.size === 0 ? current : new Set([...current].filter((id) => strokes.some((stroke) => stroke.id === id)))));
    setSelected((current) => (current && strokes.some((stroke) => stroke.id === current) ? current : null));
  }, [strokes, meId]);
  useEffect(() => {
    if (pending.length === 0 && Object.keys(moved).length === 0) {
      return;
    }
    const check = setInterval(() => {
      setPending((current) => current.filter((item) => Date.now() - item.at < PENDING_MS));
      setMoved((current) => Object.fromEntries(Object.entries(current).filter(([, item]) => Date.now() - item.at < PENDING_MS)));
    }, 1000);
    return () => clearInterval(check);
  }, [pending.length, Object.keys(moved).length]);

  // Deleted marks leave one by one; one the host keeps after a while comes back into view.
  useEffect(() => {
    const tick = setInterval(() => {
      const next = deleteQueue.current.shift();
      if (next === undefined) {
        return;
      }
      send({ type: "board.erase", stroke_id: next });
      setTimeout(() => {
        deleting.current.delete(next);
        setHidden((current) => {
          if (!current.has(next)) {
            return current;
          }
          const kept = new Set(current);
          kept.delete(next);
          return kept;
        });
      }, PENDING_MS);
    }, DELETE_MS);
    return () => clearInterval(tick);
  }, [send]);

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

  // Settled marks are drawn once into a layer of their own; a pointer move repaints only what is live.
  const movedKey = JSON.stringify(moved);
  useEffect(() => {
    if (scale === 0) {
      return;
    }
    const ratio = pixelRatio();
    const layer = (base.current ??= document.createElement("canvas"));
    layer.width = Math.round(size.width * ratio);
    layer.height = Math.round(size.height * ratio);
    const context = layer.getContext("2d")!;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    shown.filter((stroke) => !hidden.has(stroke.id) && stroke.id !== moving?.id).forEach((stroke) => drawLine(context, stroke, scale, picture));
    setBaseVersion((value) => value + 1);
  }, [strokes, size.width, size.height, hidden, movedKey, moving?.id, loaded]);

  useEffect(() => {
    const element = canvas.current;
    const layer = base.current;
    if (!element || !layer || scale === 0) {
      return;
    }
    const ratio = pixelRatio();
    if (element.width !== layer.width || element.height !== layer.height) {
      element.width = layer.width;
      element.height = layer.height;
    }
    const context = element.getContext("2d")!;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, element.width, element.height);
    context.drawImage(layer, 0, 0);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    pending.forEach((item) => drawLine(context, item.line, scale, picture));
    const active = moving ? byId(moving.id) : null;
    if (active && moving) {
      drawLine(context, { ...active, points: moving.points }, scale, picture);
    }
    for (const pointer of pointers) {
      const trail = trails.current.get(pointer.id);
      if (trail && trail.length >= 2) {
        drawLine(context, { color: pointer.cursor.color ?? colorFor(pointer.id), width: pointer.cursor.width ?? WIDTHS[1]!, points: trail }, scale);
      }
    }
    if (drawing.current) {
      drawLine(context, drawing.current, scale);
    }
    const chosen = byId(selected);
    if (chosen) {
      const line = moving?.id === chosen.id ? { ...chosen, points: moving.points } : chosen;
      const [left, top, right, bottom] = bounds(line);
      context.save();
      context.strokeStyle = "#b9b4ff";
      context.lineWidth = 1;
      context.setLineDash([5, 4]);
      context.strokeRect(left * scale - 4, top * scale - 4, (right - left) * scale + 8, (bottom - top) * scale + 8);
      context.setLineDash([]);
      if (hasCorners(line.kind)) {
        context.fillStyle = "#ecebe7";
        for (const [x, y] of handlesOf(line)) {
          context.fillRect(x! * scale - 4, y! * scale - 4, 8, 8);
          context.strokeRect(x! * scale - 4, y! * scale - 4, 8, 8);
        }
      }
      context.restore();
    }
  }, [baseVersion, pending, frame, selected, moving]);

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  const at = (event: { clientX: number; clientY: number }) => {
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
      image: line.image ?? null,
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

  // Anyone deletes their own marks; the host deletes anyone's.
  const remove = (targets: BoardStroke[]) => {
    const fresh = targets.filter((stroke) => editable(stroke) && !hidden.has(stroke.id) && !deleting.current.has(stroke.id));
    if (fresh.length === 0) {
      return;
    }
    fresh.forEach((stroke) => {
      deleting.current.add(stroke.id);
      deleteQueue.current.push(stroke.id);
    });
    setHidden((current) => new Set([...current, ...fresh.map((stroke) => stroke.id)]));
    setSelected(null);
  };
  const sweep = (x: number, y: number) => remove(shown.filter((stroke) => stroke.kind !== "erase" && picks(stroke, x, y, reach)));

  // The topmost mark under the pointer that this person may change.
  const topmost = (x: number, y: number) => [...shown].reverse().find((stroke) => editable(stroke) && !hidden.has(stroke.id) && picks(stroke, x, y, reach)) ?? null;

  const insertPicture = async (file: File | Blob, name: string) => {
    if (!PICTURE_TYPES.includes(file.type)) {
      onNotice(`${name} is not a picture; the board takes PNG, JPEG, GIF and WebP`);
      return;
    }
    if (file.size > 2_500_000) {
      onNotice(`${name} is larger than 2.5 MB`);
      return;
    }
    const local = URL.createObjectURL(file);
    const probe = new Image();
    const ratio = await new Promise<number>((resolve) => {
      probe.onload = () => resolve(probe.naturalHeight / Math.max(1, probe.naturalWidth));
      probe.onerror = () => resolve(0.75);
      probe.src = local;
    });
    const id = await uploadPicture(file, name);
    if (id === null) {
      URL.revokeObjectURL(local);
      onNotice("the picture did not reach the host; try again");
      return;
    }
    images.current.set(id, probe);
    const element = room.current;
    const middle = element && scale > 0 ? (element.scrollTop + view.height / 2) / scale : 0.4;
    const wide = Math.min(PICTURE_WIDTH, 0.6 / Math.max(ratio, 0.01));
    const tall = wide * ratio;
    const left = (1 - wide) / 2;
    const top = Math.max(0.02, Math.min(MAX_DEPTH - tall, middle - tall / 2));
    place({ kind: "image", image: id, color: "#ffffff", width: 2, points: [left, top, left + wide, top + tall] });
    setTool("select");
  };

  const down = (event: PointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.closest("aside")?.focus({ preventScroll: true });
    if (!canDraw || event.button !== 0) {
      return;
    }
    const { x, y } = at(event);
    if (tool === "select") {
      const chosen = byId(selected);
      const handle = chosen && hasCorners(chosen.kind) ? handlesOf(chosen).findIndex(([hx, hy]) => Math.hypot(hx! - x, hy! - y) <= reach * 1.5) : -1;
      const target = handle >= 0 ? chosen : topmost(x, y);
      setSelected(target?.id ?? null);
      if (target) {
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { id: target.id, handle: handle >= 0 ? handle : null, from: { x, y }, points: [...target.points] };
        setPointerStyle(handle >= 0 ? handleCursor(target, handle) : "grabbing");
      }
      return;
    }
    if (tool === "delete") {
      event.currentTarget.setPointerCapture(event.pointerId);
      sweeping.current = true;
      sweep(x, y);
      return;
    }
    if (tool === "text") {
      event.preventDefault();
      commitText();
      setTyping({ x, y, value: "" });
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    const freehand = tool === "pen" || tool === "eraser";
    drawing.current =
      tool === "eraser"
        ? { kind: "erase", color: "#ffffff", width: eraserWidth(width), points: [x, y] }
        : { kind: tool, color, width, points: freehand ? [x, y] : [x, y, x, y] };
    share(cursor(x, y, tool === "pen"), true);
    redraw();
  };

  const move = (event: PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = at(event);
    const dragged = drag.current;
    if (!dragged && tool === "select" && canDraw) {
      const chosen = byId(selected);
      const handle = chosen && hasCorners(chosen.kind) ? handlesOf(chosen).findIndex(([hx, hy]) => Math.hypot(hx! - x, hy! - y) <= reach * 1.5) : -1;
      const next = chosen && handle >= 0 ? handleCursor(chosen, handle) : topmost(x, y) ? "grab" : undefined;
      if (next !== pointerStyle) {
        setPointerStyle(next);
      }
    }
    if (dragged) {
      const stroke = byId(dragged.id);
      if (stroke) {
        const points =
          dragged.handle === null ? shifted(dragged.points, x - dragged.from.x, y - dragged.from.y) : resized({ ...stroke, points: dragged.points }, dragged.handle, x, y);
        setMoving({ id: dragged.id, points });
      }
      share(cursor(x, y, false));
      return;
    }
    if (tool === "delete" && sweeping.current) {
      sweep(x, y);
    }
    const line = drawing.current;
    if (line && line.kind !== "pen" && line.kind !== "erase") {
      line.points[2] = x;
      line.points[3] = y;
      redraw();
    } else if (line && Math.hypot(x - line.points.at(-2)!, y - line.points.at(-1)!) >= MIN_STEP) {
      line.points.push(x, y);
      redraw();
    }
    share(cursor(x, y, line !== null && line.kind === "pen"));
  };

  const up = (event: PointerEvent<HTMLCanvasElement>) => {
    sweeping.current = false;
    const dragged = drag.current;
    drag.current = null;
    if (dragged) {
      setPointerStyle(dragged.handle === null ? "grab" : pointerStyle);
      const done = moving?.id === dragged.id ? moving.points : null;
      setMoving(null);
      if (done && done.some((value, index) => Math.abs(value - dragged.points[index]!) > 1e-4)) {
        const points = rounded(done);
        setMoved((current) => ({ ...current, [dragged.id]: { points, at: Date.now() } }));
        send({ type: "board.move", stroke_id: dragged.id, points: points as [number, number, ...number[]] });
      }
      return;
    }
    const line = drawing.current;
    drawing.current = null;
    if (!line) {
      return;
    }
    const { x, y } = at(event);
    const freehand = line.kind === "pen" || line.kind === "erase";
    const slip = !freehand && Math.hypot(line.points[2]! - line.points[0]!, line.points[3]! - line.points[1]!) < MIN_SHAPE;
    // The stroke goes before the pen lifts, so the others' trail turns into the stroke without a gap.
    if (!slip) {
      place({ ...line, points: freehand ? thin(line.points) : line.points });
    }
    share(cursor(x, y, false), true);
    redraw();
  };

  const mine = strokes.filter((stroke) => stroke.author_id === meId && !deleting.current.has(stroke.id) && !hidden.has(stroke.id));
  const undo = () => {
    const last = mine.at(-1);
    if (last) {
      remove([last]);
    }
  };

  // Ctrl+Z or Cmd+Z takes back your last mark, unless you are typing somewhere.
  const latestUndo = useRef(undo);
  latestUndo.current = undo;
  useEffect(() => {
    if (!canDraw) {
      return;
    }
    const key = (event: KeyboardEvent) => {
      const typingHere = event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]") !== null;
      if (!typingHere && (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "z") {
        event.preventDefault();
        latestUndo.current();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [canDraw]);

  // Ctrl or Cmd with the wheel, and a pinch on a trackpad, zoom; a plain wheel scrolls.
  const latestZoom = useRef(zoomTo);
  latestZoom.current = zoomTo;
  useEffect(() => {
    const element = room.current;
    if (!element) {
      return;
    }
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        latestZoom.current(zoom * Math.exp(-event.deltaY * 0.01), event);
      }
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [zoom]);

  const toAgent = () =>
    void boardImage([...shown.filter((stroke) => !hidden.has(stroke.id)), ...pending.map((item) => item.line)], picture)
      .then(onSendToAgent)
      .catch(() => undefined);

  const paste = (event: ClipboardEvent<HTMLElement>) => {
    const file = [...event.clipboardData.files].find((item) => PICTURE_TYPES.includes(item.type));
    if (canDraw && file && !(event.target instanceof HTMLTextAreaElement)) {
      event.preventDefault();
      void insertPicture(file, file.name || "pasted-picture.png");
    }
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    const file = [...event.dataTransfer.files].find((item) => PICTURE_TYPES.includes(item.type));
    if (canDraw && file) {
      event.preventDefault();
      void insertPicture(file, file.name);
    }
  };

  return (
    <aside
      className={cx(styles.board, full && styles.full)}
      aria-label="Board"
      tabIndex={-1}
      onPaste={paste}
      onKeyDown={(event) => {
        const chosen = byId(selected);
        if (chosen && (event.key === "Delete" || event.key === "Backspace") && !(event.target instanceof HTMLTextAreaElement)) {
          event.preventDefault();
          remove([chosen]);
        }
      }}
    >
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
                  onClick={() => {
                    setTool(item.kind);
                    if (item.kind !== "select") {
                      setSelected(null);
                    }
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={ICONS[item.kind]} />
                  </svg>
                </button>
              ))}
              <button type="button" className={styles.tool} aria-label="Add a picture" title="add a picture (or paste or drop one)" onClick={() => picker.current?.click()}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={PICTURE_ICON} />
                </svg>
              </button>
              <input
                ref={picker}
                type="file"
                accept={PICTURE_TYPES.join(",")}
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) {
                    void insertPicture(file, file.name);
                  }
                }}
              />
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
            <button className="button small ghost" type="button" onClick={undo} disabled={mine.length === 0} title="Take back your last mark (Ctrl or Cmd + Z)">
              undo
            </button>
          </>
        ) : (
          <span className={styles.note}>viewers watch the board</span>
        )}
        <span className="grow" />
        {isHost ? (
          <button className="button small ghost" type="button" onClick={() => send({ type: "board.clear", mine: false })} disabled={strokes.length === 0}>
            clear all
          </button>
        ) : canDraw ? (
          <button className="button small ghost" type="button" onClick={() => send({ type: "board.clear", mine: true })} disabled={mine.length === 0}>
            clear mine
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
        <div className={styles.zoom} role="group" aria-label="Zoom">
          <button type="button" onClick={() => zoomTo(zoom / ZOOM_STEP)} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out" title="Zoom out (Ctrl or Cmd and the wheel)">
            −
          </button>
          <button type="button" onClick={() => zoomTo(1)} title="Back to 100%" className={styles.zoomLevel}>
            {Math.round(zoom * 100)}%
          </button>
          <button type="button" onClick={() => zoomTo(zoom * ZOOM_STEP)} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in" title="Zoom in (Ctrl or Cmd and the wheel)">
            +
          </button>
        </div>
        <button
          className="button small ghost"
          type="button"
          onClick={onToggleFull}
          aria-label={full ? "Back to half the screen" : "Full screen"}
          title={full ? "Back to half the screen" : "Full screen"}
        >
          <FullIcon full={full} />
        </button>
        <button className="button small ghost" type="button" onClick={onClose} aria-label="Hide the board" title="Hide the board for you">
          ✕
        </button>
      </header>
      <div
        ref={room}
        className={styles.room}
        onDragOver={(event) => {
          if (canDraw && event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
          }
        }}
        onDrop={drop}
      >
        <div className={styles.stage} style={{ width: size.width, height: size.height }}>
          <canvas
            ref={canvas}
            className={cx(styles.canvas, canDraw && (tool === "text" ? styles.texting : tool === "select" ? styles.selecting : styles.drawable))}
            style={{ width: size.width, height: size.height, cursor: tool === "select" ? pointerStyle : undefined }}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={up}
            onPointerLeave={() => (drawing.current || drag.current ? undefined : share(null, true))}
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
