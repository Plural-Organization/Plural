import { cx } from "../lib/cx";
import type { Space } from "../App";
import styles from "./Spaces.module.css";

interface SpacesProps {
  spaces: Space[];
  current: string;
  onSwitch: (room: string) => void;
  onClose: (room: string) => void;
}

// The sessions open in this tab. Each stays connected, so a click moves at once, without a reconnect.
export function Spaces({ spaces, current, onSwitch, onClose }: SpacesProps) {
  return (
    <ul className={styles.list}>
      {spaces.map((space) => {
        const here = space.link.room === current;
        const title = space.owner ?? space.link.room;
        return (
          <li key={space.link.room} className={cx(styles.space, here && styles.here)}>
            <button className={styles.open} type="button" disabled={here} onClick={() => onSwitch(space.link.room)} title={here ? "you are here" : `go to ${title}`}>
              <span className={styles.name}>{space.owner === null ? "your room" : space.owner}</span>
              <span className={cx("mono", styles.room)}>{space.link.room}</span>
            </button>
            <button className={styles.close} type="button" aria-label={`Close ${title}`} title="close" onClick={() => onClose(space.link.room)}>
              ×
            </button>
          </li>
        );
      })}
      <li className={cx("muted", styles.hint)}>alt+← alt+→ move between them</li>
    </ul>
  );
}
