const FENCE = /^\s{0,3}(```|~~~)/;

export function committableEnd(text: string, from: number): number {
  let end = from;
  let fenced = false;
  let cursor = from;
  let blank = false;
  while (cursor < text.length) {
    const newline = text.indexOf("\n", cursor);
    const lineEnd = newline === -1 ? text.length : newline;
    const line = text.slice(cursor, lineEnd);
    if (FENCE.test(line)) {
      fenced = !fenced;
    }
    const complete = newline !== -1;
    if (!fenced && complete && line.trim() === "") {
      blank = true;
      end = lineEnd + 1;
    } else if (blank && line.trim() !== "") {
      blank = false;
    }
    if (!complete) {
      break;
    }
    cursor = lineEnd + 1;
  }
  return end;
}

export function tailLines(text: string, columns: number, maxLines: number): { text: string; hidden: boolean } {
  const lines = text.split("\n");
  let used = 0;
  let start = lines.length;
  while (start > 0) {
    const line = lines[start - 1] ?? "";
    const height = Math.max(1, Math.ceil(line.length / Math.max(1, columns)));
    if (used + height > maxLines) {
      break;
    }
    used += height;
    start -= 1;
  }
  return { text: lines.slice(start).join("\n"), hidden: start > 0 };
}
