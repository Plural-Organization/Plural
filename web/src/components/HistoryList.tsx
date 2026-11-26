import type { HistoryView } from "@plural/client";
import styles from "./Composer.module.css";

// What the up key walks through, above the composer: a few earlier messages around the current one, and where it is in
// the list, counting down from the newest ("100 / 100") as each step goes further back.
export function HistoryList({ view, onPick }: { view: HistoryView; onPick: (index: number) => void }) {
  return (
    <div className={styles.history}>
      <div className={styles.historyHead}>
        <span>Earlier messages</span>
        <span className={styles.count} role="status" aria-label={`Message ${view.at} of ${view.of}`}>
          {view.at}
          <span aria-hidden="true"> / {view.of}</span>
        </span>
      </div>
      <ul role="listbox" aria-label="Earlier messages" className={styles.historyList}>
        {view.rows.map((row) => {
          const lines = row.text.split("\n");
          return (
            <li
              key={row.index}
              role="option"
              aria-selected={row.current}
              className={styles.past}
              // The mouse keeps the focus in the box, so the arrows go on from the picked message.
              onMouseDown={(event) => {
                event.preventDefault();
                onPick(row.index);
              }}
            >
              <span className={styles.pastText}>{lines[0]}</span>
              {lines.length > 1 ? <span className="muted">+{lines.length - 1} lines</span> : null}
            </li>
          );
        })}
      </ul>
      <div className={styles.historyKeys}>
        <span><kbd>↑</kbd><kbd>↓</kbd> browse</span>
        <span><kbd>↵</kbd> send</span>
        <span><kbd>esc</kbd> back to what you were typing</span>
      </div>
    </div>
  );
}
