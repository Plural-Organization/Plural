import { ruleLine, type Command, type Projection } from "@plural/client";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

export function Rules({ projection, send }: { projection: Projection; send: (command: Command) => void }) {
  const policy = projection.state.policy;
  return (
    <Section title="session rules">
      {policy.length === 0 ? (
        <p className="muted">none yet · {projection.basePolicy.length} built-in</p>
      ) : (
        <ul className={styles.rules}>
          {policy.map((rule) => (
            <li key={rule.id}>
              <span className={`mono ${styles.rule}`}>{ruleLine(rule)}</span>
              <button type="button" className="link-button" onClick={() => send({ type: "policy.remove", rule_id: rule.id })}>
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
