import { useEffect, useRef, useState } from "react";
import { copyText } from "../lib/clipboard";
import { fileName, lineCount, type CanvasDoc } from "../lib/canvas";
import { cx } from "../lib/cx";
import { Markdown } from "./feed/Markdown";
import styles from "./Canvas.module.css";

interface CanvasProps {
  doc: CanvasDoc;
  docs: CanvasDoc[];
  onPick: (id: string) => void;
  onClose: () => void;
}

export function Canvas({ doc, docs, onPick, onClose }: CanvasProps) {
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
      className={styles.canvas}
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
        <span className={styles.meta} aria-live="polite">{doc.live ? <span className={styles.live}>agent is writing</span> : `${lineCount(doc.text)} lines`}</span>
        <span className="grow" />
        <button className="button small" type="button" onClick={copy}>
          {copied ? "copied" : "copy"}
        </button>
        <button className="button small ghost" type="button" onClick={download}>
          download
        </button>
        <button className="button small ghost" type="button" onClick={onClose} aria-label="Close the canvas">
          ✕
        </button>
      </header>
      <div className={styles.body} ref={body} data-quotable>
        {doc.kind === "text" ? (
          <div className={styles.doc}>
            <Markdown text={doc.text} streaming={doc.live} />
          </div>
        ) : (
          <pre className={cx(styles.code, doc.live && styles.writing)}>
            {doc.text.split("\n").map((line, index) => (
              <span key={index} className={styles.line}>
                {line}
              </span>
            ))}
          </pre>
        )}
      </div>
    </aside>
  );
}
