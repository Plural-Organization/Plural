import { Button, Kbd, Spinner } from "@heroui/react";
import type { Command, Projection } from "@plural/client";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";
import { AgentLogo } from "../AgentLogo";
import { agentMark } from "../../lib/agents";

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
      <AgentName label={projection.agentLabel} />
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

// The agent's mark, its name, and the model under it: "Claude Code · claude-sonnet-5-5".
function AgentName({ label }: { label: string }) {
  const [name, ...model] = (label || "starting…").split(" · ");
  return (
    <div className="mb-2 flex items-center gap-3">
      {agentMark(label) ? (
        <span className="grid size-9 flex-none place-items-center rounded-xl bg-surface-secondary">
          <AgentLogo label={label} size={18} decorative />
        </span>
      ) : null}
      <div className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-medium text-foreground">{name}</span>
        {model.length > 0 ? <span className="truncate font-mono text-xs text-muted">{model.join(" · ")}</span> : null}
      </div>
    </div>
  );
}
