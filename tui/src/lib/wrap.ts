export function plainWidth(text: string): number {
  return Array.from(text).length;
}

export function truncate(text: string, width: number): string {
  const chars = Array.from(text);
  return chars.length <= width ? text : `${chars.slice(0, Math.max(0, width - 1)).join("")}…`;
}

export function previewLines(text: string, limit: number): { lines: string[]; more: number } {
  const lines = text.replace(/\s+$/, "").split("\n");
  return { lines: lines.slice(0, limit), more: Math.max(0, lines.length - limit) };
}
