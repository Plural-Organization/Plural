import { useEffect, useState } from "react";
import styles from "./QuoteButton.module.css";

interface Spot {
  text: string;
  top: number;
  left: number;
}

const MAX_CHARS = 4000;

// Watches selections inside [data-quotable] and offers to quote them in the composer.
export function QuoteButton({ enabled, onQuote }: { enabled: boolean; onQuote: (text: string) => void }) {
  const [spot, setSpot] = useState<Spot | null>(null);

  useEffect(() => {
    const update = () => {
      const selection = window.getSelection();
      const text = selection?.toString() ?? "";
      if (!selection || selection.isCollapsed || selection.rangeCount === 0 || text.trim() === "") {
        setSpot(null);
        return;
      }
      const range = selection.getRangeAt(0);
      const node = range.commonAncestorContainer;
      const element = node instanceof Element ? node : node.parentElement;
      if (!element?.closest("[data-quotable]")) {
        setSpot(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight) {
        setSpot(null);
        return;
      }
      setSpot({
        text: text.slice(0, MAX_CHARS),
        top: Math.max(8, rect.top - 40),
        left: Math.min(Math.max(8, rect.left + rect.width / 2), window.innerWidth - 8),
      });
    };
    // Scrolling moves the selection, so the button follows it instead of vanishing.
    document.addEventListener("selectionchange", update);
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("selectionchange", update);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, []);

  if (spot === null || !enabled) {
    return null;
  }
  const quote = () => {
    onQuote(spot.text);
    window.getSelection()?.removeAllRanges();
    setSpot(null);
  };
  return (
    <button
      type="button"
      className={styles.quote}
      style={{ top: spot.top, left: spot.left }}
      // Quote on press, before the click can move focus or clear the selection; a keyboard click still works.
      onMouseDown={(event) => {
        if (event.button !== 0) {
          return;
        }
        event.preventDefault();
        quote();
      }}
      onClick={quote}
    >
      <span aria-hidden="true">❝</span> Quote
    </button>
  );
}
