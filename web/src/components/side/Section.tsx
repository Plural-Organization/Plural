import type { ReactNode } from "react";
import styles from "./Sidebar.module.css";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h2 className="cap block font-sans text-[13px] font-medium text-muted">{title}</h2>
      {children}
    </section>
  );
}
