import { Button, Kbd, Spinner } from "@heroui/react";
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
      <p className={running ? styles.running : "muted"}>
        {running ? <Spinner size="sm" color="current" className="mr-2 align-middle" /> : null}
        <span className="cap">{running ? status || "working" : "idle"}</span>
      </p>
      {projection.state.plugin_lines.map((line) => (
        <p key={line.plugin} className="mono">
          <span className="muted">{line.plugin}</span> {line.text}
        </p>
      ))}
      {isHost && running ? (
        <Button size="sm" variant="danger" onPress={() => send({ type: "run.abort" })}>
          Stop the run
          <Kbd className="h-5 px-1 text-[11px]"><Kbd.Content>esc</Kbd.Content></Kbd>
        </Button>
      ) : null}
    </Section>
  );
}
