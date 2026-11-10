import { ToggleButton, ToggleButtonGroup, type Key } from "@heroui/react";
import type { Command, PromptMode as Mode } from "@plural/client";
import { Section } from "./Section";

export function PromptMode({ mode, isHost, send }: { mode: Mode; isHost: boolean; send: (command: Command) => void }) {
  return (
    <Section title="prompts">
      {isHost ? (
        <ToggleButtonGroup
          size="sm"
          selectionMode="single"
          disallowEmptySelection
          aria-label="Who may prompt"
          selectedKeys={new Set<Key>([mode])}
          onSelectionChange={(keys) => {
            const next = [...keys][0] as Mode | undefined;
            if (next !== undefined && next !== mode) {
              send({ type: "session.set_prompt_mode", mode: next });
            }
          }}
        >
          <ToggleButton id="open">Open</ToggleButton>
          <ToggleButton id="review"><ToggleButtonGroup.Separator />Review</ToggleButton>
        </ToggleButtonGroup>
      ) : null}
      <p className="muted"><span className="cap">{mode === "open" ? "everyone talks to the agent directly" : "the host approves each prompt first"}</span></p>
    </Section>
  );
}
