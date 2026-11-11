import { Button, Card, Chip, Description, Modal } from "@heroui/react";
import { SlidersHorizontal } from "@phosphor-icons/react";
import { useState } from "react";
import type { AgentSetupState } from "../hooks/useAgentSetup";
import { AgentLogo } from "./AgentLogo";
import { AgentSetup } from "./AgentSetup";

// The agent a room will run, in one row; setting it up happens in a window so the page stays short.
export function AgentCard({ setup }: { setup: AgentSetupState }) {
  const [open, setOpen] = useState(false);
  const { provider, choice, blocker } = setup;
  const ready = provider !== null && blocker === null;
  return (
    <>
      <Card variant="secondary">
        <Card.Content className="flex-row items-center gap-3">
          <AgentLogo label={provider?.label} size={22} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium">{provider?.label ?? "Agent"}</p>
            <Description className="truncate">{provider === null ? (setup.error ?? "Reading this computer…") : (blocker ?? (choice?.model || "Default model"))}</Description>
          </div>
          {provider === null ? null : (
            <Chip size="sm" variant="soft" color={ready ? "success" : "warning"} className="flex-none">
              <Chip.Label>{ready ? "Ready" : "Needs setup"}</Chip.Label>
            </Chip>
          )}
          <Button size="sm" variant="secondary" onPress={() => setOpen(true)}>
            <SlidersHorizontal size={15} />
            {ready ? "Change" : "Set up"}
          </Button>
        </Card.Content>
      </Card>
      <Modal.Backdrop isOpen={open} onOpenChange={setOpen}>
        <Modal.Container scroll="inside">
          <Modal.Dialog className="sm:max-w-[34rem]">
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading className="font-display text-2xl font-medium tracking-[-0.02em]">Agent</Modal.Heading>
            </Modal.Header>
            <Modal.Body className="px-1 pb-1">
              <AgentSetup setup={setup} />
            </Modal.Body>
            <Modal.Footer>
              <Button slot="close">Done</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </>
  );
}
