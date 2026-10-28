const PALETTE = ["#b9b4ff", "#9fd8ff", "#ffc48a", "#a6e3b4", "#ff9fc4", "#e3d27a", "#c7b5ff", "#8fe0d6"];

export function colorFor(id: string): string {
  let hash = 0;
  for (const char of id) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length]!;
}
