import type { Activity as Current } from "../../lib/activity";
import { cx } from "../../lib/cx";
import styles from "./Activity.module.css";

export function Activity({ activity }: { activity: Current | null }) {
  if (activity === null) {
    return <div role="status" aria-live="polite" />;
  }
  return (
    <div className={cx(styles.activity, styles[activity.kind])} role="status" aria-live="polite">
      <span className={styles.pulse} aria-hidden="true" />
      <span className={styles.text}>
        {activity.text}
        <span className={styles.dots} aria-hidden="true" />
      </span>
      {activity.detail ? <span className={styles.detail}>{activity.detail}</span> : null}
    </div>
  );
}
