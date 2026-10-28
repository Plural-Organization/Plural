import type { BoardShape } from "@plural/client";

// The board is 4:5, taller than wide to fill the side panel; every point is a share of its width or height.
export const BOARD_RATIO = 4 / 5;
// Stroke widths are in thousandths of the board width.
export const WIDTH_UNIT = 1000;
export const MAX_POINTS = 4000;

export const COLORS = ["#ecebe7", "#b9b4ff", "#9fd8ff", "#8fdca6", "#ecc47e", "#ff9a9a", "#ff9fc4"];
export const WIDTHS = [2, 4, 9];
export const BACKGROUND = "#16171a";
export const TOOLS: { kind: BoardShape; label: string }[] = [
  { kind: "pen", label: "pen" },
  { kind: "line", label: "line" },
  { kind: "arrow", label: "arrow" },
  { kind: "rect", label: "box" },
  { kind: "ellipse", label: "circle" },
  { kind: "text", label: "text" },
];

export interface Line {
  kind?: BoardShape;
  color: string;
  width: number;
  points: number[];
  text?: string | null;
}

// Text grows with the pen width so the three widths read as small, medium and large.
export function textSize(width: number, boardWidth: number): number {
  return ((14 + width * 4) * boardWidth) / WIDTH_UNIT;
}

function pen(context: CanvasRenderingContext2D, points: number[], width: number, height: number): void {
  const x = (index: number) => points[index]! * width;
  const y = (index: number) => points[index + 1]! * height;
  if (points.length === 2) {
    context.beginPath();
    context.arc(x(0), y(0), context.lineWidth / 2, 0, Math.PI * 2);
    context.fill();
    return;
  }
  context.beginPath();
  context.moveTo(x(0), y(0));
  for (let index = 2; index < points.length - 2; index += 2) {
    context.quadraticCurveTo(x(index), y(index), (x(index) + x(index + 2)) / 2, (y(index) + y(index + 2)) / 2);
  }
  context.lineTo(x(points.length - 2), y(points.length - 2));
  context.stroke();
}

// Draws one mark: a pen line through its points with soft curves, a shape between two corners, or a text.
export function drawLine(context: CanvasRenderingContext2D, line: Line, width: number, height: number): void {
  const points = line.points;
  if (points.length < 2) {
    return;
  }
  context.strokeStyle = line.color;
  context.fillStyle = line.color;
  context.lineWidth = (line.width * width) / WIDTH_UNIT;
  context.lineCap = "round";
  context.lineJoin = "round";
  const kind = line.kind ?? "pen";
  if (kind === "text") {
    const size = textSize(line.width, width);
    context.font = `500 ${size}px "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif`;
    context.textBaseline = "top";
    (line.text ?? "").split("\n").forEach((row, index) => context.fillText(row, points[0]! * width, points[1]! * height + index * size * 1.25));
    return;
  }
  if (kind === "pen" || points.length < 4) {
    pen(context, points, width, height);
    return;
  }
  const [x0, y0, x1, y1] = [points[0]! * width, points[1]! * height, points[2]! * width, points[3]! * height];
  context.beginPath();
  if (kind === "rect") {
    context.roundRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0), Math.min(8, context.lineWidth * 2));
  } else if (kind === "ellipse") {
    context.ellipse((x0 + x1) / 2, (y0 + y1) / 2, Math.abs(x1 - x0) / 2, Math.abs(y1 - y0) / 2, 0, 0, Math.PI * 2);
  } else {
    context.moveTo(x0, y0);
    context.lineTo(x1, y1);
    if (kind === "arrow") {
      const angle = Math.atan2(y1 - y0, x1 - x0);
      const head = Math.max(10, context.lineWidth * 4);
      context.moveTo(x1, y1);
      context.lineTo(x1 - head * Math.cos(angle - 0.45), y1 - head * Math.sin(angle - 0.45));
      context.moveTo(x1, y1);
      context.lineTo(x1 - head * Math.cos(angle + 0.45), y1 - head * Math.sin(angle + 0.45));
    }
  }
  context.stroke();
}

// Keeps a long line under the host's limit by dropping every other point until it fits.
export function thin(points: number[]): number[] {
  let current = points;
  while (current.length > MAX_POINTS) {
    const next: number[] = [];
    for (let index = 0; index < current.length; index += 4) {
      next.push(current[index]!, current[index + 1]!);
    }
    const last = current.length - 2;
    if (next[next.length - 2] !== current[last]) {
      next.push(current[last]!, current[last + 1]!);
    }
    current = next;
  }
  return current;
}

export function sameLine(a: Line, b: Line): boolean {
  return (a.kind ?? "pen") === (b.kind ?? "pen") && (a.text ?? null) === (b.text ?? null) && a.color === b.color && a.width === b.width && a.points.length === b.points.length && a.points.every((value, index) => Math.abs(value - b.points[index]!) < 1e-9);
}

// The whole board as a PNG, the way the agent receives it.
export async function boardImage(lines: Line[], width = 1600): Promise<Blob> {
  const height = Math.round(width / BOARD_RATIO);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d")!;
  context.fillStyle = BACKGROUND;
  context.fillRect(0, 0, width, height);
  lines.forEach((line) => drawLine(context, line, width, height));
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("the board could not be saved"))), "image/png"));
}
