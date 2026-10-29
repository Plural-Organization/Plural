import type { TextSelection } from "@plural/client";

// Selections are shared as character offsets into the text of one [data-anchor] element.
// Everyone renders the same items, so the same offsets cover the same words on every screen.

export function anchorOf(node: Node | null): HTMLElement | null {
  const element = node instanceof Element ? node : (node?.parentElement ?? null);
  return element?.closest<HTMLElement>("[data-anchor]") ?? null;
}

function offsetIn(anchor: HTMLElement, node: Node, offset: number): number {
  const range = document.createRange();
  range.selectNodeContents(anchor);
  range.setEnd(node, offset);
  return range.toString().length;
}

// The browser selection as one anchor and offsets, or null when it is empty or outside the shared items.
export function readSelection(selection: Selection | null): TextSelection | null {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const anchor = anchorOf(range.startContainer);
  if (anchor === null) {
    return null;
  }
  const length = (anchor.textContent ?? "").length;
  const start = offsetIn(anchor, range.startContainer, range.startOffset);
  const end = anchor.contains(range.endContainer) ? offsetIn(anchor, range.endContainer, range.endOffset) : length;
  const name = anchor.dataset.anchor ?? "";
  // The host takes anchors up to 200 characters and offsets up to a million.
  if (end <= start || name.length > 200 || start > 1_000_000) {
    return null;
  }
  return { anchor: name, start, end: Math.min(end, length, 1_000_000) };
}

// A DOM range over the given offsets inside the anchor, walking its text nodes.
export function rangeOf(anchor: HTMLElement, start: number, end: number): Range | null {
  const walker = document.createTreeWalker(anchor, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let seen = 0;
  let started = false;
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const size = node.textContent?.length ?? 0;
    if (!started && start <= seen + size) {
      range.setStart(node, start - seen);
      started = true;
    }
    if (started && end <= seen + size) {
      range.setEnd(node, end - seen);
      return range;
    }
    seen += size;
  }
  return null;
}

export function sameSelection(a: TextSelection | null, b: TextSelection | null): boolean {
  return a === b || (a !== null && b !== null && a.anchor === b.anchor && a.start === b.start && a.end === b.end);
}
