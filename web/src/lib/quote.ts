// The selected text as a markdown quote, the way it goes into the composer.
export function asQuote(text: string): string {
  return text
    .replace(/\r\n/g, "\n")
    .trim()
    .split("\n")
    .map((line) => (line.trim() === "" ? ">" : `> ${line}`))
    .join("\n");
}

// Adds a quote to what is already typed, leaving the caret on a fresh line after it.
export function withQuote(draft: string, text: string): string {
  const quote = `${asQuote(text)}\n\n`;
  return draft.trim() === "" ? quote : `${draft.replace(/\s+$/, "")}\n\n${quote}`;
}

export type Segment = { quote: boolean; text: string };

// Splits a message into its quoted and its own parts, so a quote reads as a quote.
export function segments(text: string): Segment[] {
  const out: Segment[] = [];
  for (const line of text.split("\n")) {
    const quote = /^>( |$)/.test(line);
    const body = quote ? line.replace(/^> ?/, "") : line;
    const last = out.at(-1);
    if (last && last.quote === quote) {
      last.text += `\n${body}`;
    } else {
      out.push({ quote, text: body });
    }
  }
  return out
    .map((segment) => ({ ...segment, text: segment.text.replace(/^\n+|\n+$/g, "") }))
    .filter((segment) => segment.text.trim() !== "");
}
