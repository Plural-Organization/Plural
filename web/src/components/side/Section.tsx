import type { ReactNode } from "react";
import styles from "./Sidebar.module.css";

// `tour` names the section for the first-visit tour (lib/onboarding.ts).
export function Section({ title, tour, children }: { title: string; tour?: string; children: ReactNode }) {
  return (
    <section className={styles.section} data-tour={tour}>
      <h2 className="cap block font-sans text-[13px] font-medium text-muted">{title}</h2>
      {children}
    </section>
  );
}
