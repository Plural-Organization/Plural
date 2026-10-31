import type { Command, Projection } from "@plural/client";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

interface AgentStatusProps {
  projection: Projection;
  status: string;
  isHost: boolean;
  send: (command: Command) => void;
}

export function AgentStatus({ projection, status, isHost, send }: AgentStatusProps) {
  const running = projection.state.run !== null;
  return (
    <Section title="agent">
      <p className="mono">{projection.agentLabel || "starting…"}</p>
      <p className={running ? styles.running : "muted"}>{running ? status || "working" : "idle"}</p>
      {projection.state.plugin_lines.map((line) => (
        <p key={line.plugin} className="mono">
          <span className="muted">{line.plugin}</span> {line.text}
        </p>
      ))}
      {isHost && running ? (
        <button className="button small danger" type="button" onClick={() => send({ type: "run.abort" })}>
          stop the run <kbd>esc</kbd>
        </button>
      ) : null}
    </Section>
  );
}
