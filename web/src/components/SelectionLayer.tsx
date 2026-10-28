import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import type { TextSelection } from "@plural/client";
import { colorFor } from "../lib/colors";
import { rangeOf } from "../lib/selection";
import styles from "./SelectionLayer.module.css";

export interface Selector {
  id: string;
  name: string;
  selection: TextSelection;
}

interface Box {
  key: string;
  id: string;
  name: string | null;
  top: number;
  left: number;
  width: number;
  height: number;
}

// Draws other people's selections over the anchors inside the parent, which must be positioned.
export function SelectionLayer({ selectors, version }: { selectors: Selector[]; version: unknown }) {
  const layer = useRef<HTMLDivElement>(null);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [tick, setTick] = useState(0);

  useLayoutEffect(() => {
    const host = layer.current?.parentElement;
    if (!host) {
      return;
    }
    const remeasure = () => setTick((value) => value + 1);
    const observer = new ResizeObserver(remeasure);
    observer.observe(host);
    // A diff scrolls sideways inside the host, which moves the text under the boxes.
    host.addEventListener("scroll", remeasure, true);
    return () => {
      observer.disconnect();
      host.removeEventListener("scroll", remeasure, true);
    };
  }, []);

  useLayoutEffect(() => {
    const host = layer.current?.parentElement;
    if (!host) {
      return;
    }
    if (selectors.length === 0) {
      setBoxes((current) => (current.length === 0 ? current : []));
      return;
    }
    const origin = host.getBoundingClientRect();
    const next: Box[] = [];
    for (const selector of selectors) {
      const anchor = host.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(selector.selection.anchor)}"]`);
      const range = anchor ? rangeOf(anchor, selector.selection.start, selector.selection.end) : null;
      if (range === null) {
        continue;
      }
      [...range.getClientRects()]
        .filter((rect) => rect.width > 0 && rect.height > 0)
        .forEach((rect, index) => {
          next.push({
            key: `${selector.id}:${index}`,
            id: selector.id,
            name: index === 0 ? selector.name : null,
            top: rect.top - origin.top + host.scrollTop,
            left: rect.left - origin.left + host.scrollLeft,
            width: rect.width,
            height: rect.height,
          });
        });
    }
    setBoxes(next);
  }, [selectors, version, tick]);

  return (
    <div ref={layer} className={styles.layer} aria-hidden="true">
      {boxes.map((box) => (
        <div
          key={box.key}
          className={styles.box}
          style={{ top: box.top, left: box.left, width: box.width, height: box.height, "--who": colorFor(box.id) } as CSSProperties}
        >
          {box.name ? <span className={styles.name}>{box.name}</span> : null}
        </div>
      ))}
    </div>
  );
}
