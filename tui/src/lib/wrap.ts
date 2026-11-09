export function truncate(text: string, width: number): string {
  const chars = Array.from(text);
  return chars.length <= width ? text : `${chars.slice(0, Math.max(0, width - 1)).join("")}…`;
}
