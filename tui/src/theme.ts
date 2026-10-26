export const theme = {
  accent: "#7aa2f7",
  text: undefined,
  dim: "gray",
  ok: "#9ece6a",
  warn: "#e0af68",
  danger: "#f7768e",
  info: "#7dcfff",
  code: "#bb9af7",
  addBg: "#1f3a2a",
  removeBg: "#3d1f2b",
} as const;

const PALETTE = ["#7dcfff", "#bb9af7", "#e0af68", "#9ece6a", "#f7768e", "#73daca", "#ff9e64", "#7aa2f7"];

export function colorFor(participantId: string): string {
  let hash = 0;
  for (const char of participantId) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length] as string;
}
