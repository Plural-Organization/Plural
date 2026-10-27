import { useEffect, useRef } from "react";
import { LOGO_ROWS } from "./logo-grid";

const H = LOGO_ROWS.length;
const W = Math.max(...LOGO_ROWS.map((row) => row.length));
const MX = (W - 1) / 2;
const MY = (H - 1) / 2;
const SIDES = ["top", "right", "bottom", "left"] as const;
type Side = (typeof SIDES)[number];

function sideAt(x: number, y: number): Side {
  return Math.abs(x - MX) > Math.abs(y - MY) ? (x > MX ? "right" : "left") : y > MY ? "bottom" : "top";
}

const FIGURES: Record<Side, [number, number][]> = (() => {
  const on = (x: number, y: number) => y >= 0 && y < H && x >= 0 && x < W && LOGO_ROWS[y]?.[x] === "#";
  const seen = LOGO_ROWS.map(() => new Array<boolean>(W).fill(false));
  const figures: Record<Side, [number, number][]> = { top: [], right: [], bottom: [], left: [] };
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!on(x, y) || seen[y]![x]) {
        continue;
      }
      const cells: [number, number][] = [];
      const stack: [number, number][] = [[x, y]];
      seen[y]![x] = true;
      while (stack.length > 0) {
        const [cx, cy] = stack.pop()!;
        cells.push([cx, cy]);
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const nx = cx + dx;
            const ny = cy + dy;
            if (on(nx, ny) && !seen[ny]![nx]) {
              seen[ny]![nx] = true;
              stack.push([nx, ny]);
            }
          }
        }
      }
      const cx = cells.reduce((sum, [px]) => sum + px, 0) / cells.length;
      const cy = cells.reduce((sum, [, py]) => sum + py, 0) / cells.length;
      figures[sideAt(cx, cy)].push(...cells);
    }
  }
  return figures;
})();

interface LogoProps {
  size: number;
  dance?: boolean;
  className?: string;
  label?: string;
}

export function Logo({ size, dance = false, className, label = "Plural" }: LogoProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const focus = useRef<Side | "all" | null>(null);

  useEffect(() => {
    const element = canvas.current;
    if (element === null) {
      return;
    }
    const context = element.getContext("2d")!;
    const margin = dance ? 4 : 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    element.width = Math.round(size * dpr);
    element.height = Math.round(size * dpr);
    const n = Math.max(1, Math.floor(element.width / (Math.max(W, H) + margin * 2)));
    const ox = Math.round((element.width - n * W) / 2);
    const oy = Math.round((element.height - n * H) / 2);
    const ink = getComputedStyle(element).color;
    let frame = 0;

    const draw = (now: number) => {
      const t = now / 1000;
      const current = focus.current;
      context.clearRect(0, 0, element.width, element.height);
      for (const side of SIDES) {
        const dancing = current === "all" || current === side;
        const phase = current === "all" ? SIDES.indexOf(side) * 0.8 : 0;
        const dx = dancing ? Math.round(Math.sin(t * 5 + phase) * 1.2) : 0;
        const dy = dancing ? -Math.round(Math.abs(Math.sin(t * 10 + phase)) * 2.6) : 0;
        context.fillStyle = ink;
        context.globalAlpha = current === null || dancing ? 1 : 0.25;
        for (const [x, y] of FIGURES[side]) {
          context.fillRect(ox + (x + dx) * n, oy + (y + dy) * n, n, n);
        }
      }
      context.globalAlpha = 1;
      frame = current === null ? 0 : requestAnimationFrame(draw);
    };
    draw(performance.now());
    if (!dance) {
      return;
    }
    const move = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect();
      const x = ((event.clientX - rect.left) * (element.width / rect.width) - ox) / n;
      const y = ((event.clientY - rect.top) * (element.height / rect.height) - oy) / n;
      const next = Math.hypot(x - MX, y - (MY + 2)) < 7 ? "all" : x < -3 || y < -3 || x > W + 3 || y > H + 3 ? null : sideAt(x, y);
      if (next !== focus.current) {
        const idle = focus.current === null;
        focus.current = next;
        if (idle || next === null) {
          cancelAnimationFrame(frame);
          draw(performance.now());
        }
      }
    };
    const leave = () => {
      focus.current = null;
      cancelAnimationFrame(frame);
      draw(performance.now());
    };
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(frame);
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
    };
  }, [size, dance]);

  return <canvas ref={canvas} className={className} style={{ width: size, height: size }} role="img" aria-label={label} />;
}
