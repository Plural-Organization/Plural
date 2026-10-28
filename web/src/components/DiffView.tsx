import { parseDiff } from "@plural/client";
import { cx } from "../lib/cx";
import styles from "./DiffView.module.css";

interface DiffViewProps {
  diff: string;
  // Shown rows; the rest are counted below. Undefined shows everything.
  limit?: number;
  anchor?: string;
}

export function DiffView({ diff, limit, anchor }: DiffViewProps) {
  const rows = parseDiff(diff);
  const shown = limit === undefined ? rows : rows.slice(0, limit);
  return (
    <div className={styles.diff}>
      <div data-anchor={anchor}>
        {shown.map((row, index) =>
          row.kind === "gap" ? (
            <div key={index} className={cx(styles.row, styles.gap)}>
              ⋯
            </div>
          ) : (
            <div key={index} className={cx(styles.row, styles[row.kind])}>
              <span className={styles.no} aria-hidden="true" data-no={row.newNo ?? row.oldNo ?? ""} />
              <span className={styles.sign} aria-hidden="true" data-sign={row.kind === "add" ? "+" : row.kind === "del" ? "−" : " "} />
              <span className={styles.text}>{row.text || " "}</span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}

export function diffRows(diff: string): number {
  return parseDiff(diff).length;
}
