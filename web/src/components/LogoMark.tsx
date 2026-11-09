import { LOGO_ROWS } from "../lib/logo-grid";

// The pixel logo as one bare mark in the current text colour, crisp at any size. Each row's runs of pixels are merged into one rect.
const RUNS = LOGO_ROWS.flatMap((row, y) => [...row.matchAll(/#+/g)].map((m) => `M${m.index} ${y}h${m[0].length}v1h-${m[0].length}z`)).join("");
const W = Math.max(...LOGO_ROWS.map((row) => row.length));
const H = LOGO_ROWS.length;

export function LogoMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={size} height={size} aria-hidden="true" shapeRendering="crispEdges" className={className}>
      <path d={RUNS} fill="currentColor" />
    </svg>
  );
}
