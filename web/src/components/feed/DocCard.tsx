import styles from "./DocCard.module.css";

const PREVIEW_LINES = 4;

interface DocCardProps {
  title: string;
  meta: string;
  preview: string;
  onOpen: () => void;
}

// What stands in the feed for a document that lives in the canvas.
export function DocCard({ title, meta, preview, onOpen }: DocCardProps) {
  return (
    <button type="button" className={styles.card} onClick={onOpen} aria-label={`Open ${title} in the canvas`}>
      <span className={styles.head}>
        <span className={styles.title}>{title}</span>
        <span className={styles.meta}>{meta}</span>
        <span className={styles.open}>open ›</span>
      </span>
      <span className={styles.preview} aria-hidden="true">
        {preview.split("\n").slice(0, PREVIEW_LINES).join("\n")}
      </span>
    </button>
  );
}
