// A long paste is shown in the composer as a short label and sent in full, as Claude Code does.

const MAX_LINES = 5;
const MAX_CHARS = 800;

export function shouldCollapse(text: string): boolean {
  return text.split("\n").length > MAX_LINES || text.length > MAX_CHARS;
}

export function pasteLabel(index: number, text: string): string {
  const lines = text.split("\n").length;
  return lines > 1 ? `[Pasted text #${index} +${lines} lines]` : `[Pasted text #${index} ${text.length} chars]`;
}

// Puts the pasted text back where its label still stands; a label the person deleted sends nothing.
export function expandPastes(text: string, pastes: ReadonlyMap<string, string>): string {
  let out = text;
  for (const [label, full] of pastes) {
    out = out.split(label).join(full);
  }
  return out;
}
