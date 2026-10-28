import type { ReactNode } from "react";
import styles from "./Sidebar.module.css";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h2 className="label">{title}</h2>
      {children}
    </section>
  );
}
