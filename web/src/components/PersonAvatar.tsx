import { Avatar } from "@heroui/react";
import type { CSSProperties } from "react";

// Everyone starts with a soft orb of colour, the same one every time for the same person.
const ORBS: [string, string, string][] = [
  ["#b4e1ee", "#35b6e6", "#6c63f2"],
  ["#b6ecd0", "#3fcf8e", "#2f7fe0"],
  ["#d9c8f5", "#a56cf0", "#5b45e6"],
  ["#f7d9bd", "#f59a4a", "#e0503a"],
  ["#f6c9d6", "#ee6a9a", "#a13fd8"],
  ["#f3ecb4", "#e8c53a", "#39b57a"],
  ["#c5d4f7", "#5a86f0", "#30c4c0"],
  ["#f4c7bd", "#ea6a4f", "#d9367a"],
  ["#c9f0e6", "#34c7a8", "#8a5cf0"],
  ["#e6d3f2", "#c76ee0", "#ec6a7a"],
  ["#d6e9b8", "#8ccb45", "#2fa8c9"],
];

export function orbFor(seed: string): CSSProperties {
  let hash = 0;
  for (const char of seed) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  const [base, middle, core] = ORBS[hash % ORBS.length]!;
  return { background: `radial-gradient(circle at ${54 + (hash % 24)}% ${58 + (hash % 19)}%, ${core} 0, ${middle} 34%, transparent 68%), ${base}` };
}

export function PersonAvatar({ seed, size = "sm" }: { seed: string; size?: "sm" | "md" | "lg" }) {
  return (
    <Avatar size={size}>
      <Avatar.Fallback style={orbFor(seed)}>{""}</Avatar.Fallback>
    </Avatar>
  );
}
