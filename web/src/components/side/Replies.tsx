import { ToggleButton, ToggleButtonGroup, type Key } from "@heroui/react";
import type { ChatMode, Command } from "@plural/client";
import { Section } from "./Section";

// When the agent answers: everyone sees it, so they know whether a plain message reaches the agent.
export function Replies({ mode, isHost, send }: { mode: ChatMode; isHost: boolean; send: (command: Command) => void }) {
  return (
    <Section title="agent answers">
      {isHost ? (
        <ToggleButtonGroup
          size="sm"
          selectionMode="single"
          disallowEmptySelection
          aria-label="When the agent answers"
          selectedKeys={new Set<Key>([mode])}
          onSelectionChange={(keys) => {
            const next = [...keys][0] as ChatMode | undefined;
            if (next !== undefined && next !== mode) {
              send({ type: "session.set_chat_mode", mode: next });
            }
          }}
        >
          <ToggleButton id="mention">@plrl</ToggleButton>
          <ToggleButton id="all"><ToggleButtonGroup.Separator />Every message</ToggleButton>
        </ToggleButtonGroup>
      ) : null}
      <p className="muted"><span className="cap">{mode === "mention" ? "messages that tag @plrl; the rest is chat it reads" : "every message; /team writes to people only"}</span></p>
    </Section>
  );
}
