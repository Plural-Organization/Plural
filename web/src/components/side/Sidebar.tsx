import type { Command, Projection } from "@plural/client";
import { cx } from "../../lib/cx";
import { AgentStatus } from "./AgentStatus";
import { People } from "./People";
import { PromptMode } from "./PromptMode";
import { Replies } from "./Replies";
import { Queue } from "./Queue";
import { Rules } from "./Rules";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";
import { Button } from "@heroui/react";
import { GearSix, SidebarSimple } from "@phosphor-icons/react";

interface SidebarProps {
  projection: Projection;
  status: string;
  waiting: number;
  open: boolean;
  tucked: boolean;
  onHide: () => void;
  send: (command: Command) => void;
  onInvite: (role: "participant" | "viewer") => void;
  /** Opens the room settings (the host only). */
  onSettings: () => void;
}

export function Sidebar({ projection, status, waiting, open, tucked, onHide, send, onInvite, onSettings }: SidebarProps) {
  const isHost = projection.me?.role === "host";
  return (
    <aside className={cx(styles.side, open && styles.open, tucked && styles.tucked)} aria-label="The room">
      <div className={styles.head}>
        <span>The room</span>
        <div className="flex items-center">
          {isHost ? (
            <Button isIconOnly variant="ghost" size="sm" aria-label="Room settings" onPress={onSettings}>
              <GearSix size={18} />
            </Button>
          ) : null}
          <Button isIconOnly variant="ghost" size="sm" aria-label="Hide the room panel" onPress={onHide}>
            <SidebarSimple size={18} className="-scale-x-100" />
          </Button>
        </div>
      </div>
      <People projection={projection} isHost={isHost} send={send} onInvite={onInvite} />
      {isHost ? (
        <Section title="waits for you">
          <p className={waiting > 0 ? styles.attention : "muted"}>{waiting > 0 ? `${waiting} above the input` : "nothing"}</p>
        </Section>
      ) : null}
      <Queue projection={projection} isHost={isHost} send={send} />
      <AgentStatus projection={projection} status={status} isHost={isHost} send={send} onSwitch={isHost ? onSettings : undefined} />
      <Replies mode={projection.state.chat_mode} isHost={isHost} send={send} />
      <PromptMode mode={projection.state.prompt_mode} isHost={isHost} send={send} />
      {isHost ? <Rules projection={projection} send={send} /> : null}
    </aside>
  );
}
