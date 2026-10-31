import type { ReactNode } from "react";
import type { Command, Projection } from "@plural/client";
import { cx } from "../../lib/cx";
import { AgentStatus } from "./AgentStatus";
import { People } from "./People";
import { PromptMode } from "./PromptMode";
import { Queue } from "./Queue";
import { Rules } from "./Rules";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

interface SidebarProps {
  projection: Projection;
  status: string;
  waiting: number;
  open: boolean;
  send: (command: Command) => void;
  onInvite: (role: "participant" | "viewer") => void;
  // The team's sessions, when this browser is in a team.
  team?: ReactNode;
}

export function Sidebar({ projection, status, waiting, open, send, onInvite, team = null }: SidebarProps) {
  const isHost = projection.me?.role === "host";
  return (
    <aside className={cx(styles.side, open && styles.open)} aria-label="The room">
      <People projection={projection} isHost={isHost} send={send} onInvite={onInvite} />
      {team ? <Section title="team">{team}</Section> : null}
      {isHost ? (
        <Section title="waits for you">
          <p className={waiting > 0 ? styles.attention : "muted"}>{waiting > 0 ? `${waiting} above the input` : "nothing"}</p>
        </Section>
      ) : null}
      <Queue projection={projection} isHost={isHost} send={send} />
      <AgentStatus projection={projection} status={status} isHost={isHost} send={send} />
      <PromptMode mode={projection.state.prompt_mode} isHost={isHost} send={send} />
      {isHost ? <Rules projection={projection} send={send} /> : null}
    </aside>
  );
}
