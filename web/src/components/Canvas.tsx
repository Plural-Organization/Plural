import { useEffect, useRef, useState, type ReactNode } from "react";
import { copyText } from "../lib/clipboard";
import { fileName, lineCount, type CanvasDoc } from "../lib/canvas";
import { cx } from "../lib/cx";
import { FullIcon } from "./Board";
import { DiffView } from "./DiffView";
import { Markdown } from "./feed/Markdown";
import { SelectionLayer, type Selector } from "./SelectionLayer";
import styles from "./Canvas.module.css";

interface CanvasProps {
  doc: CanvasDoc;
  docs: CanvasDoc[];
  selectors: Selector[];
  full: boolean;
  onToggleFull: () => void;
  onPick: (id: string) => void;
  onClose: () => void;
  // Draws a site document; without it a site shows as its page's path.
  site?: (doc: CanvasDoc) => ReactNode;
}

export function Canvas({ doc, docs, selectors, full, onToggleFull, onPick, onClose, site }: CanvasProps) {
  const body = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
    setCopied(false);
  }, [doc.id]);

  // Follow the end while the agent is still writing.
  useEffect(() => {
    const element = body.current;
    if (element && doc.live) {
      element.scrollTop = element.scrollHeight;
    }
  }, [doc.text, doc.live]);

  const copy = () =>
    void copyText(doc.text).then((ok) => {
      setCopied(ok);
      setTimeout(() => setCopied(false), 1400);
    });

  const download = () => {
    const url = URL.createObjectURL(new Blob([doc.text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName(doc);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <aside
      className={cx(styles.canvas, full && styles.full)}
      aria-label="Canvas"
      onKeyDown={(event) => {
        // Inside the canvas Esc closes it; elsewhere it still stops the run.
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className={styles.bar}>
        {docs.length > 1 ? (
          <select className={styles.pick} value={doc.id} onChange={(event) => onPick(event.target.value)} aria-label="Documents in this session">
            {docs.map((item, index) => (
              <option key={item.id} value={item.id}>
                {index + 1}. {item.title}
              </option>
            ))}
          </select>
        ) : (
          <span className={styles.title}>{doc.title}</span>
        )}
        <span className={styles.meta} aria-live="polite">
          {doc.live ? <span className={styles.live}>agent is writing</span> : doc.kind === "site" ? "live preview" : `${lineCount(doc.text)} lines`}
        </span>
        <span className="grow" />
        {doc.kind === "site" ? null : (
          <>
            <button className="button small" type="button" onClick={copy}>
              {copied ? "copied" : "copy"}
            </button>
            <button className="button small ghost" type="button" onClick={download}>
              download
            </button>
          </>
        )}
        <button
          className="button small ghost"
          type="button"
          onClick={onToggleFull}
          aria-label={full ? "Back to half the screen" : "Full screen"}
          title={full ? "Back to half the screen" : "Full screen"}
        >
          <FullIcon full={full} />
        </button>
        <button className="button small ghost" type="button" onClick={onClose} aria-label="Close the canvas">
          ✕
        </button>
      </header>
      {doc.kind === "site" ? (
        <div className={styles.site}>{site ? site(doc) : <span className={styles.meta}>{doc.text}</span>}</div>
      ) : (
        <div className={styles.body} ref={body} data-quotable>
          <SelectionLayer selectors={selectors} version={doc.text} />
          {doc.kind === "diff" ? (
            <div className={styles.diff}>
              <DiffView diff={doc.text} anchor={`canvas:${doc.id}`} />
            </div>
          ) : doc.kind === "text" ? (
            <div className={styles.doc} data-anchor={`canvas:${doc.id}`}>
              <Markdown text={doc.text} streaming={doc.live} />
            </div>
          ) : (
            <pre className={cx(styles.code, doc.live && styles.writing)} data-anchor={`canvas:${doc.id}`}>
              {doc.text.split("\n").map((line, index) => (
                <span key={index} className={styles.line}>
                  {line}
                </span>
              ))}
            </pre>
          )}
        </div>
      )}
    </aside>
  );
}
